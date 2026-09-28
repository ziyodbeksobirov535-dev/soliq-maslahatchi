"""PHASE 5: Telegram bot testlari — haqiqiy aiogram Dispatcher, soxta Telegram sessiyasi.

Har bir update `dp.feed_update()` orqali o'tadi (filtrlar, bog'liqliklar, xato ishlovchi — hammasi haqiqiy);
bot Telegram'ga yuboradigan so'rovlar `MockedSession` da yig'iladi.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetChatMember, SendMessage
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    Message,
    MessageEntity,
    Update,
    User,
)

from app.ai.schemas import AnswerOutput, Citation
from app.bot.app import build_dispatcher
from app.bot.formatting import md_to_html, split_message
from app.bot.handlers import modda_only, parse_modda_args
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
    def __init__(self, members: set[int] | None = None) -> None:
        super().__init__()
        self.requests: list = []
        self.members = members or set()  # majburiy kanal a'zolari

    async def close(self) -> None:
        pass

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, GetChatMember):
            user = User(id=method.user_id, is_bot=False, first_name="Test")
            return ChatMemberMember(user=user) if method.user_id in self.members else ChatMemberLeft(user=user)
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


def callback(user_id: int, data: str, n: int = 100) -> Update:
    msg = Message(message_id=n, date=datetime.now(timezone.utc), chat=Chat(id=user_id, type="private"),
                  from_user=User(id=1, is_bot=True, first_name="Bot"), text="javob")
    return Update(update_id=n, callback_query=CallbackQuery(
        id=str(n), from_user=User(id=user_id, is_bot=False, first_name="Test"), chat_instance="c", data=data,
        message=msg))


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


def feed(dsn, texts, *, user_id=USER, llm=None, cfg=None, members=None):
    """Update'larni ketma-ket beradi; (session, db-query-helper natijasi) qaytaradi."""
    session = MockedSession(members)

    async def go():
        pool = await create_pool(dsn, min_size=1, max_size=2)
        try:
            bot = Bot(TOKEN, session=session)
            dp = build_dispatcher(pool, cfg or settings(), llm)
            for i, t in enumerate(texts, 1):
                await dp.feed_update(bot, t if isinstance(t, Update) else update(user_id, t, i))
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
    ("/modda", "Qaysi modda?"), ("/modda abc", "Qaysi modda?"),
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


def test_question_without_llm_shows_sources_and_logged(bot_db):
    s = feed(bot_db, ["Soliq imtiyozlari shartlari qanday?"], user_id=3000, llm=None)
    msg = s.sent[0]
    assert msg.text.startswith("Hozir to'liq javob tayyorlay olmadim")
    assert "📌 <b>" in msg.text and '<a href="https://lex.uz/docs/-4674902#' in msg.text
    buttons = [b for row in msg.reply_markup.inline_keyboard for b in row]
    assert any(b.callback_data.startswith("v:m:-4674902:") for b in buttons)
    assert {b.text for b in buttons} >= {"👍 Foydali", "👎 Foydasiz"}
    rows = query(bot_db, "SELECT status FROM suhbatlar WHERE telegram_id = 3000")
    assert [r["status"] for r in rows] == ["sources_only"]


def test_modda_asks_number_then_shows_article(bot_db):
    s = feed(bot_db, ["/modda", "461"], user_id=3100)
    assert "Qaysi modda?" in s.sent[0].text
    assert "461-modda. Soliq toʻlovchilar" in s.sent[1].text


def test_modda_prompt_then_question_goes_to_question(bot_db):
    s = feed(bot_db, ["/modda", "Soliq imtiyozlari shartlari qanday?"], user_id=3150, llm=None)
    assert s.sent[1].text.startswith("Hozir to'liq javob tayyorlay olmadim")


@pytest.mark.parametrize("text", ["461", "461-modda", "modda 461", "461 moddasi"])
def test_plain_article_number_shows_article(bot_db, text):
    assert "461-modda. Soliq toʻlovchilar" in feed(bot_db, [text], user_id=3200).sent[0].text


