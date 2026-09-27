"""Botni yig'ish va ishga tushirish (long polling)."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.ai.client import ClaudeLLM
from app.bot.handlers import create_router
from app.config import Settings
from app.database.connection import create_pool
from app.health import write_heartbeat
from app.scheduler.scheduler import build_scheduler

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Yordam va misollar"),
    BotCommand(command="modda", description="Modda matni: /modda 461"),
    BotCommand(command="profil", description="Profil va kunlik limit"),
    BotCommand(command="yangiliklar", description="Qonunchilik yangiliklari"),
]


def build_dispatcher(pool, settings: Settings, llm) -> Dispatcher:
    dp = Dispatcher()
    dp["pool"] = pool
    dp["settings"] = settings
    dp["llm"] = llm
    dp.include_router(create_router())
    return dp


def make_llm(settings: Settings):
    if settings.anthropic_api_key is None or not settings.anthropic_main_model or not settings.anthropic_fast_model:
        log.warning("ANTHROPIC sozlamalari to'liq emas — savol-javob o'chiq, /modda ishlaydi")
        return None
    return ClaudeLLM(settings)


async def run_bot(settings: Settings) -> None:
    settings.require("telegram_bot_token", "supabase_db_url")
    pool = await create_pool(settings.supabase_db_url.get_secret_value())
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    try:
        llm = make_llm(settings)
        dp = build_dispatcher(pool, settings, llm)
        await bot.set_my_commands(COMMANDS)
        scheduler = build_scheduler(pool, settings, llm)
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
