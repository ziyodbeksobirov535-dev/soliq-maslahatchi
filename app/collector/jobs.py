"""Collector job'lari (spec 16–17) va ularni qo'lda ishga tushirish.

    python -m app.collector.jobs rss        # kunlik RSS
    python -m app.collector.jobs future     # kuchga kirish sanasi kelgan hujjatlarni qayta tekshirish
    python -m app.collector.jobs refresh    # asosiy hujjatlarni to'liq yangilash (hash + element diff)

Har bir job xatoni o'zi ushlaydi va log qiladi — scheduler va bot yiqilmaydi (spec 24).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import asyncpg

import lexuz
from app.collector.core_documents import approved_documents
from app.collector.importer import import_document
from app.collector.news import process_rss
from app.config import Settings, get_settings
from app.database.connection import create_pool
from app.utils.logging import request_context, setup_logging

log = logging.getLogger(__name__)


def make_lexuz_client(settings: Settings, *, cache: bool = False) -> lexuz.LexUzClient:
    return lexuz.LexUzClient(
        delay_seconds=settings.lexuz_delay_seconds,
        max_retries=settings.lexuz_max_retries,
        timeout_seconds=settings.lexuz_timeout_seconds,
        # Yangilanishni aniqlash uchun job'lar keshsiz ishlaydi (eski sahifa o'zgarishni yashirmasin).
        cache_dir=settings.lexuz_cache_dir if cache else None,
    )


async def refresh_document(pool: asyncpg.Pool, client: lexuz.LexUzClient, lex_id: str, settings: Settings):
    doc = await asyncio.to_thread(lexuz.load, lex_id, client=client)
    card = await asyncio.to_thread(lexuz.load_card, lex_id, client=client)
    async with pool.acquire() as conn:
        return await import_document(conn, doc, card, lexuz.today_tashkent())


async def rss_job(pool: asyncpg.Pool, settings: Settings, llm) -> None:
    with request_context():
        try:
            with make_lexuz_client(settings) as client:
                await process_rss(pool, client, llm, lexuz.today_tashkent())
        except Exception:
            log.error("rss_job failed", exc_info=True)


async def future_recheck_job(pool: asyncpg.Pool, settings: Settings) -> None:
    """Kuchga kirish sanasi kelgan 'kuchga_kirmagan' hujjatlar: qayta yuklash, holatni qayta baholash (spec 16)."""
    with request_context():
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT lex_id FROM hujjatlar WHERE status = 'kuchga_kirmagan' "
                    "AND (effective_date IS NULL OR effective_date <= $1)",
                    lexuz.today_tashkent(),
                )
            with make_lexuz_client(settings) as client:
                for r in rows:
                    try:
                        res = await refresh_document(pool, client, r["lex_id"], settings)
                        log.info("future recheck lex_id=%s status=%s", r["lex_id"], res.status)
                    except Exception:
                        log.error("future recheck failed lex_id=%s", r["lex_id"], exc_info=True)
        except Exception:
            log.error("future_recheck_job failed", exc_info=True)


async def weekly_refresh_job(pool: asyncpg.Pool, settings: Settings) -> None:
    """Asosiy hujjatlar: to'liq yangilash; import o'zgarishlarni `ozgarishlar` ga yozadi (spec 17)."""
    with request_context():
        with make_lexuz_client(settings) as client:
            for d in approved_documents():
                try:
                    res = await refresh_document(pool, client, d.lex_id, settings)
                    log.info("refresh lex_id=%s added=%d changed=%d removed=%d",
                             d.lex_id, res.added, res.changed, res.removed)
                except Exception:
                    log.error("refresh failed lex_id=%s", d.lex_id, exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collector job'larini qo'lda ishga tushirish")
    parser.add_argument("job", choices=["rss", "future", "refresh"])
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    settings.require("supabase_db_url")

    async def run() -> None:
        pool = await create_pool(settings.supabase_db_url.get_secret_value())
        try:
            if args.job == "rss":
                from app.bot.app import make_llm

                await rss_job(pool, settings, make_llm(settings))
            elif args.job == "future":
                await future_recheck_job(pool, settings)
            else:
                await weekly_refresh_job(pool, settings)
        finally:
            await pool.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
