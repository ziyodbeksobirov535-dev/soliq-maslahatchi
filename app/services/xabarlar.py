"""Yangilik va o'zgarish xabarlari: tayyorlash → admin tasdig'i → kunduzi hamma foydalanuvchiga yuborish.

    RSS (yangiliklar, relevant)        ┐
    haftalik yangilash (ozgarishlar)   ┴→ xabar (kutilmoqda) → adminlarga ko'rinish [✅ Yuborish] [❌ Bekor]
                                          → tasdiqlandi → NEWS_SEND_START_HOUR..END_HOUR oralig'ida → yuborildi

- Yangilik xabari hujjat havolasi emas — qisqa tahlil: sarlavha, metadata, asosiy qoidalar (hujjat bandlari),
  kimga tegishli, kuchga kirish sanasi. Claude bo'lsa — oddiy tildagi sarlavha va bandlar, har bir band
  hujjat elementiga bog'langan va tekshirilgan (uydirma band tashlanadi); Claude'siz — hujjatning birinchi
  raqamli bandlari (`usul = 'matndan'`). Sanalar va raqamlar faqat metadata'dan.
- O'zgarish xabari — kuzatiladigan hujjatdagi o'zgargan/qo'shilgan/chiqarilgan moddalar ro'yxati.
- Tasdiqsiz hech kimga yuborilmaydi. Kechasi tasdiqlangani ertalab yuboriladi.
- Qayta ishga tushish xavfsiz: `xabarlar.kalit` UNIQUE, `xabar_yuborishlar` PK — hech kimga ikki marta ketmaydi.
- Botni bloklagan foydalanuvchi belgilanadi (`foydalanuvchilar.bloklagan`) va keyingi xabarlar unga ketmaydi.
- Qabul qiluvchilar: NEWS_AUDIENCE — "admins" (hozircha, foydalanuvchi qarori) yoki "all" (/start bosgan hamma).
- Kanal: avtomatik emas — admin tasdiqlangan xabar ostidagi "📢 Kanalga joylash" tugmasini bosadi (NEWS_CHANNEL
  berilgan bo'lsa); bir marta (`xabarlar.kanal_xabar_id`). Kanal postida faqat havola tugmalari.
- NEWS_REQUIRE_AI: xabar faqat Claude bilan tayyorlanadi; AI ishlamasa keyingi urinishda qayta.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from app.ai.client import LLMError, Usage
from app.bot.formatting import esc, link
from app.config import Settings
from app.retrieval.query import normalize

log = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MAX_POINTS = 3
POINT_CHARS = 220
DIGEST_ELEMENTS = 40
MAX_CHANGE_LINES = 10
MAX_CHANGE_BUTTONS = 3
SEND_DELAY_SECONDS = 0.05  # ~20 xabar/soniya — Telegram chegarasidan past
STALE_SEND_MINUTES = 30
_BAND_RE = re.compile(r"^\s*\d{1,2}[.)]\s")
_send_lock = asyncio.Lock()
_background: set[asyncio.Task] = set()  # create_task havolasi GC'da yo'qolmasin

# Kalit so'z (news.KUCHLI_SOZLAR / SOHA_SOZLARI) → foydalanuvchiga ko'rsatiladigan soha nomi.
SOHA_LABELS = {
    "soliq": "soliq", "solig": "soliq", "qqs": "QQS", "aksiz": "aksiz", "bojxona": "bojxona", "boj": "bojxona",
    "buxgalter": "buxgalteriya", "moliyaviy hisobot": "moliyaviy hisobot", "bhms": "buxgalteriya",
    "mehnat": "mehnat", "ish haqi": "ish haqi", "pensiya": "pensiya", "tadbirkor": "tadbirkorlik",
    "yakka tartibdagi": "YaTT", "imtiyoz": "imtiyozlar", "subsidiya": "subsidiyalar", "litsenziya": "litsenziya",
    "ruxsatnoma": "ruxsatnomalar", "qurilish": "qurilish", "qishloq xojalig": "qishloq xo'jaligi",
    "fermer": "qishloq xo'jaligi", "transport": "transport", "yuk tashish": "transport", "bank": "bank",
    "savdo": "savdo", "turizm": "turizm", "it-park": "IT", "raqamli": "IT", "eksport": "eksport",
    "import": "import", "investitsiya": "investitsiya", "davlat xarid": "davlat xaridlari",
    "elektron tijorat": "elektron tijorat", "ijara": "ijara", "yer uchastka": "yer", "sugurta": "sug'urta",
}
CHANGE_LABELS = {"qo'shilgan": "qo'shildi", "o'zgargan": "o'zgartirildi", "o'chirilgan": "chiqarildi"}


@dataclass
class Draft:
    turi: str  # yangilik | ozgarish
    kalit: str
    lex_id: str
    matn: str  # Telegram HTML
    havola: str
    usul: str  # llm | matndan
    tugmalar: list[list[str]] = field(default_factory=list)  # [[matn, callback_data], ...]


def is_daytime(settings: Settings, now: datetime | None = None) -> bool:
    local = (now or datetime.now(settings.tz)).astimezone(settings.tz)
    return settings.news_send_start_hour <= local.hour < settings.news_send_end_hour


def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def meta_line(doc_type: str | None, number: str | None, adoption, effective) -> str:
    return " · ".join(p for p in [
        doc_type or "", f"№{number}" if number else "",
        f"qabul qilingan {adoption:%d.%m.%Y}" if adoption else "",
        f"kuchga kirish {effective:%d.%m.%Y}" if effective else "",
    ] if p)


def soha_labels(hits: list[str] | None) -> list[str]:
    return list(dict.fromkeys(SOHA_LABELS[h] for h in (hits or []) if h in SOHA_LABELS))[:4]


def extract_points(texts: list[str]) -> list[str]:
    """Claude'siz: hujjatning birinchi raqamli bandlari (bo'lmasa — birinchi mazmunli xatboshilar)."""
    bands = [t for t in texts if _BAND_RE.match(t) and len(t) > 30]
    points = bands[:MAX_POINTS] or [t for t in texts if len(t) > 40][:2]
    return [_trim(t, POINT_CHARS) for t in points]


NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")
SHORT_TYPES = (
    ("prezidentining farmoni", "Prezident farmoni"),
    ("prezidentining qarori", "Prezident qarori"),
    ("vazirlar mahkamasining qarori", "Vazirlar Mahkamasi qarori"),
    ("qonuni", "Qonun"),
)


def short_type(doc_type: str | None) -> str:
    norm = normalize(doc_type or "")
    return next((label for key, label in SHORT_TYPES if key in norm), doc_type or "Hujjat")


def hashtags(labels: list[str]) -> str:
    tags = ["#" + re.sub(r"[^\w]", "", label.replace(" ", "_").replace("'", "")) for label in labels]
    return " ".join(dict.fromkeys(t for t in tags if len(t) > 1))


def _strip_band_number(text: str) -> str:
    return _BAND_RE.sub("", text, count=1).strip()


def render_news(y, points: list[str], *, sarlavha: str | None = None, mohiyat: str | None = None,
                kimga: list[str] | None = None, amaliy: str | None = None,
                point_links: list[str] | None = None) -> str:
    """Telegram xabari: turi va raqami, sarlavha, qisqacha, raqamlangan asosiy o'zgarishlar, kimga tegishli,
    nima qilish kerak, sanalar, heshteglar. Sana va raqam — faqat metadata'dan."""
    head = f"📰 <b>{esc(short_type(y['doc_type']))}</b>"
    if y["number"]:
        head += f" · №{esc(y['number'])}"
    lines = [head, "", f"<b>{esc(sarlavha or y['title'])}</b>"]
    if sarlavha:  # oddiy tildagi sarlavha — rasmiy nom ham ko'rinsin
        lines.append(f"<i>{esc(y['title'])}</i>")
    summary = mohiyat or y["summary"]
    if summary:
        lines += ["", f"💡 {esc(summary)}"]
    if points:
        lines += ["", "📌 <b>Asosiy o'zgarishlar:</b>"]
        for i, p in enumerate(points[: len(NUMBERS)]):
            src = f" {link(point_links[i], '↗')}" if point_links else ""
            lines.append(f"{NUMBERS[i]} {esc(p)}{src}")
    if kimga:
        lines += ["", "👥 <b>Kimga tegishli:</b> " + esc(", ".join(kimga))]
    if amaliy:
        lines += ["", f"✅ <b>Nima qilish kerak:</b> {esc(amaliy)}"]
    dates = [f"qabul qilingan {y['adoption_date']:%d.%m.%Y}" if y["adoption_date"] else "",
             f"kuchga kiradi {y['effective_date']:%d.%m.%Y}" if y["effective_date"] else ""]
    dates = [d for d in dates if d]
    if dates:
        lines += ["", "📅 " + " · ".join(dates)]
    tags = hashtags(soha_labels(y["keyword_hits"]))
    if tags:
        lines += ["", tags]
    return "\n".join(lines).strip()


