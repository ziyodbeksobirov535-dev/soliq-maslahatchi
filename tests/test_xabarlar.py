"""Yangilik va o'zgarish xabarlari: tayyorlash, admin tasdig'i, kunduzi yuborish (soxta Telegram bot bilan).

DB testlari TEST_DATABASE_URL talab qiladi; hujjatlar — tests/test_sections.py dagi farmon va qonun namunasi.
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from app.ai.client import LLMError
from app.ai.schemas import DigestPoint, NewsDigest
from app.collector.importer import import_document
from app.config import Settings
from app.database.connection import connect, create_pool
from app.services import xabarlar
from tests.conftest import run
from tests.test_sections import ARTICLE_DOC_ID, DOC_ID, code_like, decree, element

TODAY = date(2026, 9, 27)
ADMIN = 1000
BLOCKED = 7777
NEWS = {
    "lex_id": DOC_ID, "title": "Soliq hisobotini soddalashtirish to'g'risida", "doc_type": "Prezident farmoni",
    "number": "PF-1", "adoption_date": date(2026, 9, 25), "effective_date": date(2026, 10, 1),
    "url": f"https://lex.uz/docs/{DOC_ID}", "summary": None, "keyword_hits": ["soliq", "hisobot", "qurilish"],
}


def settings(*, day: bool = True, **kw) -> Settings:
    if day:
        hours = dict(news_send_start_hour=0, news_send_end_hour=24)
    else:  # hozirgi soat oraliqqa kirmaydi
        h = datetime.now(ZoneInfo("Asia/Tashkent")).hour
        hours = dict(news_send_start_hour=h + 1, news_send_end_hour=h + 2) if h < 22 else \
            dict(news_send_start_hour=0, news_send_end_hour=1)
    kw.setdefault("news_require_ai", False)  # testlarda AI'siz ham xabar tayyorlansin (alohida test bor)
    return Settings(_env_file=None, admin_telegram_ids=frozenset({ADMIN}), **hours, **kw)


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str, object]] = []
        self.edits: list[tuple[int, int, object]] = []

    async def send_message(self, chat_id, text, **kw):
        if chat_id == BLOCKED:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text=text),
                                         message="bot was blocked by the user")
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.edits.append((chat_id, message_id, reply_markup))

    async def me(self):
        return SimpleNamespace(username="soliqexpertibot")


def buttons(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


async def with_conn(dsn, fn):
    conn = await connect(dsn)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def with_pool(dsn, fn):
    async def go():
        pool = await create_pool(dsn, min_size=1, max_size=3)
        try:
            return await fn(pool)
        finally:
            await asyncio.gather(*xabarlar._background, return_exceptions=True)
            await pool.close()

    return run(go())


@pytest.fixture
def xdb(db):
    async def clean(conn):
        await conn.execute("DELETE FROM xabarlar")
        await conn.execute("DELETE FROM yangiliklar")
        await conn.execute("DELETE FROM foydalanuvchilar")
        await conn.execute("DELETE FROM hujjatlar WHERE lex_id = ANY($1::text[])", [DOC_ID, ARTICLE_DOC_ID])

    async def setup(conn):
        await clean(conn)
        await import_document(conn, decree(), None, TODAY)
        await conn.executemany("INSERT INTO foydalanuvchilar (telegram_id) VALUES ($1)",
                               [(ADMIN,), (2001,), (2002,), (BLOCKED,)])

    run(with_conn(db, setup))
    yield db
    run(with_conn(db, clean))


async def add_news(conn, **kw):
    y = {**NEWS, **kw}
    await conn.execute(
        """
        INSERT INTO yangiliklar (lex_id, title, doc_type, number, adoption_date, effective_date, url, pub_date,
                                 keyword_hits, relevant, summary)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        y["lex_id"], y["title"], y["doc_type"], y["number"], y["adoption_date"], y["effective_date"], y["url"],
        y.get("pub_date", datetime.now(timezone.utc)), y["keyword_hits"], y.get("relevant", True), y["summary"])


# --- bazasiz ---------------------------------------------------------------------------


