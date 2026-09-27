"""Oddiy migration runner: `migrations/NNN_*.sql` fayllarini tartib bilan, bir marta qo'llaydi.

Ishlatish:  python -m app.database.migrate            (SUPABASE_DB_URL dan)
            python -m app.database.migrate --status   (qo'llangan/kutilayotganlar)

Har bir fayl alohida tranzaksiyada bajariladi va `schema_migrations` ga checksum bilan
yoziladi. Qo'llangan faylning matni keyin o'zgartirilsa — xato (yangi migration yozing).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""
# Parallel ishga tushgan ikki jarayon bir vaqtda migration qilmasligi uchun.
_LOCK_KEY = 7_311_902_001


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        if not _NAME_RE.match(path.name):
            raise MigrationError(f"Noto'g'ri migration nomi: {path.name} (kutilgan: 001_nom.sql)")
        migrations.append(Migration(version=path.stem, path=path))
    numbers = [m.version[:3] for m in migrations]
    if len(numbers) != len(set(numbers)):
        raise MigrationError(f"Takrorlangan migration raqami: {numbers}")
    return migrations


async def applied(conn: asyncpg.Connection) -> dict[str, str]:
    await conn.execute(_CREATE_TABLE)
    # Supabase public API orqali ko'rinmasligi uchun (boshqa jadvallar kabi).
    await conn.execute("ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY")
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {r["version"]: r["checksum"] for r in rows}


async def migrate(dsn: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Kutilayotgan migration'larni qo'llaydi va qo'llanganlar ro'yxatini qaytaradi."""
    migrations = discover(directory)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
        try:
            done = await applied(conn)
            for m in migrations:
                if m.version in done and done[m.version] != m.checksum:
                    raise MigrationError(
                        f"{m.version} allaqachon qo'llangan, lekin fayl o'zgargan. Yangi migration yozing."
                    )
            new = []
            for m in migrations:
                if m.version in done:
                    continue
                async with conn.transaction():
                    await conn.execute(m.sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                        m.version,
                        m.checksum,
                    )
                log.info("migration applied version=%s", m.version)
                new.append(m.version)
            return new
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
    finally:
        await conn.close()


async def status(dsn: str, directory: Path = MIGRATIONS_DIR) -> list[tuple[str, bool]]:
    conn = await asyncpg.connect(dsn)
    try:
        done = await applied(conn)
    finally:
        await conn.close()
    return [(m.version, m.version in done) for m in discover(directory)]


def main() -> None:
    from app.config import get_settings
    from app.utils.logging import setup_logging

    parser = argparse.ArgumentParser(description="Database migration'larini qo'llash")
    parser.add_argument("--status", action="store_true", help="faqat holatni ko'rsatish")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    settings.require("supabase_db_url")
    dsn = settings.supabase_db_url.get_secret_value()

    if args.status:
        for version, is_applied in asyncio.run(status(dsn)):
            print(f"{'✓' if is_applied else '·'} {version}")
        return
    new = asyncio.run(migrate(dsn))
    print("Qo'llandi: " + (", ".join(new) if new else "yangi migration yo'q"))


if __name__ == "__main__":
    main()