async def _doc_elements(conn: asyncpg.Connection, lex_id: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT e.id, e.text, e.link FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id
        WHERE h.lex_id = $1 AND e.kind IN ('text', 'table') ORDER BY e.order_no LIMIT $2
        """,
        lex_id, DIGEST_ELEMENTS,
    )


async def build_news_draft(conn: asyncpg.Connection, y, llm, *, require_ai: bool = False) -> Draft | None:
    """Yangilik xabari. AI (Claude) bo'lsa — oddiy tildagi sarlavha va tekshirilgan bandlar; bo'lmasa —
    hujjatning birinchi bandlari. `require_ai` va AI natija bermasa — None (keyingi urinishda qayta)."""
    rows = await _doc_elements(conn, y["lex_id"])
    draft = Draft("yangilik", f"yangilik:{y['lex_id']}", y["lex_id"], "", y["url"], "matndan")
    if llm is not None and rows and hasattr(llm, "news_digest"):
        meta = meta_line(y["doc_type"], y["number"], y["adoption_date"], y["effective_date"])
        by_id = {f"EL-{r['id']}": r for r in rows}
        try:
            d = await asyncio.to_thread(llm.news_digest, y["title"], meta,
                                        [(sid, r["text"][:1500]) for sid, r in by_id.items()], Usage())
            valid = [(p.matn.strip(), by_id[p.source_id]["link"]) for p in d.bandlar
                     if p.source_id in by_id and p.matn.strip()][:4]
            if valid:  # hech bo'lmasa bitta tekshirilgan band
                draft.matn = render_news(y, [v[0] for v in valid], sarlavha=_trim(d.sarlavha, 120),
                                         mohiyat=d.mohiyat.strip() or None, kimga=[k for k in d.kimga if k][:4],
                                         amaliy=d.amaliy.strip() or None, point_links=[v[1] for v in valid])
                draft.usul = "llm"
        except LLMError as exc:
            log.warning("news digest llm failed lex_id=%s error=%s", y["lex_id"], exc)
    if draft.usul == "matndan":
        if require_ai:
            return None
        points = [_strip_band_number(p) for p in extract_points([r["text"] for r in rows])]
        draft.matn = render_news(y, points, kimga=soha_labels(y["keyword_hits"]))
    return draft


async def build_change_draft(conn: asyncpg.Connection, document_id: int) -> tuple[Draft, list[int]] | None:
    """Hujjatdagi hali xabar qilinmagan o'zgarishlar → bitta xabar (moddalar bo'yicha guruhlangan)."""
    doc = await conn.fetchrow("SELECT lex_id, name, url, current_version FROM hujjatlar WHERE id = $1", document_id)
    rows = await conn.fetch(
        """
        SELECT o.id, o.change_type, e.modda_raqami, e.birlik, e.birlik_nomi,
               a.text AS heading, coalesce(a.link, e.link) AS link
        FROM ozgarishlar o
        LEFT JOIN elementlar e ON e.document_id = o.document_id AND e.element_id = o.element_id
        LEFT JOIN LATERAL (
            SELECT x.text, x.link FROM elementlar x
            WHERE x.document_id = o.document_id AND x.kind = 'article' AND x.modda_raqami = e.modda_raqami
            ORDER BY x.order_no LIMIT 1
        ) a ON e.modda_raqami IS NOT NULL
        WHERE o.document_id = $1 AND o.xabar_id IS NULL
        ORDER BY e.order_no NULLS LAST, o.id  -- hujjatdagi tartib bo'yicha
        """,
        document_id,
    )
    if doc is None or not rows:
        return None
    units: dict[tuple[str, str], dict] = {}
    other = 0
    for r in rows:
        if r["modda_raqami"]:
            key = ("m", r["modda_raqami"])
            title = r["heading"] or f"{r['modda_raqami']}-modda"
        elif r["birlik"]:
            key = ("b", r["birlik"])
            title = r["birlik_nomi"] or "Bo'lim"
        else:  # chiqarilgan element — joriy matnda yo'q
            other += 1
            continue
        u = units.setdefault(key, {"title": title, "link": r["link"], "types": set()})
        u["types"].add(r["change_type"])
    lines = [f"⚠️ <b>{esc(doc['name'])} — o'zgartirishlar</b>"]
    if doc["current_version"]:
        lines.append(f"<i>Joriy tahrir: {esc(doc['current_version'])} · Lex.uz</i>")
    lines.append("")
    items = list(units.items())
    for (_, _), u in items[:MAX_CHANGE_LINES]:
        kind = CHANGE_LABELS[next(iter(u["types"]))] if len(u["types"]) == 1 else "o'zgartirildi"
        lines.append(f"• {link(u['link'], _trim(u['title'], 120)) if u['link'] else esc(u['title'])} — {kind}")
    rest = len(items) - MAX_CHANGE_LINES
    if rest > 0:
        lines.append(f"• yana {rest} ta modda/bo'lim")
    if other:
        lines.append(f"• matndan chiqarilgan qismlar: {other} ta")
    lines += ["", "O'zgargan moddalarning joriy matnini quyidagi tugmalar orqali ko'rishingiz mumkin."]
    buttons = [[f"📖 {unit_id}-modda", f"v:m:{doc['lex_id']}:{unit_id}"]
               for (kind, unit_id), _ in items if kind == "m"][:MAX_CHANGE_BUTTONS]
    draft = Draft("ozgarish", f"ozgarish:{document_id}:{max(r['id'] for r in rows)}", doc["lex_id"],
                  "\n".join(lines), doc["url"], "matndan", buttons)
    return draft, [r["id"] for r in rows]


async def save_draft(conn: asyncpg.Connection, d: Draft) -> int | None:
    return await conn.fetchval(
        """
        INSERT INTO xabarlar (turi, kalit, lex_id, matn, havola, tugmalar, usul)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
        ON CONFLICT (kalit) DO NOTHING RETURNING id
        """,
        d.turi, d.kalit, d.lex_id, d.matn, d.havola, json.dumps(d.tugmalar, ensure_ascii=False), d.usul,
    )


async def prepare_news(pool: asyncpg.Pool, llm, settings: Settings) -> list[int]:
    """Yangi relevant RSS hujjatlari uchun xabar (bir hujjat — bir xabar)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT y.* FROM yangiliklar y
            WHERE y.relevant AND coalesce(y.pub_date, y.created_at) >= now() - make_interval(days => $1)
              AND NOT EXISTS (SELECT 1 FROM xabarlar x WHERE x.kalit = 'yangilik:' || y.lex_id)
            ORDER BY coalesce(y.pub_date, y.created_at)
            """,
            settings.news_max_age_days,
        )
    ids, skipped = [], 0
    for y in rows:
        try:
            async with pool.acquire() as conn:
                draft = await build_news_draft(conn, y, llm, require_ai=settings.news_require_ai)
                if draft is None:
                    skipped += 1
                    continue
                xid = await save_draft(conn, draft)
            if xid:
                ids.append(xid)
        except Exception:  # bitta hujjat qolganlarini to'xtatmasin
            log.error("news draft failed lex_id=%s", y["lex_id"], exc_info=True)
    if skipped:
        log.warning("news drafts waiting for AI=%d (NEWS_REQUIRE_AI; Claude ishlamayapti — kredit?)", skipped)
    return ids


async def prepare_changes(pool: asyncpg.Pool) -> list[int]:
    """Kuzatiladigan hujjatlardagi yangi o'zgarishlar uchun xabar (hujjat bo'yicha bittadan)."""
    async with pool.acquire() as conn:
        docs = await conn.fetch("SELECT DISTINCT document_id FROM ozgarishlar WHERE xabar_id IS NULL")
    ids = []
    for d in docs:
        try:
            async with pool.acquire() as conn, conn.transaction():
                built = await build_change_draft(conn, d["document_id"])
                if built is None:
                    continue
                draft, change_ids = built
                xid = await save_draft(conn, draft)
                if xid:
                    await conn.execute("UPDATE ozgarishlar SET xabar_id = $1 WHERE id = ANY($2::bigint[])",
                                       xid, change_ids)
                    ids.append(xid)
        except Exception:
            log.error("change draft failed document_id=%s", d["document_id"], exc_info=True)
    return ids


# --- tugmalar ---------------------------------------------------------------------------


def _buttons(x) -> list[list[InlineKeyboardButton]]:
    tugmalar = x["tugmalar"]
    if isinstance(tugmalar, str):
        tugmalar = json.loads(tugmalar)
    rows = [[InlineKeyboardButton(text=t, callback_data=c)] for t, c in tugmalar]
    rows.append([InlineKeyboardButton(text="📄 Lex.uz'da ochish", url=x["havola"])])
    return rows


def message_keyboard(x) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_buttons(x))


def _channel_row(x, settings: Settings) -> list[list[InlineKeyboardButton]]:
    """Kanalga joylash — faqat admin qarori bilan, alohida tugma (NEWS_CHANNEL berilgan va hali joylanmagan)."""
    if not settings.news_channel or x["kanal_xabar_id"] is not None or x["holat"] == "bekor":
        return []
    return [[InlineKeyboardButton(text="📢 Kanalga joylash", callback_data=f"x:ch:{x['id']}")]]


def admin_keyboard(x, settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_buttons(x) + [[
        InlineKeyboardButton(text="✅ Yuborish", callback_data=f"x:ok:{x['id']}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"x:no:{x['id']}"),
    ]])


def channel_keyboard(x, bot_username: str | None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="📄 Lex.uz'da ochish", url=x["havola"])]]
    if bot_username:
        rows.append([InlineKeyboardButton(text="🤖 Botda savol berish", url=f"https://t.me/{bot_username}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def status_keyboard(x, status: str, settings: Settings) -> InlineKeyboardMarkup:
    """Hal qilingan ko'rinish: amal tugmalari o'rniga holat (bosilsa hech narsa qilmaydi) va kanal tugmasi."""
    return InlineKeyboardMarkup(inline_keyboard=_buttons(x) + _channel_row(x, settings) + [[
        InlineKeyboardButton(text=status, callback_data="x:-")]])


# --- admin tasdig'i ------------------------------------------------------------------------


async def recipient_count(conn: asyncpg.Connection, settings: Settings) -> int:
    if settings.news_audience == "admins":
        return len(settings.admin_telegram_ids)
    return await conn.fetchval("SELECT count(*) FROM foydalanuvchilar WHERE active AND NOT bloklagan")


def audience_text(n: int, settings: Settings) -> str:
    return f"{n} ta adminga" if settings.news_audience == "admins" else f"{n} ta foydalanuvchiga"


def preview_header(x, n: int, settings: Settings) -> str:
    turi = "yangilik" if x["turi"] == "yangilik" else "o'zgarish"
    ai = "" if x["usul"] == "llm" else " · AI'siz"
    return f"🆕 <b>Tasdiq kutilmoqda</b> · {turi}{ai} · {audience_text(n, settings)}\n\n"


async def show_preview(bot: Bot, pool: asyncpg.Pool, settings: Settings, xabar_id: int, chat_id: int) -> bool:
    """/admin → xabarni qayta ko'rsatish (tasdiq tugmalari bilan); ko'rinish holat yangilanishiga qo'shiladi."""
    async with pool.acquire() as conn:
        x = await conn.fetchrow("SELECT * FROM xabarlar WHERE id = $1 AND holat = 'kutilmoqda'", xabar_id)
        if x is None:
            return False
        n = await recipient_count(conn, settings)
    m = await bot.send_message(chat_id, preview_header(x, n, settings) + x["matn"], parse_mode=ParseMode.HTML,
                               link_preview_options=NO_PREVIEW, reply_markup=admin_keyboard(x, settings))
    async with pool.acquire() as conn:
        await conn.execute("UPDATE xabarlar SET admin_xabarlar = admin_xabarlar || $2::jsonb WHERE id = $1",
                           xabar_id, json.dumps([[chat_id, m.message_id]]))
    return True