def test_extract_points_prefers_numbered_bands():
    texts = ["Maqsadida:", "1. Birinchi muhim qoida bu yerda yozilgan.", "Izoh matni.",
             "2. Ikkinchi muhim qoida bu yerda yozilgan.", "3. Uchinchi qoida ham yetarlicha uzun.",
             "4. To'rtinchi qoida ham yetarlicha uzun matn."]
    assert xabarlar.extract_points(texts) == texts[1:2] + texts[3:5]
    assert xabarlar.extract_points(["Qisqa", "Bandsiz, lekin yetarlicha uzun va mazmunli xatboshi matni."]) == \
        ["Bandsiz, lekin yetarlicha uzun va mazmunli xatboshi matni."]


def test_soha_labels_and_meta():
    assert xabarlar.soha_labels(["soliq", "solig", "qurilish", "noma'lum"]) == ["soliq", "qurilish"]
    assert xabarlar.meta_line("Farmon", "PF-1", date(2026, 9, 25), None) == "Farmon · №PF-1 · qabul qilingan 25.09.2026"


def test_is_daytime_window():
    s = Settings(_env_file=None, news_send_start_hour=9, news_send_end_hour=20)
    tz = ZoneInfo("Asia/Tashkent")
    assert xabarlar.is_daytime(s, datetime(2026, 9, 28, 9, 0, tzinfo=tz))
    assert xabarlar.is_daytime(s, datetime(2026, 9, 28, 19, 59, tzinfo=tz))
    assert not xabarlar.is_daytime(s, datetime(2026, 9, 28, 20, 0, tzinfo=tz))
    assert not xabarlar.is_daytime(s, datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc))  # 08:00 Toshkent


# --- tayyorlash --------------------------------------------------------------------------


def test_news_draft_without_llm_uses_document_bands(xdb):
    async def go(conn):
        await add_news(conn)
        y = await conn.fetchrow("SELECT * FROM yangiliklar WHERE lex_id = $1", DOC_ID)
        return await xabarlar.build_news_draft(conn, y, None)

    d = run(with_conn(xdb, go))
    assert d.usul == "matndan" and d.kalit == f"yangilik:{DOC_ID}" and d.havola == NEWS["url"]
    assert d.matn.startswith("📰 <b>Prezident farmoni</b> · №PF-1\n\n<b>Soliq hisobotini soddalashtirish to'g'risida</b>")
    assert "📌 <b>Asosiy o'zgarishlar:</b>" in d.matn
    assert "1️⃣ Hisobot shakllari qisqartirilsin." in d.matn  # band raqami takrorlanmaydi
    assert "2️⃣ Aksiz to'lovchilar hisobotni har oy topshiradi." in d.matn
    assert "👥 <b>Kimga tegishli:</b> soliq, qurilish" in d.matn
    assert "📅 qabul qilingan 25.09.2026 · kuchga kiradi 01.10.2026" in d.matn
    assert d.matn.endswith("#soliq #qurilish")


class DigestLLM:
    def __init__(self, fn):
        self.fn = fn

    def news_digest(self, title, meta, elements, usage):
        return self.fn(elements)


def test_news_draft_with_llm_keeps_only_verified_points(xdb):
    def digest(elements):
        real = elements[2][0]
        return NewsDigest(sarlavha="Aksiz hisobotlari har oy", mohiyat="Farmon hisobotni soddalashtiradi.",
                          bandlar=[DigestPoint(matn="Aksiz hisoboti har oy", source_id=real),
                                   DigestPoint(matn="Uydirma band", source_id="EL-999999")],
                          kimga=["aksiz to'lovchilar"], amaliy="Hisobotni har oy topshiring.")

    async def go(conn):
        await add_news(conn)
        y = await conn.fetchrow("SELECT * FROM yangiliklar WHERE lex_id = $1", DOC_ID)
        return await xabarlar.build_news_draft(conn, y, DigestLLM(digest))

    d = run(with_conn(xdb, go))
    assert d.usul == "llm"
    assert d.matn.startswith("📰 <b>Prezident farmoni</b> · №PF-1\n\n<b>Aksiz hisobotlari har oy</b>\n"
                             "<i>Soliq hisobotini soddalashtirish to'g'risida</i>\n\n💡 Farmon hisobotni soddalashtiradi.")
    assert "1️⃣ Aksiz hisoboti har oy" in d.matn and "Uydirma" not in d.matn
    assert f'<a href="https://lex.uz/docs/{DOC_ID}#' in d.matn and "↗</a>" in d.matn  # manba — bazadagi havola
    assert "👥 <b>Kimga tegishli:</b> aksiz to'lovchilar" in d.matn
    assert "✅ <b>Nima qilish kerak:</b> Hisobotni har oy topshiring." in d.matn


