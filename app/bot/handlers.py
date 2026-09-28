"""Telegram buyruqlari (spec 20): /start, /profil, /modda, /stat, /yangiliklar, oddiy savol.

Bog'liqliklar dispatcher orqali beriladi (`dp["pool"]`, `dp["llm"]`, `dp["settings"]`):
- pool: asyncpg pool;
- llm: ClaudeLLM yoki None (kalit bo'lmasa — savolga Claude'siz "faqat manbalar" javobi, /modda ishlaydi);
- settings: app.config.Settings.

Qulayliklar:
- /modda raqamsiz → bot raqamni so'raydi, keyingi xabar raqam sifatida qabul qilinadi;
- "461", "461-modda", "106 mehnat" kabi xabar — to'g'ridan-to'g'ri modda;
- javob ostida tugmalar: manbaning to'liq matni, 👍/👎 baho;
- /profil — tugmalar bilan tanlash yoki o'zi yozish.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

import asyncpg
from aiogram import F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardMarkup, LinkPreviewOptions, Message

from app.ai.client import LLM
from app.bot.admin import admin_menu, negative_ratings, news_overview, unanswered
from app.bot.formatting import esc, format_article, format_final_answer, format_news, split_message
from app.bot.keyboards import (
    PROFILE_BUTTON_TITLES,
    PROFILE_OPTIONS,
    answer_keyboard,
    profile_keyboard,
    profile_options_keyboard,
    without_rating,
)
from app.bot.subscription import CHECK_CALLBACK, GATE_TEXT, MembershipChecker, gate_keyboard
from app.collector.news import recent_news
from app.config import Settings
from app.retrieval.articles import get_article, get_section, normalize_article_number
from app.retrieval.query import is_followup, normalize
from app.services.answer import answer_question, answer_without_llm
from app.services.xabarlar import decide, show_preview
from app.services.users import (
    PROFILE_FIELDS,
    collect_stats,
    effective_limit,
    ensure_user,
    last_question,
    log_conversation,
    log_simple,
    questions_today,
    set_profile_field,
    set_rating,
)
from app.utils.logging import request_context

log = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MAX_QUESTION_CHARS = 1000

DOC_ALIASES: dict[str, list[str]] = {
    "soliq": ["-4674902"],
    "sk": ["-4674902"],
    "mehnat": ["-6257288"],
    "mk": ["-6257288"],
    "bojxona": ["-2876354"],
    "fuqarolik": ["-111189", "-180552"],
    "fk": ["-111189", "-180552"],
    "buxgalteriya": ["-2931253"],
    "bux": ["-2931253"],
}
# Xabar faqat modda ishorasidan iborat bo'lsa ("461", "461-modda", "modda 121-1", "106 mehnat kodeksi").
_MODDA_WORDS = frozenset({"modda", "moddasi", "moddani", "kodeksi", "kodeks"})
_MODDA_TOKEN_RE = re.compile(r"\d{1,4}(?:[-.]\d{1,2})?¹?|[a-z]+")

START_TEXT = (
    "Assalomu alaykum! Men O'zbekiston qonunchiligi bo'yicha yordamchiman.\n\n"
    "Savolingizni oddiy matn bilan yozing — javobni <b>Lex.uz</b>dagi rasmiy manba va havola bilan beraman.\n"
    "Masalan: <i>Aylanma solig'idan QQSga qachon o'tish kerak?</i>\n"
    "Lotin yoki kirill yozuvida yozishingiz mumkin; ruscha savoldagi soliq atamalarini ham tushunaman.\n\n"
    "Buyruqlar:\n"
    "/modda 461 — Soliq kodeksi moddasi (boshqa hujjat: /modda 106 mehnat). Faqat raqam yozsangiz ham bo'ladi.\n"
    "/profil — soha, soliq rejimi va tashkiliy shakl (tugmalar bilan)\n"
    "/yangiliklar — qonunchilikdagi yangiliklar\n\n"
    "Hozir bazada: Soliq, Mehnat, Fuqarolik, Bojxona kodekslari va Buxgalteriya hisobi to'g'risidagi qonun.\n"
    "Bot yuridik maslahatchi o'rnini bosmaydi, lekin har bir javobni manbaga bog'laydi."
)
MODDA_PROMPT = "Qaysi modda? Raqamini yozing, masalan: <b>461</b> yoki <b>106 mehnat</b>."


class Waiting(StatesGroup):
    modda = State()  # /modda raqamsiz — keyingi xabar modda raqami
    profile_value = State()  # /profil → "Boshqa" — keyingi xabar maydon qiymati


async def send_long(message: Message, html_text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    parts = split_message(html_text)
    for i, part in enumerate(parts):
        await message.answer(part, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW,
                             reply_markup=reply_markup if i == len(parts) - 1 else None)


async def cmd_start(message: Message, pool: asyncpg.Pool, settings: Settings, state: FSMContext,
                    membership: MembershipChecker) -> None:
    await state.clear()
    tg_id = message.from_user.id
    async with pool.acquire() as conn:
        await ensure_user(conn, tg_id)
    await message.answer(START_TEXT, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
    if settings.required_channel and not settings.is_admin(tg_id) and \
            await membership.is_member(message.bot, settings, tg_id) is False:
        await message.answer(GATE_TEXT, parse_mode=ParseMode.HTML, reply_markup=gate_keyboard(settings))


async def on_subscription_check(query: CallbackQuery, settings: Settings, membership: MembershipChecker) -> None:
    """"✅ A'zo bo'ldim": a'zolikni keshsiz qayta tekshiradi."""
    if not settings.required_channel:
        await query.answer()
        return
    ok = await membership.is_member(query.bot, settings, query.from_user.id, fresh=True)
    if ok is False:
        await query.answer("Siz hali kanalga a'zo emassiz. Avval a'zo bo'ling.", show_alert=True)
        return
    await query.answer("Rahmat!")
    await query.message.edit_text("✅ Rahmat! Endi savolingizni yozishingiz mumkin.")


