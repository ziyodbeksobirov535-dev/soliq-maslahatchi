"""Umumiy fixture'lar.

Database testlari faqat TEST_DATABASE_URL berilganda ishlaydi (aks holda skip):
    TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/postgres python -m pytest
Har bir test sessiyasi uchun vaqtinchalik baza yaratiladi va oxirida o'chiriladi.
Production bazani bu yerga bermang.
"""

import asyncio
import os
import uuid

import pytest


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def admin_dsn():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL berilmagan — database testlari o'tkazib yuborildi")
    return dsn


def _temp_database(admin_dsn):
    """Vaqtinchalik baza yaratadi; generator — yield DSN, keyin o'chiradi."""
    import asyncpg

    name = f"soliq_test_{uuid.uuid4().hex[:12]}"

    async def execute(sql):
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    run(execute(f'CREATE DATABASE "{name}"'))
    base, _, _ = admin_dsn.rpartition("/")
    try:
        yield f"{base}/{name}"
    finally:
        run(execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def empty_db(admin_dsn):
    """Har bir test uchun alohida, migration qo'llanmagan bo'sh baza."""
    yield from _temp_database(admin_dsn)


@pytest.fixture(scope="session")
def db(admin_dsn):
    """Sessiya uchun umumiy, migration qo'llangan baza."""
    from app.database.migrate import migrate

    for dsn in _temp_database(admin_dsn):
        run(migrate(dsn))
        yield dsn