async def notify_admins(bot: Bot, pool: asyncpg.Pool, settings: Settings) -> int:
    """Adminlarga hali ko'rsatilmagan 'kutilmoqda' xabarlar ko'rinishini yuboradi."""
    if not settings.admin_telegram_ids:
        log.warning("xabarlar: ADMIN_TELEGRAM_IDS bo'sh — xabarlar tasdiqlanmaydi va yuborilmaydi")
        return 0
    async with pool.acquire() as conn:
        pending = await conn.fetch(
            "SELECT * FROM xabarlar WHERE holat = 'kutilmoqda' AND admin_xabarlar = '[]'::jsonb ORDER BY id")
        n = await recipient_count(conn, settings)
    shown = 0
    for x in pending:
        header = preview_header(x, n, settings)
        sent: list[list[int]] = []
        for admin_id in sorted(settings.admin_telegram_ids):
            try:
                m = await bot.send_message(admin_id, header + x["matn"], parse_mode=ParseMode.HTML,
                                           link_preview_options=NO_PREVIEW, reply_markup=admin_keyboard(x, settings))
                sent.append([admin_id, m.message_id])
            except TelegramAPIError as exc:  # admin botga /start bosmagan bo'lishi mumkin
                log.warning("admin preview failed admin=%s xabar=%s error=%s", admin_id, x["id"], type(exc).__name__)
        if sent:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE xabarlar SET admin_xabarlar = $2::jsonb WHERE id = $1", x["id"],
                                   json.dumps(sent))
            shown += 1
    return shown


