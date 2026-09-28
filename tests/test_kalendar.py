"""Soliq kalendari: muddatlar real Soliq kodeksi matnida, sana hisobi, eslatmalar (bir marta, rozilik bilan)."""

from datetime import date
from functools import lru_cache
from types import SimpleNamespace

import pytest

from app.database.connection import connect, create_pool
from app.services import kalendar as k
from tests.conftest import run
from tests.test_lexuz_parser import soliq_kodeksi


@lru_cache(maxsize=None)
def article_text(number: str) -> str:
    return "\n".join(e.text for e in soliq_kodeksi().article(number))


@pytest.mark.parametrize("d", k.DEADLINES, ids=lambda d: d.kalit)
def test_deadline_quotes_exist_in_real_tax_code(d):
    assert d.quote in article_text(d.modda)
    assert d.period_quote in article_text(d.period_modda)


def test_quote_day_matches_deadline_day():
    words = {15: "oʻn beshinchi", 20: "yigirmanchi"}
    for d in k.DEADLINES:
        assert words[d.day] in d.quote, d.kalit


def by_key(items):
    return {d.kalit: due for d, due in items}


def test_next_dates_monthly_and_quarterly():
    today = date(2026, 9, 28)
    up = by_key(k.upcoming(today, None))
    assert up == {"aylanma": date(2026, 10, 15), "jshds": date(2026, 10, 15), "ijtimoiy": date(2026, 10, 15),
                  "qqs": date(2026, 10, 20), "foyda": date(2026, 10, 20)}
    assert by_key(k.upcoming(date(2026, 10, 15), None))["aylanma"] == date(2026, 10, 15)  # muddat kuni ham
    assert by_key(k.upcoming(date(2026, 10, 21), None))["foyda"] == date(2027, 4, 20)
    assert by_key(k.upcoming(date(2026, 12, 16), None))["aylanma"] == date(2027, 1, 15)


def test_profile_regime_filters_deadlines():
    assert set(by_key(k.upcoming(date(2026, 9, 28), "Aylanma solig'i"))) == {"aylanma", "jshds", "ijtimoiy"}
    assert set(by_key(k.upcoming(date(2026, 9, 28), "Umumbelgilangan (QQS, foyda solig'i)"))) == \
        {"jshds", "ijtimoiy", "qqs", "foyda"}


def test_due_reminders_three_days_before_and_on_day():
    assert {d.kalit for d, _, left in k.due_reminders(date(2026, 10, 12), "Aylanma solig'i")} == \
        {"aylanma", "jshds", "ijtimoiy"}
    assert [left for _, _, left in k.due_reminders(date(2026, 10, 15), "Aylanma solig'i")] == [0, 0, 0]
    assert k.due_reminders(date(2026, 10, 13), None) == []
    assert k.fmt_date(date(2026, 10, 15)) == "15-oktabr"


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=len(self.sent))


def test_reminders_sent_once_to_opted_in_users(db):
    async def go():
        pool = await create_pool(db, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM foydalanuvchilar WHERE telegram_id BETWEEN 8000 AND 8099")
                await conn.execute("DELETE FROM eslatmalar_yuborilgan")
                await conn.execute("UPDATE foydalanuvchilar SET eslatma = false")  # boshqa testlardagilar
                await conn.executemany(
                    "INSERT INTO foydalanuvchilar (telegram_id, profile, eslatma) VALUES ($1, $2::jsonb, $3)",
                    [(8001, '{"rejim": "Aylanma solig\'i"}', True), (8002, "{}", False)])
            bot = FakeBot()
            links = {"470": "https://lex.uz/docs/-4674902#-1"}
            first = await k.send_reminders(bot, pool, date(2026, 10, 12), links)
            second = await k.send_reminders(bot, pool, date(2026, 10, 12), links)
            return bot, first, second
        finally:
            await pool.close()

    bot, first, second = run(go())
    assert (first, second) == (3, 0)
    assert {chat for chat, _, _ in bot.sent} == {8001}
    aylanma = next(t for _, t, _ in bot.sent if "Aylanma" in t)
    assert "3 kundan keyin (15-oktabr)" in aylanma
    markup = next(m for _, t, m in bot.sent if "Aylanma" in t)
    assert markup.inline_keyboard[0][0].url == "https://lex.uz/docs/-4674902#-1"
