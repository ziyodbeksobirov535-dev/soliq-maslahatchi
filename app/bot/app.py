"""Botni yig'ish va ishga tushirish (long polling)."""

from __future__ import annotations

import asyncio

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.ai.client import ClaudeLLM
from app.bot.handlers import create_router
from app.bot.subscription import MembershipChecker, SubscriptionMiddleware
from app.config import Settings
from app.database.connection import create_pool
from app.health import write_heartbeat
from app.scheduler.scheduler import build_scheduler

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Yordam va misollar"),
    BotCommand(command="modda", description="Modda matni: /modda 461"),
    BotCommand(command="hisobla", description="Soliq kalkulyatori: QQS, JSHDS, aylanma, penya"),
    BotCommand(command="kalendar", description="Soliq kalendari va eslatmalar"),
    BotCommand(command="profil", description="Profil va kunlik limit"),
    BotCommand(command="yangiliklar", description="Qonunchilik yangiliklari"),
    BotCommand(command="obuna", description="Tarif va kunlik limit"),
]


def build_dispatcher(pool, settings: Settings, llm) -> Dispatcher:
    dp = Dispatcher()
    dp["pool"] = pool
    dp["settings"] = settings
    dp["llm"] = llm
    # Bir vaqtdagi savollar: foydalanuvchi oldingi javobni kutayotgan bo'lsa — ikkinchisi qabul qilinmaydi;
    # bir vaqtda ko'pi bilan max_concurrent_questions savol ishlanadi (AI limiti, baza ulanishlari).
    dp["busy"] = set()
    dp["slots"] = asyncio.Semaphore(settings.max_concurrent_questions)
    checker = MembershipChecker()
    dp["membership"] = checker
    gate = SubscriptionMiddleware(checker)
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.include_router(create_router())
    return dp


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _primary_llm(settings: Settings):
    if settings.llm_provider == "gemini":
        from app.ai.gemini import GeminiLLM

        if not (settings.llm_api_key and settings.llm_main_model and settings.llm_fast_model):
            log.warning("LLM_* sozlamalari to'liq emas (gemini)")
            return None
        return GeminiLLM(settings)
    if settings.llm_provider == "openai_compat":
        from app.ai.openai_compat import OpenAICompatLLM

        if not (settings.llm_base_url and settings.llm_api_key and settings.llm_main_model and settings.llm_fast_model):
            log.warning("LLM_* sozlamalari to'liq emas (openai_compat)")
            return None
        return OpenAICompatLLM(settings)
    if settings.anthropic_api_key is None or not settings.anthropic_main_model or not settings.anthropic_fast_model:
        log.warning("ANTHROPIC sozlamalari to'liq emas")
        return None
    return ClaudeLLM(settings)


def _fallback_llm(settings: Settings, name: str):
    from app.ai.openai_compat import OpenAICompatLLM

    if name == "groq" and settings.groq_api_key:
        return OpenAICompatLLM(base_url=GROQ_BASE_URL, api_key=settings.groq_api_key.get_secret_value(),
                               main_model=settings.groq_main_model, fast_model=settings.groq_fast_model, name="groq")
    if name == "openrouter" and settings.openrouter_api_key and settings.openrouter_main_model:
        return OpenAICompatLLM(base_url=OPENROUTER_BASE_URL, api_key=settings.openrouter_api_key.get_secret_value(),
                               main_model=settings.openrouter_main_model,
                               fast_model=settings.openrouter_fast_model or settings.openrouter_main_model,
                               name="openrouter")
    log.warning("zaxira provayder %s: kalit yoki model berilmagan — o'tkazib yuborildi", name)
    return None


def make_llm(settings: Settings):
    """Asosiy provayder (LLM_PROVIDER) va zaxiralar (LLM_FALLBACKS) — bittadan ko'p bo'lsa zanjir."""
    providers = []
    primary = _primary_llm(settings)
    if primary is not None:
        providers.append((settings.llm_provider, primary))
    fast_only: set[str] = set()
    for item in [n.strip().lower() for n in settings.llm_fallbacks.split(",") if n.strip()]:
        name, _, role = item.partition(":")  # "groq:fast" — faqat qisqa vazifalar (so'rov tuzish, yangiliklar)
        llm = _fallback_llm(settings, name)
        if llm is not None:
            providers.append((name, llm))
            if role == "fast":
                fast_only.add(name)
    if not providers:
        log.warning("AI sozlamalari to'liq emas — savol-javob o'chiq, /modda ishlaydi")
        return None
    log.info("LLM: %s", " → ".join(n + (" (faqat qisqa vazifalar)" if n in fast_only else "") for n, _ in providers))
    if len(providers) == 1 and not fast_only:
        return providers[0][1]
    from app.ai.chain import ChainLLM

    return ChainLLM(providers, fast_only)


async def run_bot(settings: Settings) -> None:
    settings.require("telegram_bot_token", "supabase_db_url")
    pool = await create_pool(settings.supabase_db_url.get_secret_value(), max_size=settings.db_pool_max)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    try:
        llm = make_llm(settings)
        dp = build_dispatcher(pool, settings, llm)
        await bot.set_my_commands(COMMANDS)
        scheduler = build_scheduler(pool, settings, llm, bot)
        scheduler.start()
        write_heartbeat()
        log.info("bot started, scheduler jobs=%s", [j.id for j in scheduler.get_jobs()])
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            scheduler.shutdown(wait=False)
    finally:
        await bot.session.close()
        await pool.close()
