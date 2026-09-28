"""Obuna servisi: uzaytirish (ustma-ust), tugagan obuna, bekor qilish, to'lov bir marta hisoblanadi."""

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.database.connection import connect
from app.services import obuna
from tests.conftest import run

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
UID = 8500


def with_conn(dsn, fn):
    async def go():
        conn = await connect(dsn)
        try:
            await conn.execute("DELETE FROM obunalar WHERE telegram_id = $1", UID)
            await conn.execute("DELETE FROM tolovlar WHERE telegram_id = $1", UID)
            await conn.execute("INSERT INTO foydalanuvchilar (telegram_id) VALUES ($1) ON CONFLICT DO NOTHING", UID)
            return await fn(conn)
        finally:
            await conn.close()

    return run(go())


def test_extend_stacks_and_restarts_after_expiry(db):
    async def go(conn):
        a = await obuna.extend(conn, UID, 30, "admin", NOW)
        b = await obuna.extend(conn, UID, 30, "admin", NOW + timedelta(days=5))  # hali faol — oxiridan
        c = await obuna.extend(conn, UID, 10, "admin", NOW + timedelta(days=100))  # tugagan — hozirdan
        return a, b, c

    a, b, c = with_conn(db, go)
    assert a == NOW + timedelta(days=30)
    assert b == NOW + timedelta(days=60)
    assert c == NOW + timedelta(days=110)


def test_revoke_and_limits(db):
    async def go(conn):
        await obuna.extend(conn, UID, 30, "admin", NOW)
        active = await obuna.get_subscription(conn, UID)
        revoked = await obuna.revoke(conn, UID)
        after = await obuna.get_subscription(conn, UID)
        return active, revoked, after

    active, revoked, after = with_conn(db, go)
    assert active.active(NOW) and not active.active(NOW + timedelta(days=31))
    assert revoked and after.until is None
    assert obuna.daily_limit(active, NOW, 20, 100) == 100 and obuna.daily_limit(after, NOW, 20, 100) == 20


def test_payment_recorded_once(db):
    async def go(conn):
        first = await obuna.record_payment(conn, UID, 4900000, "UZS", 30, "charge-x", "p", NOW)
        again = await obuna.record_payment(conn, UID, 4900000, "UZS", 30, "charge-x", "p", NOW)
        n = await conn.fetchval("SELECT count(*) FROM tolovlar WHERE telegram_id = $1", UID)
        return first, again, n

    first, again, n = with_conn(db, go)
    assert first == NOW + timedelta(days=30) and again is None and n == 1


def test_payload_roundtrip():
    assert obuna.parse_payload(obuna.payload(123, 30)) == (123, 30)
    assert obuna.parse_payload("premium:abc:30") is None and obuna.parse_payload("") is None


def test_payment_token_is_redacted_from_logs():
    s = Settings(_env_file=None, payment_provider_token="12345:LIVE:secret")
    assert "12345:LIVE:secret" in s.secret_values()