async def _mark_previews(bot: Bot, x, status: str, settings: Settings) -> None:
    previews = x["admin_xabarlar"]
    if isinstance(previews, str):
        previews = json.loads(previews)
    for chat_id, message_id in previews:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id,
                                                reply_markup=status_keyboard(x, status, settings))
        except TelegramAPIError as exc:
            log.warning("admin preview update failed chat=%s error=%s", chat_id, type(exc).__name__)


async def decide(bot: Bot, pool: asyncpg.Pool, settings: Settings, xabar_id: int, admin_id: int,
                 approve: bool) -> str:
    """Admin qarori. Birinchi qaror kuchda; natija — adminga ko'rsatiladigan qisqa matn."""
    async with pool.acquire() as conn:
        x = await conn.fetchrow(
            """
            UPDATE xabarlar SET holat = $2, hal_qilgan = $3, hal_qilingan_at = now()
            WHERE id = $1 AND holat = 'kutilmoqda' RETURNING *
            """,
            xabar_id, "tasdiqlandi" if approve else "bekor", admin_id,
        )
        if x is None:
            holat = await conn.fetchval("SELECT holat FROM xabarlar WHERE id = $1", xabar_id)
            return f"Bu xabar allaqachon hal qilingan ({holat})" if holat else "Xabar topilmadi"
    if not approve:
        await _mark_previews(bot, x, "❌ Bekor qilindi", settings)
        return "Bekor qilindi"
    if is_daytime(settings):
        await _mark_previews(bot, x, "✅ Tasdiqlandi — yuborilmoqda", settings)
        task = asyncio.create_task(send_approved(bot, pool, settings))
        _background.add(task)
        task.add_done_callback(_background.discard)
        return "Tasdiqlandi, yuborilmoqda"
    when = f"{settings.news_send_start_hour:02d}:00"
    await _mark_previews(bot, x, f"✅ Tasdiqlandi — {when} da yuboriladi", settings)
    return f"Tasdiqlandi, {when} da yuboriladi"


