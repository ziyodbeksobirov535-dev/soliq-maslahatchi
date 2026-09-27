"""Telegram buyruqlari (spec 20): /start, /profil, /modda, /stat, /yangiliklar, oddiy savol.

Bog'liqliklar dispatcher orqali beriladi (`dp["pool"]`, `dp["llm"]`, `dp["settings"]`):
- pool: asyncpg pool;
- llm: ClaudeLLM yoki None (kalit bo'lmasa — savol-javob o'chiq, /modda ishlayveradi);
- settings: app.config.Settings.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import asyncpg
from aiogram import F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import ErrorEvent, LinkPreviewOptions, Message

from app.ai.client import LLM
from app.bot.formatting import esc, format_article, format_final_answer, split_message
from app.config import Settings
from app.retrieval.articles import get_article, normalize_article_number
from app.services.answer import answer_question
from app.services.users import (
    PROFILE_FIELDS,
    collect_stats,
    effective_limit,
    ensure_user,
    log_conversation,
    log_simple,
    questions_today,
    set_profile_field,
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

START_TEXT = (
    "Assalomu alaykum! Men O'zbekiston qonunchiligi bo'yicha yordamchiman.\n\n"
    "Savolingizni oddiy matn bilan yozing — javobni <b>Lex.uz</b>dagi rasmiy manba va havola bilan beraman.\n"
    "Masalan: <i>Aylanma solig'idan QQSga qachon o'tish kerak?</i>\n\n"
    "Buyruqlar:\n"
    "/modda 461 — Soliq kodeksi moddasi (boshqa hujjat: /modda 106 mehnat)\n"
    "/profil — profilingiz va kunlik limit\n"
    "/yangiliklar — qonunchilikdagi yangiliklar\n\n"
    "Hozir bazada: Soliq, Mehnat, Fuqarolik, Bojxona kodekslari va Buxgalteriya hisobi to'g'risidagi qonun.\n"
    "Bot yuridik maslahatchi o'rnini bosmaydi, lekin har bir javobni manbaga bog'laydi."
)


async def send_long(message: Message, html_text: str) -> None:
    for part in split_message(html_text):
        await message.answer(part, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)


async def cmd_start(message: Message, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await ensure_user(conn, message.from_user.id)
    await message.answer(START_TEXT, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)


async def cmd_profil(message: Message, command: CommandObject, pool: asyncpg.Pool, settings: Settings) -> None:
    tg_id = message.from_user.id
    args = (command.args or "").split(maxsplit=1)
    async with pool.acquire() as conn:
        user = await ensure_user(conn, tg_id)
        if args:
            key = args[0].lower()
            if key not in PROFILE_FIELDS:
                keys = ", ".join(PROFILE_FIELDS)
                await message.answer(f"Noma'lum maydon. Mumkin bo'lganlari: {esc(keys)}.\nMasalan: /profil rejim aylanma soliq",
                                     parse_mode=ParseMode.HTML)
                return
            profile = await set_profile_field(conn, tg_id, key, args[1] if len(args) > 1 else "")
        else:
            profile = user.profile
        used = await questions_today(conn, tg_id, datetime.now(timezone.utc), settings.tz)
    limit = "cheklanmagan (admin)" if settings.is_admin(tg_id) else str(effective_limit(user, settings.daily_question_limit))
    lines = ["<b>Profil</b>", f"Bugungi savollar: {used} / {esc(limit)}", ""]
    for key, title in PROFILE_FIELDS.items():
        lines.append(f"{esc(title.split(' (')[0])}: {esc(profile.get(key, '—'))}")
    lines += ["", "O'zgartirish: /profil &lt;maydon&gt; &lt;qiymat&gt; (maydonlar: " + esc(", ".join(PROFILE_FIELDS)) + ")"]
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


def parse_modda_args(args: str | None) -> tuple[str | None, list[str]]:
    number, docs = None, ["-4674902"]
    for token in (args or "").replace(",", " ").split():
        low = token.lower().strip(".")
        if low in DOC_ALIASES:
            docs = DOC_ALIASES[low]
        elif number is None:
            number = normalize_article_number(token)
    return number, docs


async def cmd_modda(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    number, docs = parse_modda_args(command.args)
    if number is None:
        await message.answer("Modda raqamini yozing. Masalan: /modda 461 yoki /modda 106 mehnat")
        return
    async with pool.acquire() as conn:
        await ensure_user(conn, message.from_user.id)
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


async def cmd_stat(message: Message, pool: asyncpg.Pool, settings: Settings) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    async with pool.acquire() as conn:
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
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_news(message: Message) -> None:
    await message.answer("Qonunchilik yangiliklari bo'limi tayyorlanmoqda (keyingi bosqich).")


async def cmd_unknown(message: Message) -> None:
    await message.answer("Noma'lum buyruq. /start — yordam.")


async def on_question(message: Message, pool: asyncpg.Pool, settings: Settings, llm: LLM | None) -> None:
    tg_id = message.from_user.id
    question = message.text.strip()
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
            if llm is None:
                text = ("Savol-javob xizmati hozircha sozlanmagan. Moddani ko'rish uchun /modda buyrug'idan "
                        "foydalaning (masalan: /modda 461).")
                await log_simple(conn, rid, tg_id, question, "unavailable", text)
                await message.answer(text)
                return

            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            fa = await answer_question(conn, llm, question, datetime.now(settings.tz).date(), request_id=rid)
            await log_conversation(conn, tg_id, question, fa)
        await send_long(message, format_final_answer(fa))


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
    router.message(Command("yangiliklar"))(cmd_news)
    router.message(F.text.startswith("/"))(cmd_unknown)
    router.message(F.text)(on_question)
    router.errors()(on_error)
    return router
