"""APScheduler (Asia/Tashkent): collector job'lari bot bilan bitta jarayonda.

- 07:10, 12:10, 17:10 — RSS (kuniga 3 marta — yangilik tezroq aniqlansin)
- 07:40 — kuchga kirish sanasi kelgan hujjatlarni qayta tekshirish
- Yakshanba 03:20 — kuzatiladigan hujjatlarni to'liq yangilash (asosiy + RSS/qidiruvdan topilganlar)
- Shanba 04:10 — Lex.uz qidiruvi: amaldagi eski hujjatlar ro'yxati
- 08:10 — topilgan hujjatlardan kunlik limit bo'yicha import (DISCOVERY_DAILY_LIMIT, 0 = o'chiq)
- 09:30 — soliq kalendari eslatmalari (rozilik berganlarga)
- har 15 daqiqada (kunduzi) — yangilik/o'zgarish xabarlari: tayyorlash → admin tasdig'i → yuborish
- har 5 daqiqada — heartbeat fayli (health check)
Vaqtlar :00 dan siljitilgan (Lex.uz'ga bir vaqtda tushadigan yuklamani kamaytirish uchun).
Job ichidagi xato scheduler'ni to'xtatmaydi; bir vaqtda bitta nusxa (max_instances=1).
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.collector.jobs import discover_job, future_recheck_job, import_found_job, rss_job, weekly_refresh_job
from app.config import Settings
from app.health import write_heartbeat
from app.services import kalendar
from app.services.xabarlar import is_daytime, publish
from app.utils.logging import request_context

log = logging.getLogger(__name__)


async def publish_job(bot, pool, settings: Settings, llm) -> None:
    with request_context():
        try:
            await publish(bot, pool, settings, llm)
        except Exception:
            log.error("publish_job failed", exc_info=True)


async def reminders_job(bot, pool, settings: Settings) -> None:
    """Soliq kalendari eslatmalari (rozilik berganlarga, kunduzi, har biri bir marta)."""
    if not is_daytime(settings):
        return
    with request_context():
        try:
            async with pool.acquire() as conn:
                links = await kalendar.article_links(conn)
            n = await kalendar.send_reminders(bot, pool, datetime.now(settings.tz).date(), links)
            log.info("reminders sent=%d", n)
        except Exception:
            log.error("reminders_job failed", exc_info=True)


def build_scheduler(pool, settings: Settings, llm, bot=None) -> AsyncIOScheduler:
    tz = settings.tz
    scheduler = AsyncIOScheduler(timezone=tz, job_defaults={"max_instances": 1, "coalesce": True,
                                                             "misfire_grace_time": 3600})
    scheduler.add_job(rss_job, CronTrigger(hour="7,12,17", minute=10, timezone=tz), args=[pool, settings, llm],
                      id="rss")
    scheduler.add_job(future_recheck_job, CronTrigger(hour=7, minute=40, timezone=tz), args=[pool, settings],
                      id="future_recheck")
    scheduler.add_job(weekly_refresh_job, CronTrigger(day_of_week="sun", hour=3, minute=20, timezone=tz),
                      args=[pool, settings], id="weekly_refresh")
    scheduler.add_job(discover_job, CronTrigger(day_of_week="sat", hour=4, minute=10, timezone=tz),
                      args=[pool, settings], id="discover")
    scheduler.add_job(import_found_job, CronTrigger(hour=8, minute=10, timezone=tz), args=[pool, settings],
                      id="import_found")
    # Health check uchun: bot jarayoni tirikligini ko'rsatadi (app/health.py --bot).
    scheduler.add_job(write_heartbeat, IntervalTrigger(minutes=5), id="heartbeat")
    if bot is not None:  # xabar yuborish uchun bot kerak (CLI job'larida yo'q)
        scheduler.add_job(publish_job, IntervalTrigger(minutes=15), args=[bot, pool, settings, llm], id="publish")
        scheduler.add_job(reminders_job, CronTrigger(hour=9, minute=30, timezone=tz), args=[bot, pool, settings],
                          id="reminders")
    return scheduler
