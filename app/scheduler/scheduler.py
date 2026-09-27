"""APScheduler (Asia/Tashkent): collector job'lari bot bilan bitta jarayonda.

- 07:10 — kunlik RSS
- 07:40 — kuchga kirish sanasi kelgan hujjatlarni qayta tekshirish
- Yakshanba 03:20 — asosiy hujjatlarni to'liq yangilash
- har 5 daqiqada — heartbeat fayli (health check)
Vaqtlar :00 dan siljitilgan (Lex.uz'ga bir vaqtda tushadigan yuklamani kamaytirish uchun).
Job ichidagi xato scheduler'ni to'xtatmaydi; bir vaqtda bitta nusxa (max_instances=1).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.collector.jobs import future_recheck_job, rss_job, weekly_refresh_job
from app.config import Settings
from app.health import write_heartbeat


def build_scheduler(pool, settings: Settings, llm) -> AsyncIOScheduler:
    tz = settings.tz
    scheduler = AsyncIOScheduler(timezone=tz, job_defaults={"max_instances": 1, "coalesce": True,
                                                             "misfire_grace_time": 3600})
    scheduler.add_job(rss_job, CronTrigger(hour=7, minute=10, timezone=tz), args=[pool, settings, llm], id="rss")
    scheduler.add_job(future_recheck_job, CronTrigger(hour=7, minute=40, timezone=tz), args=[pool, settings],
                      id="future_recheck")
    scheduler.add_job(weekly_refresh_job, CronTrigger(day_of_week="sun", hour=3, minute=20, timezone=tz),
                      args=[pool, settings], id="weekly_refresh")
    # Health check uchun: bot jarayoni tirikligini ko'rsatadi (app/health.py --bot).
    scheduler.add_job(write_heartbeat, IntervalTrigger(minutes=5), id="heartbeat")
    return scheduler