def test_modda_only_parser():
    assert modda_only("461") == "461"
    assert modda_only("106 mehnat") == "106 mehnat"
    assert modda_only("121-1-modda") == "121-1"
    assert modda_only("QQS stavkasi qancha") is None
    assert modda_only("461 va 462") is None


def test_view_source_button(bot_db):
    s = feed(bot_db, [callback(3300, "v:m:-4674902:461")], user_id=3300)
    assert "461-modda. Soliq toʻlovchilar" in s.sent[0].text
    s = feed(bot_db, [callback(3300, "v:m:-4674902:9999")], user_id=3300)
    assert not s.sent  # topilmasa — faqat ogohlantirish (answerCallbackQuery)


def test_rating_saved_only_for_own_answer(bot_db):
    s = feed(bot_db, ["Soliq imtiyozlari shartlari qanday?"], user_id=3400, llm=None)
    rid = query(bot_db, "SELECT request_id FROM suhbatlar WHERE telegram_id = 3400")[0]["request_id"]
    feed(bot_db, [callback(3999, f"r:{rid}:-1")], user_id=3999)  # boshqa foydalanuvchi
    assert query(bot_db, "SELECT rating FROM suhbatlar WHERE telegram_id = 3400")[0]["rating"] is None
    s = feed(bot_db, [callback(3400, f"r:{rid}:1")], user_id=3400)
    assert query(bot_db, "SELECT rating FROM suhbatlar WHERE telegram_id = 3400")[0]["rating"] == 1
    assert [type(r).__name__ for r in s.requests] == ["AnswerCallbackQuery", "EditMessageReplyMarkup"]


def test_profile_buttons(bot_db):
    s = feed(bot_db, ["/profil", callback(3500, "p:rejim"), callback(3500, "p:rejim:0", 101)], user_id=3500)
    assert s.sent[0].reply_markup.inline_keyboard[0][0].callback_data == "p:soha"
    edits = [r for r in s.requests if type(r).__name__ == "EditMessageText"]
    assert "Soliq rejimi" in edits[0].text
    assert "Soliq rejimi: Aylanma solig'i" in edits[1].text
    s = feed(bot_db, [callback(3500, "p:soha:o"), "Mebel ishlab chiqarish"], user_id=3500)
    assert "Faoliyat sohasi: Mebel ishlab chiqarish" in s.sent[-1].text
    s = feed(bot_db, [callback(3500, "p:soha:x")], user_id=3500)
    edits = [r for r in s.requests if type(r).__name__ == "EditMessageText"]
    assert "Faoliyat sohasi: —" in edits[0].text


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


# --- majburiy kanal a'zoligi -------------------------------------------------------------


def channel_cfg():
    return settings(required_channel="@soliq_kanal")


def test_channel_gate_blocks_non_members(bot_db):
    s = feed(bot_db, ["/modda 461", "QQS stavkasi"], user_id=5050, cfg=channel_cfg())
    assert all("kanalimizga a'zo bo'ling" in m.text for m in s.sent)
    buttons = [b for row in s.sent[0].reply_markup.inline_keyboard for b in row]
    assert buttons[0].url == "https://t.me/soliq_kanal" and buttons[1].callback_data == "sub:check"
    assert not query(bot_db, "SELECT 1 FROM suhbatlar WHERE telegram_id = 5050")


def test_channel_gate_start_registers_and_shows_invite(bot_db):
    s = feed(bot_db, ["/start"], user_id=5100, cfg=channel_cfg())
    assert "Assalomu alaykum" in s.sent[0].text and "kanalimizga a'zo bo'ling" in s.sent[1].text
    assert query(bot_db, "SELECT 1 FROM foydalanuvchilar WHERE telegram_id = 5100")


def test_channel_members_and_admins_pass(bot_db):
    member = feed(bot_db, ["/modda 461"], user_id=5200, cfg=channel_cfg(), members={5200})
    assert "461-modda" in member.sent[0].text
    admin = feed(bot_db, ["/modda 461"], user_id=ADMIN, cfg=channel_cfg())
    assert "461-modda" in admin.sent[0].text
    assert not [r for r in admin.requests if isinstance(r, GetChatMember)]  # admin tekshirilmaydi