# --- yuborish ------------------------------------------------------------------------------


async def _send_one(bot: Bot, chat_id: int, x) -> str:
    for attempt in range(2):
        try:
            await bot.send_message(chat_id, x["matn"], parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW,
                                   reply_markup=message_keyboard(x))
            return "ok"
        except TelegramRetryAfter as exc:
            if attempt:
                return "xato"
            await asyncio.sleep(exc.retry_after)
        except TelegramForbiddenError:
            return "bloklangan"
        except TelegramAPIError as exc:
            log.warning("xabar send failed chat=%s xabar=%s error=%s", chat_id, x["id"], type(exc).__name__)
            return "xato"
    return "xato"


async def post_to_channel(bot: Bot, pool: asyncpg.Pool, settings: Settings, xabar_id: int) -> str:
    """Admin "📢 Kanalga joylash" tugmasi: tasdiqlangan xabarni NEWS_CHANNEL ga bir marta joylaydi."""
    async with pool.acquire() as conn:
        x = await conn.fetchrow("SELECT * FROM xabarlar WHERE id = $1", xabar_id)
    if x is None or not settings.news_channel:
        return "Kanal sozlanmagan"
    if x["kanal_xabar_id"] is not None:
        return "Allaqachon kanalga joylangan"
    if x["holat"] not in ("tasdiqlandi", "yuborildi"):
        return "Avval xabarni tasdiqlang"
    try:
        me = await bot.me()
        username = me.username
    except (TelegramAPIError, AttributeError):
        username = None
    try:
        m = await bot.send_message(settings.news_channel, x["matn"], parse_mode=ParseMode.HTML,
                                   link_preview_options=NO_PREVIEW, reply_markup=channel_keyboard(x, username))
    except TelegramAPIError as exc:  # bot kanalda admin emas yoki kanal noto'g'ri
        log.warning("kanalga joylanmadi channel=%s xabar=%s error=%s", settings.news_channel, x["id"],
                    type(exc).__name__)
        return "Kanalga joylanmadi — bot kanalda adminmi?"
    async with pool.acquire() as conn:
        await conn.execute("UPDATE xabarlar SET kanal_xabar_id = $2 WHERE id = $1", x["id"], m.message_id)
    return "Kanalga joylandi"