def test_news_draft_llm_failure_or_no_valid_points_falls_back(xdb):
    def bad(elements):
        return NewsDigest(sarlavha="x", mohiyat="y", bandlar=[DigestPoint(matn="z", source_id="EL-1")], kimga=[],
                          amaliy="")

    def fail(elements):
        raise LLMError("kredit yo'q")

    async def go(conn):
        await add_news(conn)
        y = await conn.fetchrow("SELECT * FROM yangiliklar WHERE lex_id = $1", DOC_ID)
        return [await xabarlar.build_news_draft(conn, y, DigestLLM(f)) for f in (bad, fail)]

    assert [d.usul for d in run(with_conn(xdb, go))] == ["matndan", "matndan"]


def test_require_ai_waits_instead_of_plain_text(xdb):
    def fail(elements):
        raise LLMError("kredit yo'q")

    async def go(pool):
        async with pool.acquire() as conn:
            await add_news(conn)
        waiting = await xabarlar.prepare_news(pool, DigestLLM(fail), settings(news_require_ai=True))
        no_llm = await xabarlar.prepare_news(pool, None, settings(news_require_ai=True))
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT count(*) FROM xabarlar")
        later = await xabarlar.prepare_news(pool, None, settings(news_require_ai=False))  # keyinroq — qayta urinadi
        return waiting, no_llm, n, later

    waiting, no_llm, n, later = with_pool(xdb, go)
    assert (waiting, no_llm, n) == ([], [], 0) and len(later) == 1


def test_prepare_news_is_idempotent_and_skips_old_and_irrelevant(xdb):
    async def go(pool):
        async with pool.acquire() as conn:
            await add_news(conn)
            await add_news(conn, lex_id="-9900010", url="https://lex.uz/docs/-9900010",
                           pub_date=datetime.now(timezone.utc) - timedelta(days=10))
            await add_news(conn, lex_id="-9900011", url="https://lex.uz/docs/-9900011", relevant=False)
        first = await xabarlar.prepare_news(pool, None, settings())
        second = await xabarlar.prepare_news(pool, None, settings())
        async with pool.acquire() as conn:
            return first, second, await conn.fetch("SELECT kalit, holat FROM xabarlar")

    first, second, rows = with_pool(xdb, go)
    assert len(first) == 1 and second == []
    assert [(r["kalit"], r["holat"]) for r in rows] == [(f"yangilik:{DOC_ID}", "kutilmoqda")]


def test_prepare_changes_groups_by_article(xdb):
    changed = code_like()
    changed.elements[2].text = "Aksiz stavkalari Vazirlar Mahkamasi tomonidan belgilanadi."
    changed.elements.append(element(ARTICLE_DOC_ID, 4, "article", "2-modda. Yangi modda", modda="2-modda",
                                    modda_raqami="2"))
    changed.elements.append(element(ARTICLE_DOC_ID, 5, "text", "Yangi modda matni.", modda="2-modda",
                                    modda_raqami="2"))

    async def go(pool):
        async with pool.acquire() as conn:
            await import_document(conn, code_like(), None, TODAY)
            await import_document(conn, changed, None, TODAY)  # o'zgarishlar jurnalga yoziladi
        ids = await xabarlar.prepare_changes(pool)
        again = await xabarlar.prepare_changes(pool)
        async with pool.acquire() as conn:
            x = await conn.fetchrow("SELECT * FROM xabarlar WHERE id = $1", ids[0])
            left = await conn.fetchval("SELECT count(*) FROM ozgarishlar WHERE xabar_id IS NULL")
        return ids, again, x, left

    ids, again, x, left = with_pool(xdb, go)
    assert len(ids) == 1 and again == [] and left == 0
    assert x["turi"] == "ozgarish" and x["holat"] == "kutilmoqda"
    assert x["matn"].startswith("⚠️ <b>Sinov qonuni — o'zgartirishlar</b>")
    assert ">1-modda. Aksiz</a> — o'zgartirildi" in x["matn"]
    assert ">2-modda. Yangi modda</a> — qo'shildi" in x["matn"]
    assert json.loads(x["tugmalar"]) == [["📖 1-modda", f"v:m:{ARTICLE_DOC_ID}:1"],
                                         ["📖 2-modda", f"v:m:{ARTICLE_DOC_ID}:2"]]


