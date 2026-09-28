"""Collector job'lari (spec 16–17) va ularni qo'lda ishga tushirish.

    python -m app.collector.jobs rss        # kunlik RSS
    python -m app.collector.jobs future     # kuchga kirish sanasi kelgan hujjatlarni qayta tekshirish
    python -m app.collector.jobs refresh    # kuzatiladigan hujjatlarni to'liq yangilash (hash + element diff)
    python -m app.collector.jobs discover   # Lex.uz qidiruvi: amaldagi eski hujjatlar ro'yxatini yig'ish
    python -m app.collector.jobs import-found [--limit N]   # topilganlardan N tasini import qilish
    python -m app.collector.jobs vocab      # imlo tuzatish lug'atini (sozlar) qayta qurish
    python -m app.collector.jobs reclassify # topilgan hujjatlarni joriy filtr bo'yicha qayta baholash (so'rovsiz)

Har bir job xatoni o'zi ushlaydi va log qiladi — scheduler va bot yiqilmaydi (spec 24).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import asyncpg

import lexuz
from app.collector.core_documents import approved_documents
from app.collector.discovery import discover, import_pending, reclassify
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


async def refresh_vocabulary(pool: asyncpg.Pool) -> None:
    """Imlo tuzatish lug'ati (`sozlar`) — import'dan keyin yangi so'zlar qo'shilsin (~2 s)."""
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT yangila_sozlar()")
        log.info("vocabulary refreshed words=%d", n)
    except Exception:
        log.error("vocabulary refresh failed", exc_info=True)


async def rss_job(pool: asyncpg.Pool, settings: Settings, llm) -> None:
    with request_context():
        try:
            with make_lexuz_client(settings) as client:
                stats = await process_rss(pool, client, llm, lexuz.today_tashkent())
            if stats.imported:
                await refresh_vocabulary(pool)
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
            if rows:
                await refresh_vocabulary(pool)
        except Exception:
            log.error("future_recheck_job failed", exc_info=True)


async def tracked_documents(pool: asyncpg.Pool) -> list[str]:
    """Kuzatiladigan hujjatlar: asosiy hujjatlar + RSS va qidiruvdan import qilingan, kuchini yo'qotmaganlar."""
    ids = [d.lex_id for d in approved_documents()]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT h.lex_id FROM hujjatlar h WHERE h.status <> 'kuchini_yoqotgan' AND ("
            " EXISTS (SELECT 1 FROM yangiliklar y WHERE y.lex_id = h.lex_id AND y.imported) OR"
            " EXISTS (SELECT 1 FROM topilgan_hujjatlar t WHERE t.lex_id = h.lex_id AND t.imported))"
            " ORDER BY h.last_successful_load NULLS FIRST"
        )
    seen = set(ids)
    ids += [r["lex_id"] for r in rows if r["lex_id"] not in seen]
    return ids


async def weekly_refresh_job(pool: asyncpg.Pool, settings: Settings) -> None:
    """Asosiy va RSS'dan topilgan hujjatlar: to'liq yangilash; import o'zgarishlarni `ozgarishlar` ga yozadi
    (spec 17). Farmon/qarorga o'zgartirish kiritilsa, bir hafta ichida bazada yangilanadi."""
    with request_context():
        try:
            lex_ids = await tracked_documents(pool)
        except Exception:
            log.error("weekly_refresh_job: hujjatlar ro'yxati olinmadi", exc_info=True)
            return
        log.info("weekly refresh documents=%d", len(lex_ids))
        with make_lexuz_client(settings) as client:
            for lex_id in lex_ids:
                try:
                    res = await refresh_document(pool, client, lex_id, settings)
                    log.info("refresh lex_id=%s added=%d changed=%d removed=%d",
                             lex_id, res.added, res.changed, res.removed)
                except Exception:
                    log.error("refresh failed lex_id=%s", lex_id, exc_info=True)
        await refresh_vocabulary(pool)


async def discover_job(pool: asyncpg.Pool, settings: Settings) -> None:
    """Lex.uz qidiruvi: amaldagi eski hujjatlar ro'yxati (hujjatlar yuklanmaydi, ~80 so'rov)."""
    with request_context():
        try:
            with make_lexuz_client(settings) as client:
                await discover(pool, client)
        except Exception:
            log.error("discover_job failed", exc_info=True)


async def import_found_job(pool: asyncpg.Pool, settings: Settings, limit: int | None = None) -> None:
    """Topilgan hujjatlardan kunlik limit bo'yicha import (`DISCOVERY_DAILY_LIMIT`, 0 = o'chiq)."""
    limit = settings.discovery_daily_limit if limit is None else limit
    if limit <= 0:
        return
    with request_context():
        try:
            with make_lexuz_client(settings) as client:
                stats = await import_pending(pool, client, limit, lexuz.today_tashkent())
            if stats.imported:
                await refresh_vocabulary(pool)
        except Exception:
            log.error("import_found_job failed", exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collector job'larini qo'lda ishga tushirish")
    parser.add_argument("job", choices=["rss", "future", "refresh", "discover", "import-found", "vocab",
                                        "reclassify"])
    parser.add_argument("--limit", type=int, default=None, help="import-found: nechta hujjat (sukut: DISCOVERY_DAILY_LIMIT)")
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
            elif args.job == "discover":
                await discover_job(pool, settings)
            elif args.job == "import-found":
                await import_found_job(pool, settings, args.limit)
            elif args.job == "vocab":
                await refresh_vocabulary(pool)
            elif args.job == "reclassify":
                await reclassify(pool)
            else:
                await weekly_refresh_job(pool, settings)
        finally:
            await pool.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
