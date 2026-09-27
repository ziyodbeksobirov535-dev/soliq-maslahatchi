"""PHASE 5: Telegram bot testlari — haqiqiy aiogram Dispatcher, soxta Telegram sessiyasi.

Har bir update `dp.feed_update()` orqali o'tadi (filtrlar, bog'liqliklar, xato ishlovchi — hammasi haqiqiy);
bot Telegram'ga yuboradigan so'rovlar `MockedSession` da yig'iladi.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity, Update, User

from app.ai.schemas import AnswerOutput, Citation
from app.bot.app import build_dispatcher
from app.bot.formatting import md_to_html, split_message
from app.bot.handlers import parse_modda_args
from app.collector.importer import import_document
from app.config import Settings
from app.database.connection import connect, create_pool
from tests.conftest import run
from tests.test_answer import FakeLLM, cite_first_text
from tests.test_lexuz_parser import SK_ID, card, soliq_kodeksi

TODAY = datetime.now(timezone.utc).date()
ADMIN = 1000
USER = 2000
TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ"


class MockedSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=len(self.requests), date=datetime.now(timezone.utc),
                           chat=Chat(id=method.chat_id, type="private"), text=method.text)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    @property
    def sent(self) -> list[SendMessage]:
        return [r for r in self.requests if isinstance(r, SendMessage)]


def update(user_id: int, text: str, n: int = 1) -> Update:
    entities = None
    if text.startswith("/"):
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
    return Update(
        update_id=n,
        message=Message(
            message_id=n, date=datetime.now(timezone.utc), chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Test"), text=text, entities=entities,
        ),
    )


def settings(**kw) -> Settings:
    return Settings(_env_file=None, admin_telegram_ids=frozenset({ADMIN}), **kw)


@pytest.fixture(scope="module")
def bot_db(db):
    async def setup():
        conn = await connect(db)
        try:
            await conn.execute("DELETE FROM hujjatlar")
            await conn.execute("DELETE FROM foydalanuvchilar")
            await conn.execute("DELETE FROM suhbatlar")
            await import_document(conn, soliq_kodeksi(), card("card1-soliq-kodeksi.html", SK_ID), TODAY)
        finally:
            await conn.close()

    run(setup())
    return db


def feed(dsn, texts, *, user_id=USER, llm=None, cfg=None):
    """Update'larni ketma-ket beradi; (session, db-query-helper natijasi) qaytaradi."""
    session = MockedSession()

    async def go():
        pool = await create_pool(dsn, min_size=1, max_size=2)
        try:
            bot = Bot(TOKEN, session=session)
            dp = build_dispatcher(pool, cfg or settings(), llm)
            for i, t in enumerate(texts, 1):
                await dp.feed_update(bot, update(user_id, t, i))
        finally:
            await pool.close()

    run(go())
    return session


def query(dsn, sql, *args):
    async def go():
        conn = await connect(dsn)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return run(go())


# --- formatlash (DB'siz) ------------------------------------------------------------


def test_md_to_html_escapes_and_converts():
    out = md_to_html("**Muhim:** <script>x</script> *kursiv* `kod`\n- band")
    assert "<b>Muhim:</b>" in out and "&lt;script&gt;" in out
    assert "<i>kursiv</i>" in out and "<code>kod</code>" in out and "• band" in out