# --- admin tasdig'i va yuborish ------------------------------------------------------------


def prepared(xdb):
    async def go(pool):
        async with pool.acquire() as conn:
            await add_news(conn)
        return (await xabarlar.prepare_news(pool, None, settings()))[0]

    return with_pool(xdb, go)


def test_admin_gets_preview_with_decision_buttons(xdb):
    xid = prepared(xdb)
    bot = FakeBot()

    async def go(pool):
        shown = await xabarlar.notify_admins(bot, pool, settings())
        again = await xabarlar.notify_admins(bot, pool, settings())
        async with pool.acquire() as conn:
            return shown, again, await conn.fetchval("SELECT admin_xabarlar FROM xabarlar WHERE id = $1", xid)

    shown, again, previews = with_pool(xdb, go)
    assert (shown, again) == (1, 0)  # bir marta ko'rsatiladi
    chat_id, text, markup = bot.sent[0]
    assert chat_id == ADMIN and text.startswith("🆕 <b>Tasdiq kutilmoqda</b> · yangilik · AI'siz · 1 ta adminga")
    assert buttons(markup) == ["📄 Lex.uz'da ochish", "✅ Yuborish", "❌ Bekor qilish"]
    assert json.loads(previews) == [[ADMIN, 1]]
    assert not [s for s in bot.sent if s[0] != ADMIN]  # tasdiqsiz hech kimga ketmadi


def approve_and_send(xdb, cfg):
    xid = prepared(xdb)
    bot = FakeBot()

    async def go(pool):
        await xabarlar.notify_admins(bot, pool, cfg)
        result = await xabarlar.decide(bot, pool, cfg, xid, ADMIN, approve=True)
        await asyncio.gather(*xabarlar._background)
        again = await xabarlar.send_approved(bot, pool, cfg)
        async with pool.acquire() as conn:
            x = await conn.fetchrow("SELECT holat, hal_qilgan FROM xabarlar WHERE id = $1", xid)
            log = {r["telegram_id"]: r["natija"] for r in await conn.fetch(
                "SELECT telegram_id, natija FROM xabar_yuborishlar WHERE xabar_id = $1", xid)}
            blocked = await conn.fetchval("SELECT bloklagan FROM foydalanuvchilar WHERE telegram_id = $1", BLOCKED)
        return result, again, x, log, blocked

    return bot, *with_pool(xdb, go)


def test_approve_sends_only_to_admins_by_default(xdb):
    bot, result, again, x, log, blocked = approve_and_send(xdb, settings())
    assert result == "Tasdiqlandi, yuborilmoqda" and again == 0
    assert (x["holat"], x["hal_qilgan"]) == ("yuborildi", ADMIN)
    assert log == {ADMIN: "ok"}  # obunachilarga emas (NEWS_AUDIENCE=admins)
    assert [s[0] for s in bot.sent] == [ADMIN, ADMIN]  # ko'rinish + tasdiqlangan xabar
    assert buttons(bot.sent[1][2]) == ["📄 Lex.uz'da ochish"]
    assert buttons(bot.edits[-1][2])[-1] == "✅ Yuborildi: 1 ta adminga"


def test_approve_with_audience_all_sends_to_everyone_once(xdb):
    bot, result, again, x, log, blocked = approve_and_send(xdb, settings(news_audience="all"))
    assert log == {ADMIN: "ok", 2001: "ok", 2002: "ok", BLOCKED: "bloklangan"}
    assert sorted(s[0] for s in bot.sent[1:]) == [ADMIN, 2001, 2002]
    assert blocked is True
    assert buttons(bot.edits[-1][2])[-1] == "✅ Yuborildi: 3 ta foydalanuvchiga"


def test_approve_at_night_waits_for_daytime(xdb):
    xid = prepared(xdb)
    bot = FakeBot()

    async def go(pool):
        await xabarlar.notify_admins(bot, pool, settings(day=False))
        result = await xabarlar.decide(bot, pool, settings(day=False), xid, ADMIN, approve=True)
        night = await xabarlar.send_approved(bot, pool, settings(day=False))
        day = await xabarlar.send_approved(bot, pool, settings())
        return result, night, day

    result, night, day = with_pool(xdb, go)
    assert result.startswith("Tasdiqlandi,") and result.endswith("da yuboriladi")
    assert (night, day) == (0, 1)