def test_channel_membership_is_cached(bot_db):
    s = feed(bot_db, ["/modda 461", "/modda 462"], user_id=5300, cfg=channel_cfg(), members={5300})
    assert len([r for r in s.requests if isinstance(r, GetChatMember)]) == 1


def test_joined_button_rechecks(bot_db):
    s = feed(bot_db, [callback(5400, "sub:check")], user_id=5400, cfg=channel_cfg())
    alert = [r for r in s.requests if type(r).__name__ == "AnswerCallbackQuery"][0]
    assert "hali kanalga a'zo emassiz" in alert.text
    s = feed(bot_db, [callback(5400, "sub:check")], user_id=5400, cfg=channel_cfg(), members={5400})
    edits = [r for r in s.requests if type(r).__name__ == "EditMessageText"]
    assert "Endi savolingizni yozishingiz mumkin" in edits[0].text


def test_channel_check_error_does_not_lock_users_out(bot_db):
    class Broken(MockedSession):
        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, GetChatMember):
                from aiogram.exceptions import TelegramBadRequest

                raise TelegramBadRequest(method=method, message="chat not found")
            return await super().make_request(bot, method, timeout)

    session = Broken()

    async def go():
        pool = await create_pool(bot_db, min_size=1, max_size=2)
        try:
            dp = build_dispatcher(pool, channel_cfg(), None)
            await dp.feed_update(Bot(TOKEN, session=session), update(5500, "/modda 461"))
        finally:
            await pool.close()

    run(go())
    assert "461-modda" in session.sent[0].text


def test_gate_disabled_without_channel(bot_db):
    s = feed(bot_db, ["/modda 461"], user_id=5600)
    assert "461-modda" in s.sent[0].text
    assert not [r for r in s.requests if isinstance(r, GetChatMember)]


def test_followup_question_uses_previous_question(bot_db):
    s = feed(bot_db, ["Soliq imtiyozlari shartlari qanday?", "Bu qachon beriladi?"], user_id=6050, llm=None)
    assert "🔗 Oldingi savolingiz bilan bog'lab qidirdim: «Soliq imtiyozlari shartlari qanday?»" in s.sent[1].text
    assert s.sent[1].text.count("📌") >= 1
    rows = query(bot_db, "SELECT question, status FROM suhbatlar WHERE telegram_id = 6050 ORDER BY id")
    assert [r["question"] for r in rows] == ["Soliq imtiyozlari shartlari qanday?", "Bu qachon beriladi?"]


def test_standalone_question_is_not_linked(bot_db):
    s = feed(bot_db, ["Soliq imtiyozlari shartlari qanday?", "Jarima qanday hisoblanadi?"], user_id=6150, llm=None)
    assert "Oldingi savolingiz" not in s.sent[1].text


# --- /admin paneli -------------------------------------------------------------------------


def test_admin_panel_is_admin_only(bot_db):
    assert "faqat adminlar" in feed(bot_db, ["/admin"], user_id=USER).sent[0].text
    s = feed(bot_db, ["/admin"], user_id=ADMIN)
    data = [b.callback_data for row in s.sent[0].reply_markup.inline_keyboard for b in row]
    assert data == ["a:neg", "a:miss", "a:news", "a:stat"]
    s = feed(bot_db, [callback(USER, "a:neg")], user_id=USER)
    assert not s.sent  # oddiy foydalanuvchi — faqat ogohlantirish


def test_admin_negative_and_unanswered_lists(bot_db):
    feed(bot_db, ["Soliq imtiyozlari shartlari qanday?", "qwzx yyyy"], user_id=6200, llm=None)
    rid = query(bot_db, "SELECT request_id FROM suhbatlar WHERE telegram_id = 6200 AND status = 'sources_only'")[0][0]
    feed(bot_db, [callback(6200, f"r:{rid}:-1")], user_id=6200)
    neg = feed(bot_db, [callback(ADMIN, "a:neg")], user_id=ADMIN).sent[0].text
    assert "👎 Salbiy baholar" in neg and "Soliq imtiyozlari shartlari qanday?" in neg
    miss = feed(bot_db, [callback(ADMIN, "a:miss")], user_id=ADMIN).sent[0].text
    assert "❓ Javobsiz savollar" in miss and "qwzx yyyy" in miss and "not_found" in miss
    news = feed(bot_db, [callback(ADMIN, "a:news")], user_id=ADMIN).sent[0].text
    assert "tasdiq kutmoqda: 0" in news
    stat = feed(bot_db, [callback(ADMIN, "a:stat")], user_id=ADMIN).sent[0].text
    assert "<b>Statistika</b>" in stat


