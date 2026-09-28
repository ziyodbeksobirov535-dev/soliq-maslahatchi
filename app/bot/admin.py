"""/admin paneli (faqat ADMIN_TELEGRAM_IDS): sifat va xabarlar nazorati.

- 👎 Salbiy baholar — foydalanuvchi "Foydasiz" degan javoblar (savol, natija turi, sana);
- ❓ Javobsiz savollar — topilmadi / aniqlashtirish / ma'lumot yetarli emas: bazani to'ldirish uchun;
- 📰 Xabarlar — holatlar soni va tasdiq kutayotganlar; har birini qayta ko'rish (tasdiq tugmalari bilan);
- 📊 Statistika — /stat bilan bir xil.
Callback: `a:<bo'lim>`, `a:show:<xabar_id>`.
"""

from __future__ import annotations

from datetime import datetime

import asyncpg
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.formatting import esc

LIST_LIMIT = 10
UNANSWERED_STATUSES = ("not_found", "needs_clarification", "insufficient")
HOLAT_UZ = {"kutilmoqda": "tasdiq kutmoqda", "tasdiqlandi": "tasdiqlangan", "bekor": "bekor qilingan",
            "yuborildi": "yuborilgan"}


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👎 Salbiy baholar", callback_data="a:neg"),
         InlineKeyboardButton(text="❓ Javobsiz savollar", callback_data="a:miss")],
        [InlineKeyboardButton(text="📰 Xabarlar", callback_data="a:news"),
         InlineKeyboardButton(text="📊 Statistika", callback_data="a:stat")],
    ])


def _short(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _when(ts: datetime, tz) -> str:
    return ts.astimezone(tz).strftime("%d.%m %H:%M")


async def negative_ratings(conn: asyncpg.Connection, tz) -> str:
    rows = await conn.fetch(
        "SELECT question, status, created_at FROM suhbatlar WHERE rating = -1 ORDER BY created_at DESC LIMIT $1",
        LIST_LIMIT)
    total = await conn.fetchval("SELECT count(*) FROM suhbatlar WHERE rating = -1")
    if not rows:
        return "👎 Salbiy baholangan javob yo'q."
    lines = [f"<b>👎 Salbiy baholar</b> (jami {total}, oxirgi {len(rows)}):", ""]
    lines += [f"• {_when(r['created_at'], tz)} · {esc(r['status'] or '—')}\n  {esc(_short(r['question']))}" for r in rows]
    return "\n".join(lines)


async def unanswered(conn: asyncpg.Connection, tz) -> str:
    rows = await conn.fetch(
        "SELECT question, status, created_at FROM suhbatlar WHERE status = ANY($1::text[]) "
        "ORDER BY created_at DESC LIMIT $2", list(UNANSWERED_STATUSES), LIST_LIMIT)
    if not rows:
        return "❓ Javobsiz savol yo'q."
    lines = ["<b>❓ Javobsiz savollar</b> (bazaga hujjat qo'shish yoki qidiruvni yaxshilash uchun):", ""]
    lines += [f"• {_when(r['created_at'], tz)} · {esc(r['status'])}\n  {esc(_short(r['question']))}" for r in rows]
    return "\n".join(lines)


async def news_overview(conn: asyncpg.Connection) -> tuple[str, InlineKeyboardMarkup | None]:
    counts = {r["holat"]: r["n"] for r in await conn.fetch("SELECT holat, count(*) AS n FROM xabarlar GROUP BY holat")}
    pending = await conn.fetch(
        "SELECT id, turi, lex_id, created_at FROM xabarlar WHERE holat = 'kutilmoqda' ORDER BY id LIMIT $1",
        LIST_LIMIT)
    lines = ["<b>📰 Xabarlar</b>", ""]
    lines += [f"• {HOLAT_UZ[h]}: {counts.get(h, 0)}" for h in HOLAT_UZ]
    if not pending:
        return "\n".join(lines), None
    lines += ["", "Tasdiq kutayotganlarni qayta ko'rish:"]
    rows = [[InlineKeyboardButton(text=f"#{p['id']} · {'yangilik' if p['turi'] == 'yangilik' else 'o‘zgarish'}",
                                  callback_data=f"a:show:{p['id']}")] for p in pending]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