# --- /profil -------------------------------------------------------------------------


async def _profile_text(conn: asyncpg.Connection, tg_id: int, profile: dict, settings: Settings) -> str:
    user = await ensure_user(conn, tg_id)
    used = await questions_today(conn, tg_id, datetime.now(timezone.utc), settings.tz)
    limit = "cheklanmagan (admin)" if settings.is_admin(tg_id) else str(effective_limit(user, settings.daily_question_limit))
    lines = ["<b>Profil</b>", f"Bugungi savollar: {used} / {esc(limit)}", ""]
    for key, title in PROFILE_FIELDS.items():
        lines.append(f"{esc(title.split(' (')[0])}: {esc(profile.get(key, '—'))}")
    lines += ["", "O'zgartirish uchun quyidagi tugmani bosing."]
    return "\n".join(lines)


async def cmd_profil(message: Message, command: CommandObject, pool: asyncpg.Pool, settings: Settings,
                     state: FSMContext) -> None:
    await state.clear()
    tg_id = message.from_user.id
    args = (command.args or "").split(maxsplit=1)
    async with pool.acquire() as conn:
        user = await ensure_user(conn, tg_id)
        if args:  # eski usul ham ishlaydi: /profil rejim aylanma soliq
            key = args[0].lower()
            if key not in PROFILE_FIELDS:
                keys = ", ".join(PROFILE_FIELDS)
                await message.answer(f"Noma'lum maydon. Mumkin bo'lganlari: {esc(keys)}.\nMasalan: /profil rejim aylanma soliq",
                                     parse_mode=ParseMode.HTML)
                return
            profile = await set_profile_field(conn, tg_id, key, args[1] if len(args) > 1 else "")
        else:
            profile = user.profile
        text = await _profile_text(conn, tg_id, profile, settings)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=profile_keyboard())