def test_voice_and_non_text_messages_get_friendly_reply(bot_db):
    from aiogram.types import PhotoSize, Voice

    def msg_update(n, **kw):
        return Update(update_id=n, message=Message(
            message_id=n, date=datetime.now(timezone.utc), chat=Chat(id=6300, type="private"),
            from_user=User(id=6300, is_bot=False, first_name="Test"), **kw))

    voice = msg_update(1, voice=Voice(file_id="v", file_unique_id="v", duration=3))
    photo = msg_update(2, photo=[PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)])
    s = feed(bot_db, [voice, photo], user_id=6300)
    assert "Ovozli xabarlarni hozircha tushunmayman" in s.sent[0].text
    assert "faqat matnli savollarni" in s.sent[1].text


# --- /hisobla ---------------------------------------------------------------------------


def test_calculator_dialog(bot_db):
    s = feed(bot_db, ["/hisobla", callback(6400, "h:qqs_qosh"), "10 000 000"], user_id=6400)
    kinds = [b.callback_data for row in s.sent[0].reply_markup.inline_keyboard for b in row]
    assert kinds == ["h:qqs_qosh", "h:qqs_ajrat", "h:jshds", "h:aylanma", "h:penya"]
    text = s.sent[-1].text
    assert "QQS (12%): <b>1 200 000</b> so'm" in text and "Jami (QQS bilan): <b>11 200 000</b> so'm" in text
    assert '<a href="https://lex.uz/docs/-4674902#' in text and "258-modda" in text
    buttons = [b.callback_data for row in s.sent[-1].reply_markup.inline_keyboard for b in row]
    assert buttons == ["h:menu", "v:m:-4674902:258"]


def test_calculator_turnover_rate_choice_and_bad_input(bot_db):
    s = feed(bot_db, [callback(6500, "h:aylanma"), callback(6500, "h:aylanma:2", 101), "abc", "1 000 000"],
             user_id=6500)
    assert [b.callback_data for row in s.sent[0].reply_markup.inline_keyboard for b in row] == \
        ["h:aylanma:4", "h:aylanma:2", "h:aylanma:1"]
    assert "Sonni tushunmadim" in s.sent[2].text
    assert "Soliq (2%): <b>20 000</b> so'm" in s.sent[3].text


def test_calculator_question_instead_of_number_goes_to_question(bot_db):
    s = feed(bot_db, [callback(6600, "h:jshds"), "Soliq imtiyozlari shartlari qanday?"], user_id=6600, llm=None)
    assert s.sent[1].text.startswith("Hozir to'liq javob tayyorlay olmadim")


def test_calendar_command_and_toggle(bot_db):
    s = feed(bot_db, ["/profil rejim Aylanma solig'i", "/kalendar", callback(6700, "k:on")], user_id=6700)
    text = s.sent[1].text
    assert "📅 <b>Soliq kalendari</b>" in text and "Aylanma solig'i — hisobot va to'lov" in text
    assert "QQS" not in text  # aylanma soliq to'lovchiga QQS muddati ko'rsatilmaydi
    assert '<a href="https://lex.uz/docs/-4674902#' in text and "Eslatmalar: o'chiq" in text
    assert s.sent[1].reply_markup.inline_keyboard[0][0].callback_data == "k:on"
    edit = [r for r in s.requests if type(r).__name__ == "EditMessageText"][0]
    assert "Eslatmalar: yoqilgan" in edit.text
    assert query(bot_db, "SELECT eslatma FROM foydalanuvchilar WHERE telegram_id = 6700")[0][0] is True
