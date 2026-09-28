"""Soliq kalendari: hisobot/to'lov muddatlari va eslatmalar (/kalendar).

Muddatlar xotiradan emas — har biri Soliq kodeksidagi aniq jumla bilan bog'langan (`quote`, `period_quote`);
tests/test_kalendar.py ularni real Lex.uz matnida tekshiradi. Profil soliq rejimiga qarab tegishlilari
ko'rsatiladi (rejim bo'sh — hammasi). Eslatma (rozilik bilan): muddatdan 3 kun oldin va muddat kuni, kunduzi.
Dam olish kuniga to'g'ri kelsa ko'chirish qoidasi hisobga olinmagan — xabarda moddaga havola beriladi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import asyncpg
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

log = logging.getLogger(__name__)

SK = "-4674902"
REMIND_DAYS_BEFORE = (3, 0)
MONTHS_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr",
             "dekabr"]


@dataclass(frozen=True)
class Deadline:
    kalit: str
    nomi: str
    day: int
    months: tuple[int, ...]  # qaysi oylarda (oylik — 1..12; choraklik — 1, 4, 7, 10)
    modda: str
    quote: str  # muddat jumlasi (modda matnida)
    period_modda: str
    period_quote: str  # hisobot davri jumlasi
    rejimlar: tuple[str, ...]  # profil rejimi shu so'zlardan birini o'z ichiga olsa — tegishli; bo'sh — hammaga


ALL_MONTHS = tuple(range(1, 13))
DEADLINES: tuple[Deadline, ...] = (
    Deadline("aylanma", "Aylanma solig'i — hisobot va to'lov", 15, ALL_MONTHS, "470",
             "hisobot davridan keyingi oyning oʻn beshinchi kunidan kechiktirmay", "469", "Bir oy hisobot davridir.",
             ("aylanma",)),
    Deadline("jshds", "JSHDS (soliq agenti, ish haqidan) — hisobot", 15, ALL_MONTHS, "389",
             "har oyda, hisobot davridan keyingi oyning oʻn beshinchi kunidan kechiktirmay", "389",
             "har oyda, hisobot davridan keyingi oyning oʻn beshinchi kunidan kechiktirmay", ()),
    Deadline("ijtimoiy", "Ijtimoiy soliq — hisobot va to'lov", 15, ALL_MONTHS, "407",
             "har oyda hisobot davridan keyingi oyning oʻn beshinchi kunidan kechiktirmay", "406",
             "Yil oyi hisobot davridir.", ()),
    Deadline("qqs", "QQS — hisobot", 20, ALL_MONTHS, "273", "keyingi oyning yigirmanchi kunidan", "259",
             "bir oy soliq davridir", ("umumbelgilangan", "qqs")),
    Deadline("foyda", "Foyda solig'i — choraklik hisobot", 20, (4, 7, 10), "339",
             "hisobot davridan keyingi oyning yigirmanchi kunidan kechiktirmay", "338", "Yilning choragi hisobot davridir.",
             ("umumbelgilangan", "foyda")),
)


def applies(d: Deadline, rejim: str | None) -> bool:
    if not d.rejimlar or not rejim:
        return True
    low = rejim.lower()
    return any(r in low for r in d.rejimlar)


def next_date(d: Deadline, today: date) -> date:
    year, month = today.year, today.month
    for _ in range(13):
        if month in d.months and date(year, month, d.day) >= today:
            return date(year, month, d.day)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    raise AssertionError("muddat topilmadi")  # months bo'sh bo'lmasa bu yerga yetmaydi


def upcoming(today: date, rejim: str | None) -> list[tuple[Deadline, date]]:
    items = [(d, next_date(d, today)) for d in DEADLINES if applies(d, rejim)]
    return sorted(items, key=lambda x: (x[1], x[0].kalit))


def fmt_date(d: date) -> str:
    return f"{d.day}-{MONTHS_UZ[d.month - 1]}"


def due_reminders(today: date, rejim: str | None) -> list[tuple[Deadline, date, int]]:
    """Bugun eslatiladiganlar: (muddat, sana, qolgan kun) — 3 kun qolganda va muddat kuni."""
    out = []
    for d in DEADLINES:
        if not applies(d, rejim):
            continue
        due = next_date(d, today)
        left = (due - today).days
        if left in REMIND_DAYS_BEFORE:
            out.append((d, due, left))
    return out


async def set_reminders(conn: asyncpg.Connection, telegram_id: int, on: bool) -> None:
    await conn.execute("UPDATE foydalanuvchilar SET eslatma = $2 WHERE telegram_id = $1", telegram_id, on)


async def reminder_targets(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT telegram_id, profile->>'rejim' AS rejim FROM foydalanuvchilar "
        "WHERE eslatma AND active AND NOT bloklagan ORDER BY id")


async def mark_sent(conn: asyncpg.Connection, telegram_id: int, kalit: str, due: date, left: int) -> bool:
    """Bir eslatma (foydalanuvchi, muddat, sana, kun) — bir marta. Yangi bo'lsa True."""
    row = await conn.fetchval(
        "INSERT INTO eslatmalar_yuborilgan (telegram_id, kalit, muddat, qolgan_kun) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT DO NOTHING RETURNING 1", telegram_id, kalit, due, left)
    return row is not None


async def send_reminders(bot: Bot, pool: asyncpg.Pool, today: date, links: dict[str, str]) -> int:
    """Kunlik: rozilik bergan foydalanuvchilarga bugungi eslatmalar (har biri bir marta). Natija — yuborilganlar."""
    sent = 0
    async with pool.acquire() as conn:
        targets = await reminder_targets(conn)
    for t in targets:
        for d, due, left in due_reminders(today, t["rejim"]):
            async with pool.acquire() as conn:
                if not await mark_sent(conn, t["telegram_id"], d.kalit, due, left):
                    continue
            when = "Bugun oxirgi kun" if left == 0 else f"{left} kundan keyin"
            text = (f"⏰ <b>Eslatma: {when} ({fmt_date(due)})</b>\n{d.nomi}\n\n"
                    f"Muddat Soliq kodeksining {d.modda}-moddasi bo'yicha. Dam olish kuniga to'g'ri kelsa — "
                    f"moddani va soliq organining xabarini tekshiring.")
            markup = None
            if d.modda in links:
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=f"📖 {d.modda}-modda", url=links[d.modda])]])
            try:
                await bot.send_message(t["telegram_id"], text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                       link_preview_options=LinkPreviewOptions(is_disabled=True))
                sent += 1
            except TelegramForbiddenError:
                async with pool.acquire() as conn:
                    await conn.execute("UPDATE foydalanuvchilar SET bloklagan = true WHERE telegram_id = $1",
                                       t["telegram_id"])
                break
            except TelegramAPIError as exc:
                log.warning("reminder failed chat=%s error=%s", t["telegram_id"], type(exc).__name__)
    return sent


async def article_links(conn: asyncpg.Connection) -> dict[str, str]:
    """Kalendar moddalarining bazadagi havolalari (sarlavha elementi)."""
    moddalar = sorted({d.modda for d in DEADLINES})
    rows = await conn.fetch(
        "SELECT DISTINCT ON (e.modda_raqami) e.modda_raqami, e.link FROM elementlar e JOIN hujjatlar h "
        "ON h.id = e.document_id WHERE h.lex_id = $1 AND e.kind = 'article' AND e.modda_raqami = ANY($2::text[]) "
        "ORDER BY e.modda_raqami, e.order_no", SK, moddalar)
    return {r["modda_raqami"]: r["link"] for r in rows}