async def on_profile_button(query: CallbackQuery, pool: asyncpg.Pool, settings: Settings, state: FSMContext) -> None:
    parts = (query.data or "").split(":")
    tg_id = query.from_user.id
    field = parts[1] if len(parts) > 1 else "-"
    if field != "-" and field not in PROFILE_OPTIONS:
        await query.answer()
        return
    if len(parts) == 2 and field != "-":  # maydon variantlari
        await query.message.edit_text(f"<b>{esc(PROFILE_BUTTON_TITLES[field])}</b> — tanlang:",
                                      parse_mode=ParseMode.HTML, reply_markup=profile_options_keyboard(field))
        await query.answer()
        return
    if len(parts) == 3 and parts[2] == "o":  # o'zi yozadi
        await state.set_state(Waiting.profile_value)
        await state.update_data(field=field)
        await query.message.answer(f"{esc(PROFILE_BUTTON_TITLES[field])}ni yozing (masalan: "
                                   f"{esc(PROFILE_OPTIONS[field][0])}).", parse_mode=ParseMode.HTML)
        await query.answer()
        return
    async with pool.acquire() as conn:
        user = await ensure_user(conn, tg_id)
        profile = user.profile
        if len(parts) == 3:
            choice = parts[2]
            if choice == "x":
                value = ""
            elif choice.isdigit() and int(choice) < len(PROFILE_OPTIONS[field]):
                value = PROFILE_OPTIONS[field][int(choice)]
            else:
                await query.answer()
                return
            profile = await set_profile_field(conn, tg_id, field, value)
        text = await _profile_text(conn, tg_id, profile, settings)
    await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=profile_keyboard())
    await query.answer("Saqlandi" if len(parts) == 3 else None)


async def on_profile_value(message: Message, pool: asyncpg.Pool, settings: Settings, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    field = data.get("field")
    if field not in PROFILE_FIELDS or not message.text or message.text.startswith("/"):
        return
    async with pool.acquire() as conn:
        profile = await set_profile_field(conn, message.from_user.id, field, message.text)
        text = await _profile_text(conn, message.from_user.id, profile, settings)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=profile_keyboard())


# --- /modda --------------------------------------------------------------------------


def parse_modda_args(args: str | None) -> tuple[str | None, list[str]]:
    number, docs = None, ["-4674902"]
    for token in (args or "").replace(",", " ").split():
        low = token.lower().strip(".")
        if low in DOC_ALIASES:
            docs = DOC_ALIASES[low]
        elif number is None:
            number = normalize_article_number(token)
    return number, docs


def modda_only(text: str) -> str | None:
    """Xabar faqat modda ishorasi bo'lsa — /modda argumentlari ("461 mehnat"), aks holda None."""
    norm = normalize(text).replace("-modda", " modda")
    tokens = _MODDA_TOKEN_RE.findall(norm)
    if not tokens or len(tokens) > 4 or len(norm) > 40:
        return None
    numbers = [t for t in tokens if t[0].isdigit()]
    rest = [t for t in tokens if not t[0].isdigit() and t not in _MODDA_WORDS]
    if len(numbers) != 1 or any(t not in DOC_ALIASES for t in rest):
        return None
    return " ".join([numbers[0], *rest])


async def show_modda(message: Message, pool: asyncpg.Pool, tg_id: int, args: str | None) -> None:
    number, docs = parse_modda_args(args)
    async with pool.acquire() as conn:
        await ensure_user(conn, tg_id)
        article = None
        for lex_id in docs:
            article = await get_article(conn, number, lex_id)
            if article:
                break
    if article is None:
        await message.answer(f"{number}-modda bazada topilmadi. Raqam va hujjat nomini tekshiring "
                             "(masalan: /modda 106 mehnat).")
        return
    await send_long(message, format_article(article))