def test_split_message_respects_limit():
    text = "\n".join(f"satr {i} " + "x" * 50 for i in range(400))
    parts = split_message(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == text


@pytest.mark.parametrize("args,number,docs", [
    ("461", "461", ["-4674902"]), ("106 mehnat", "106", ["-6257288"]), ("mehnat 106", "106", ["-6257288"]),
    ("121¹", "121-1", ["-4674902"]), ("12 fuqarolik", "12", ["-111189", "-180552"]), ("abc", None, ["-4674902"]),
    (None, None, ["-4674902"]),
])
def test_parse_modda_args(args, number, docs):
    assert parse_modda_args(args) == (number, docs)


# --- buyruqlar ---------------------------------------------------------------------------


def test_start_registers_user(bot_db):
    s = feed(bot_db, ["/start"])
    assert "Assalomu alaykum" in s.sent[0].text
    assert s.sent[0].parse_mode == "HTML"
    assert query(bot_db, "SELECT count(*) AS n FROM foydalanuvchilar WHERE telegram_id = $1", USER)[0]["n"] == 1


def test_modda_461_without_llm(bot_db):
    s = feed(bot_db, ["/modda 461"])
    text = s.sent[0].text
    assert '<a href="https://lex.uz/docs/-4674902#-4688907">461-modda. Soliq toʻlovchilar</a>' in text
    assert "O‘zbekiston Respublikasining Soliq kodeksi" in text
    assert "Holati: amalda" in text
    assert "1) soliq davrida jami daromadi bir milliard" in text
    assert s.sent[0].link_preview_options.is_disabled


def test_modda_with_future_changes_warns(bot_db):
    text = feed(bot_db, ["/modda 19"]).sent[0].text
    assert "kelajakda kuchga kiradigan" in text


@pytest.mark.parametrize("cmd,expected", [
    ("/modda", "Modda raqamini yozing"), ("/modda abc", "Modda raqamini yozing"),
    ("/modda 9999", "bazada topilmadi"), ("/modda 106 mehnat", "bazada topilmadi"),  # test bazada faqat SK
])
def test_modda_errors(bot_db, cmd, expected):
    assert expected in feed(bot_db, [cmd]).sent[0].text


def test_profil_show_and_update(bot_db):
    s = feed(bot_db, ["/profil rejim aylanma soliq", "/profil", "/profil nomalum x"])
    assert "Soliq rejimi: aylanma soliq" in s.sent[0].text
    assert "Bugungi savollar: 0 / 20" in s.sent[1].text
    assert "Noma'lum maydon" in s.sent[2].text
    row = query(bot_db, "SELECT profile->>'rejim' AS r FROM foydalanuvchilar WHERE telegram_id = $1", USER)[0]
    assert row["r"] == "aylanma soliq"


def test_stat_admin_only(bot_db):
    assert "faqat adminlar" in feed(bot_db, ["/stat"], user_id=USER).sent[0].text
    text = feed(bot_db, ["/stat"], user_id=ADMIN).sent[0].text
    assert "Statistika" in text and "Soliq kodeksi" in text and "8137 element" in text


def test_unknown_command_and_news(bot_db):
    s = feed(bot_db, ["/nimadir", "/yangiliklar"])
    assert "Noma'lum buyruq" in s.sent[0].text
    assert "yangi hujjat topilmadi" in s.sent[1].text  # test bazasida yangilik yo'q


# --- oddiy savol -------------------------------------------------------------------------


def test_question_without_llm_is_polite_and_logged(bot_db):
    s = feed(bot_db, ["Soliq imtiyozlari shartlari qanday?"], user_id=3000, llm=None)
    assert "sozlanmagan" in s.sent[0].text and "/modda" in s.sent[0].text
    rows = query(bot_db, "SELECT status FROM suhbatlar WHERE telegram_id = 3000")
    assert [r["status"] for r in rows] == ["unavailable"]


def test_question_answered_with_sources_and_logged(bot_db):
    llm = FakeLLM(lambda msg, n: cite_first_text(msg))
    s = feed(bot_db, ["Soliq imtiyozidan foydalanish uchun qanday shartlar bor?"], user_id=4000, llm=llm)
    chat_actions = [r for r in s.requests if type(r).__name__ == "SendChatAction"]
    assert chat_actions  # "yozmoqda..." ko'rsatildi
    text = s.sent[0].text
    assert "<b>Huquqiy asos:</b>" in text
    assert '<a href="https://lex.uz/docs/-4674902#' in text
    row = query(bot_db, "SELECT * FROM suhbatlar WHERE telegram_id = 4000")[0]
    assert row["status"] == "answered"
    assert row["question"].startswith("Soliq imtiyozidan")
    assert row["retrieved_element_ids"]  # kontekstdagi elementlar (bazadagi id)
    assert "lex.uz/docs/-4674902#" in row["used_sources"]
    assert row["processing_ms"] is not None


def test_model_html_is_escaped(bot_db):
    def respond(msg, n):
        out = cite_first_text(msg)
        out.answer_markdown = "<b>qalin emas</b> <a href='http://evil'>x</a>"
        return out

    text = feed(bot_db, ["Soliq imtiyozlari shartlari?"], user_id=4100, llm=FakeLLM(respond)).sent[0].text
    assert "evil" not in text  # URL olib tashlandi
    assert "&lt;b&gt;qalin emas&lt;/b&gt;" in text


def test_daily_limit_and_admin_bypass(bot_db):
    llm = FakeLLM(lambda msg, n: cite_first_text(msg))
    cfg = settings(daily_question_limit=1)
    s = feed(bot_db, ["Soliq imtiyozlari shartlari?", "Soliq imtiyozlari shartlari?"], user_id=5000, llm=llm, cfg=cfg)
    assert "Huquqiy asos" in s.sent[0].text
    assert "limiti tugadi" in s.sent[-1].text
    statuses = [r["status"] for r in query(bot_db, "SELECT status FROM suhbatlar WHERE telegram_id = 5000 ORDER BY id")]
    assert statuses == ["answered", "limit_exceeded"]
    s = feed(bot_db, ["Soliq imtiyozlari shartlari?"] * 2, user_id=ADMIN, llm=llm, cfg=cfg)
    assert all("limiti tugadi" not in m.text for m in s.sent)


def test_clarification_question_does_not_call_llm(bot_db):
    def never(msg, n):
        raise AssertionError("LLM chaqirilmasligi kerak")

    s = feed(bot_db, ["Qaysi modda bu talabni belgilaydi?"], user_id=6000, llm=FakeLLM(never))
    assert "aniqlashtirib" in s.sent[0].text
    assert query(bot_db, "SELECT status FROM suhbatlar WHERE telegram_id = 6000")[0]["status"] == "needs_clarification"


def test_too_long_question_rejected(bot_db):
    s = feed(bot_db, ["soliq " * 300], user_id=7000, llm=FakeLLM(lambda m, n: None))
    assert "juda uzun" in s.sent[0].text


def test_unexpected_error_gives_friendly_reply(bot_db):
    def boom(msg, n):
        raise RuntimeError("kutilmagan")

    s = feed(bot_db, ["Soliq imtiyozlari shartlari?"], user_id=8000, llm=FakeLLM(boom))
    assert "texnik xatolik" in s.sent[-1].text
    assert "RuntimeError" not in s.sent[-1].text and "Traceback" not in s.sent[-1].text