async def _recipients(conn: asyncpg.Connection, settings: Settings, xabar_id: int) -> list[int]:
    """Hali yuborilmaganlar: NEWS_AUDIENCE=admins — faqat adminlar; all — /start bosgan hamma."""
    if settings.news_audience == "admins":
        sent = {r["telegram_id"] for r in await conn.fetch(
            "SELECT telegram_id FROM xabar_yuborishlar WHERE xabar_id = $1", xabar_id)}
        return [a for a in sorted(settings.admin_telegram_ids) if a not in sent]
    return [r["telegram_id"] for r in await conn.fetch(
        """
        SELECT f.telegram_id FROM foydalanuvchilar f
        WHERE f.active AND NOT f.bloklagan
          AND NOT EXISTS (SELECT 1 FROM xabar_yuborishlar y WHERE y.xabar_id = $1 AND y.telegram_id = f.telegram_id)
        ORDER BY f.id
        """,
        xabar_id,
    )]


async def _deliver(bot: Bot, pool: asyncpg.Pool, settings: Settings, x) -> dict[str, int]:
    async with pool.acquire() as conn:
        recipients = await _recipients(conn, settings, x["id"])
    counts = {"ok": 0, "bloklangan": 0, "xato": 0}
    for chat_id in recipients:
        result = await _send_one(bot, chat_id, x)
        counts[result] += 1
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO xabar_yuborishlar (xabar_id, telegram_id, natija) VALUES ($1, $2, $3) "
                "ON CONFLICT DO NOTHING", x["id"], chat_id, result)
            if result == "bloklangan":
                await conn.execute("UPDATE foydalanuvchilar SET bloklagan = true WHERE telegram_id = $1", chat_id)
        await asyncio.sleep(SEND_DELAY_SECONDS)
    async with pool.acquire() as conn:
        x = await conn.fetchrow(
            "UPDATE xabarlar SET holat = 'yuborildi', yuborildi_at = now() WHERE id = $1 RETURNING *", x["id"])
        total = await conn.fetchval(
            "SELECT count(*) FROM xabar_yuborishlar WHERE xabar_id = $1 AND natija = 'ok'", x["id"])
    await _mark_previews(bot, x, f"✅ Yuborildi: {audience_text(total, settings)}", settings)
    log.info("xabar sent id=%s ok=%d blocked=%d failed=%d", x["id"], counts["ok"], counts["bloklangan"], counts["xato"])
    return counts