async def cmd_modda(message: Message, command: CommandObject, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    number, _ = parse_modda_args(command.args)
    if number is None:
        await state.set_state(Waiting.modda)
        await message.answer(MODDA_PROMPT, parse_mode=ParseMode.HTML)
        return
    await show_modda(message, pool, message.from_user.id, command.args)


async def on_modda_number(message: Message, pool: asyncpg.Pool, settings: Settings, llm: LLM | None,
                          state: FSMContext) -> None:
    await state.clear()
    number, _ = parse_modda_args(message.text)
    if number is None:  # raqam emas — oddiy savol sifatida
        await on_question(message, pool, settings, llm, state)
        return
    await show_modda(message, pool, message.from_user.id, message.text)


async def on_view_source(query: CallbackQuery, pool: asyncpg.Pool) -> None:
    """Tugma: manbaning (modda yoki bo'lim) to'liq matni."""
    parts = (query.data or "").split(":", 3)
    if len(parts) != 4 or parts[1] not in ("m", "b"):
        await query.answer()
        return
    _, kind, lex_id, unit_id = parts
    async with pool.acquire() as conn:
        article = await (get_article(conn, unit_id, lex_id) if kind == "m" else get_section(conn, lex_id, unit_id))
    if article is None:
        await query.answer("Manba bazada topilmadi", show_alert=True)
        return
    await query.answer()
    await send_long(query.message, format_article(article))


async def on_rate(query: CallbackQuery, pool: asyncpg.Pool) -> None:
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[2] not in ("1", "-1"):
        await query.answer()
        return
    try:
        uuid.UUID(parts[1])
    except ValueError:
        await query.answer()
        return
    async with pool.acquire() as conn:
        saved = await set_rating(conn, parts[1], query.from_user.id, int(parts[2]))
    await query.answer("Rahmat, bahoyingiz saqlandi!" if saved else "Baho saqlanmadi")
    if saved:
        await query.message.edit_reply_markup(reply_markup=without_rating(query.message.reply_markup))


async def on_xabar_decision(query: CallbackQuery, pool: asyncpg.Pool, settings: Settings) -> None:
    """Admin: yangilik/o'zgarish xabarini tasdiqlash (x:ok:<id>) yoki bekor qilish (x:no:<id>)."""
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[1] not in ("ok", "no") or not parts[2].isdigit():
        await query.answer()  # "x:-" — hal qilingan ko'rinishdagi holat tugmasi
        return
    if not settings.is_admin(query.from_user.id):
        await query.answer("Faqat adminlar uchun", show_alert=True)
        return
    result = await decide(query.bot, pool, settings, int(parts[2]), query.from_user.id, parts[1] == "ok")
    await query.answer(result)


# --- /stat, /yangiliklar ----------------------------------------------------------------


async def stats_text(conn: asyncpg.Connection, settings: Settings) -> str:
    s = await collect_stats(conn, datetime.now(timezone.utc), settings.tz)
    lines = [
        "<b>Statistika</b>",
        f"Foydalanuvchilar: {s.users} (bugun faol: {s.active_today})",
        f"Savollar: bugun {s.questions_today}, jami {s.questions_total}",
        "Bugun natijalar: " + (", ".join(f"{esc(k)}={v}" for k, v in s.by_status_today.items()) or "—"),
        f"Tokenlar bugun: kirish {s.tokens_today[0]}, chiqish {s.tokens_today[1]}",
        f"O'rtacha javob vaqti: {s.avg_ms_today if s.avg_ms_today is not None else '—'} ms",
        "",
        "<b>Hujjatlar</b>",
    ] + [f"• {esc(name)} ({esc(status)}): {n} element" for _, name, status, n in s.documents]
    return "\n".join(lines)


async def cmd_stat(message: Message, pool: asyncpg.Pool, settings: Settings) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    async with pool.acquire() as conn:
        text = await stats_text(conn, settings)
    await send_long(message, text)


async def cmd_admin(message: Message, settings: Settings) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    await message.answer("<b>Admin paneli</b> — bo'limni tanlang:", parse_mode=ParseMode.HTML,
                         reply_markup=admin_menu())


async def on_admin_button(query: CallbackQuery, pool: asyncpg.Pool, settings: Settings) -> None:
    if not settings.is_admin(query.from_user.id):
        await query.answer("Faqat adminlar uchun", show_alert=True)
        return
    parts = (query.data or "").split(":")
    section = parts[1] if len(parts) > 1 else ""
    markup = None
    if section == "show" and len(parts) == 3 and parts[2].isdigit():
        ok = await show_preview(query.bot, pool, settings, int(parts[2]), query.from_user.id)
        await query.answer(None if ok else "Bu xabar allaqachon hal qilingan")
        return
    async with pool.acquire() as conn:
        if section == "neg":
            text = await negative_ratings(conn, settings.tz)
        elif section == "miss":
            text = await unanswered(conn, settings.tz)
        elif section == "news":
            text, markup = await news_overview(conn)
        elif section == "stat":
            text = await stats_text(conn, settings)
        else:
            await query.answer()
            return
    await query.answer()
    await send_long(query.message, text, markup)


async def cmd_news(message: Message, pool: asyncpg.Pool, settings: Settings) -> None:
    async with pool.acquire() as conn:
        entries = await recent_news(conn, datetime.now(settings.tz).date())
    if not entries:
        await message.answer("So'nggi 7 kunda soliq va biznesga oid yangi hujjat topilmadi.")
        return
    await send_long(message, format_news(entries))


async def cmd_unknown(message: Message) -> None:
    await message.answer("Noma'lum buyruq. /start — yordam.")


# --- oddiy savol -------------------------------------------------------------------------


async def on_question(message: Message, pool: asyncpg.Pool, settings: Settings, llm: LLM | None,
                      state: FSMContext | None = None) -> None:
    tg_id = message.from_user.id
    question = message.text.strip()
    args = modda_only(question)
    if args is not None:
        await show_modda(message, pool, tg_id, args)
        return
    with request_context() as rid:
        if len(question) > MAX_QUESTION_CHARS:
            await message.answer(f"Savol juda uzun. Iltimos, {MAX_QUESTION_CHARS} belgigacha qisqartiring.")
            return
        async with pool.acquire() as conn:
            user = await ensure_user(conn, tg_id)
            if not user.active:
                await message.answer("Hisobingiz vaqtincha faol emas.")
                return
            if not settings.is_admin(tg_id):
                used = await questions_today(conn, tg_id, datetime.now(timezone.utc), settings.tz)
                if used >= effective_limit(user, settings.daily_question_limit):
                    text = "Bugungi savollar limiti tugadi. Ertaga yana murojaat qiling."
                    await log_simple(conn, rid, tg_id, question, "limit_exceeded", text)
                    await message.answer(text)
                    return

            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            today = datetime.now(settings.tz).date()
            previous = None
            if is_followup(question, today):
                previous = await last_question(conn, tg_id, datetime.now(timezone.utc))
            asked = f"{previous} — {question}" if previous else question
            if llm is None:
                fa = await answer_without_llm(conn, asked, today, request_id=rid)
            else:
                fa = await answer_question(conn, llm, asked, today, request_id=rid, profile=user.profile)
            fa.followup_of = previous
            await log_conversation(conn, tg_id, question, fa)
        await send_long(message, format_final_answer(fa), answer_keyboard(fa))


async def on_error(event: ErrorEvent) -> bool:
    """Har qanday kutilmagan xato: foydalanuvchiga sodda xabar, logga tur va request_id (stack trace emas)."""
    log.error("bot error type=%s", type(event.exception).__name__, exc_info=event.exception)
    message = getattr(event.update, "message", None)
    if message is not None:
        try:
            await message.answer("Kechirasiz, texnik xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.")
        except Exception:  # Telegram xatosi xato ishlovchini yiqitmasin
            log.warning("bot error reply failed")
    return True


def new_request_id() -> str:
    return str(uuid.uuid4())


def create_router() -> Router:
    """Har bir Dispatcher uchun yangi Router (aiogram router faqat bitta dispatcher'ga ulanadi)."""
    router = Router(name="main")
    router.message(CommandStart())(cmd_start)
    router.message(Command("profil"))(cmd_profil)
    router.message(Command("modda"))(cmd_modda)
    router.message(Command("stat"))(cmd_stat)
    router.message(Command("admin"))(cmd_admin)
    router.message(Command("yangiliklar"))(cmd_news)
    router.message(F.text.startswith("/"))(cmd_unknown)
    router.message(Waiting.modda, F.text)(on_modda_number)
    router.message(Waiting.profile_value, F.text)(on_profile_value)
    router.message(F.text)(on_question)
    router.callback_query(F.data.startswith("v:"))(on_view_source)
    router.callback_query(F.data.startswith("r:"))(on_rate)
    router.callback_query(F.data.startswith("p:"))(on_profile_button)
    router.callback_query(F.data.startswith("x:"))(on_xabar_decision)
    router.callback_query(F.data == CHECK_CALLBACK)(on_subscription_check)
    router.callback_query(F.data.startswith("a:"))(on_admin_button)
    router.errors()(on_error)
    return router
