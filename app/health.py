"""Health check (spec 30, PHASE 7): server monitoringi, cron yoki systemd timer uchun.

    python -m app.health            # JSON natija; muammo bo'lsa exit code 1
    python -m app.health --bot      # + bot jarayoni tirikligi (heartbeat fayli)

Tekshiruvlar:
- db: bazaga ulanish, hujjatlar va elementlar soni;
- documents: hujjatlar holati (kuchga kirish sanasi o'tgan, lekin "kuchga_kirmagan" qolganlar — ogohlantirish);
- rss: oxirgi RSS yozuvi 36 soatdan eski bo'lmasin (kunlik job ishlayaptimi);
- heartbeat (--bot): bot scheduler'i har 5 daqiqada yangilaydigan fayl 15 daqiqadan eski bo'lmasin.
Secret'lar chiqarilmaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import get_settings
from app.database.connection import connect

HEARTBEAT_FILE = Path(".cache/heartbeat")
HEARTBEAT_MAX_AGE = 15 * 60
RSS_MAX_AGE = timedelta(hours=36)


def write_heartbeat(path: Path = HEARTBEAT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(time.time())))


async def check(dsn: str, bot: bool) -> dict:
    result: dict = {"ok": True, "checks": {}}

    def fail(name: str, detail) -> None:
        result["ok"] = False
        result["checks"][name] = {"ok": False, "detail": detail}

    try:
        conn = await connect(dsn)
    except Exception as exc:
        fail("db", f"ulanib bo'lmadi: {type(exc).__name__}")
        return result
    try:
        docs = await conn.fetchval("SELECT count(*) FROM hujjatlar")
        elements = await conn.fetchval("SELECT count(*) FROM elementlar")
        if not docs or not elements:
            fail("db", {"hujjatlar": docs, "elementlar": elements})
        else:
            result["checks"]["db"] = {"ok": True, "hujjatlar": docs, "elementlar": elements}

        stale = await conn.fetchval(
            "SELECT count(*) FROM hujjatlar WHERE status = 'kuchga_kirmagan' AND effective_date < current_date"
        )
        result["checks"]["documents"] = {"ok": True, "overdue_future_docs": stale}

        last_rss = await conn.fetchval("SELECT max(created_at) FROM yangiliklar")
        if last_rss is None or datetime.now(timezone.utc) - last_rss > RSS_MAX_AGE:
            fail("rss", {"last": last_rss.isoformat() if last_rss else None})
        else:
            result["checks"]["rss"] = {"ok": True, "last": last_rss.isoformat()}
    finally:
        await conn.close()

    if bot:
        try:
            age = time.time() - int(HEARTBEAT_FILE.read_text().strip())
        except (OSError, ValueError):
            age = None
        if age is None or age > HEARTBEAT_MAX_AGE:
            fail("heartbeat", {"age_seconds": None if age is None else int(age)})
        else:
            result["checks"]["heartbeat"] = {"ok": True, "age_seconds": int(age)}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot", action="store_true", help="bot jarayoni heartbeat'ini ham tekshirish")
    args = parser.parse_args()
    settings = get_settings()
    settings.require("supabase_db_url")
    result = asyncio.run(check(settings.supabase_db_url.get_secret_value(), args.bot))
    print(json.dumps(result, ensure_ascii=False, default=str))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