def test_cancel_and_second_decision(xdb):
    xid = prepared(xdb)
    bot = FakeBot()

    async def go(pool):
        await xabarlar.notify_admins(bot, pool, settings())
        first = await xabarlar.decide(bot, pool, settings(), xid, ADMIN, approve=False)
        second = await xabarlar.decide(bot, pool, settings(), xid, ADMIN, approve=True)
        sent = await xabarlar.send_approved(bot, pool, settings())
        return first, second, sent

    first, second, sent = with_pool(xdb, go)
    assert first == "Bekor qilindi" and second == "Bu xabar allaqachon hal qilingan (bekor)" and sent == 0
    assert buttons(bot.edits[-1][2])[-1] == "❌ Bekor qilindi"


def test_blocked_user_is_unblocked_when_writing_again(xdb):
    from app.services.users import ensure_user

    async def go(conn):
        await conn.execute("UPDATE foydalanuvchilar SET bloklagan = true WHERE telegram_id = $1", BLOCKED)
        await ensure_user(conn, BLOCKED)
        return await conn.fetchval("SELECT bloklagan FROM foydalanuvchilar WHERE telegram_id = $1", BLOCKED)

    assert run(with_conn(xdb, go)) is False


def test_channel_post_only_by_admin_button_after_approval(xdb):
    xid = prepared(xdb)
    bot = FakeBot()
    cfg = settings(news_channel="@soliq_kanal")

    async def go(pool):
        await xabarlar.notify_admins(bot, pool, cfg)
        early = await xabarlar.post_to_channel(bot, pool, cfg, xid)  # tasdiqsiz — yo'q
        await xabarlar.decide(bot, pool, cfg, xid, ADMIN, approve=True)
        await asyncio.gather(*xabarlar._background)
        auto = [s for s in bot.sent if s[0] == "@soliq_kanal"]  # tasdiqlash kanalga avtomatik joylamaydi
        first = await xabarlar.post_to_channel(bot, pool, cfg, xid)
        second = await xabarlar.post_to_channel(bot, pool, cfg, xid)
        async with pool.acquire() as conn:
            kanal_id = await conn.fetchval("SELECT kanal_xabar_id FROM xabarlar WHERE id = $1", xid)
        return early, auto, first, second, kanal_id

    early, auto, first, second, kanal_id = with_pool(xdb, go)
    assert early == "Avval xabarni tasdiqlang" and auto == []
    assert (first, second) == ("Kanalga joylandi", "Allaqachon kanalga joylangan") and kanal_id is not None
    status = buttons(bot.edits[0][2])
    assert "📢 Kanalga joylash" in status  # tasdiqlangan ko'rinishda kanal tugmasi bor
    posts = [s for s in bot.sent if s[0] == "@soliq_kanal"]
    assert len(posts) == 1
    assert [b.url for row in posts[0][2].inline_keyboard for b in row] == [NEWS["url"], "https://t.me/soliqexpertibot"]


def test_channel_button_hidden_without_channel(xdb):
    xid = prepared(xdb)
    bot = FakeBot()

    async def go(pool):
        await xabarlar.notify_admins(bot, pool, settings())
        await xabarlar.decide(bot, pool, settings(day=False), xid, ADMIN, approve=True)

    with_pool(xdb, go)
    assert "📢 Kanalga joylash" not in buttons(bot.edits[-1][2])


def test_admin_can_reshow_pending_preview(xdb):
    xid = prepared(xdb)
    bot = FakeBot()

    async def go(pool):
        await xabarlar.notify_admins(bot, pool, settings())
        shown = await xabarlar.show_preview(bot, pool, settings(), xid, ADMIN)
        await xabarlar.decide(bot, pool, settings(day=False), xid, ADMIN, approve=False)
        again = await xabarlar.show_preview(bot, pool, settings(), xid, ADMIN)
        return shown, again

    shown, again = with_pool(xdb, go)
    assert (shown, again) == (True, False)
    assert len([e for e in bot.edits if buttons(e[2])[-1] == "❌ Bekor qilindi"]) == 2  # ikkala ko'rinish yangilandi