async def send_approved(bot: Bot, pool: asyncpg.Pool, settings: Settings, now: datetime | None = None) -> int:
    """Tasdiqlangan xabarlarni yuboradi (faqat kunduzi). Natija — yuborilgan xabarlar soni."""
    if not is_daytime(settings, now):
        return 0
    done = 0
    async with _send_lock:
        while True:
            async with pool.acquire() as conn:
                x = await conn.fetchrow(
                    """
                    UPDATE xabarlar SET yuborish_boshlangan = now()
                    WHERE id = (
                        SELECT id FROM xabarlar
                        WHERE holat = 'tasdiqlandi'
                          AND (yuborish_boshlangan IS NULL
                               OR yuborish_boshlangan < now() - make_interval(mins => $1))
                        ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
                    RETURNING *
                    """,
                    STALE_SEND_MINUTES,
                )
            if x is None:
                break
            await _deliver(bot, pool, settings, x)
            done += 1
    return done


async def publish(bot: Bot, pool: asyncpg.Pool, settings: Settings, llm) -> None:
    """Scheduler: kunduzi — yangi xabarlarni tayyorlash, adminlarga ko'rsatish, tasdiqlanganlarni yuborish."""
    if not is_daytime(settings):
        return
    await prepare_news(pool, llm, settings)
    await prepare_changes(pool)
    await notify_admins(bot, pool, settings)
    await send_approved(bot, pool, settings)
