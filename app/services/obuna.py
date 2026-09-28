"""Obuna (premium): kunlik savol limiti yuqori. To'lov — Telegram Payments (Click/Payme provider tokeni) yoki
admin qo'lda beradi (/obuna_ber).

- Bepul: DAILY_QUESTION_LIMIT; premium: PREMIUM_DAILY_LIMIT, `obunalar.tugash_at` gacha.
- Uzaytirish joriy muddat oxiridan (yoki hozirdan, agar tugagan bo'lsa) hisoblanadi.
- To'lov `tolovlar.telegram_charge_id` bo'yicha bir marta hisoblanadi (Telegram xabarni qayta yuborsa ham).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg

PAYLOAD_PREFIX = "premium"


@dataclass(frozen=True)
class Subscription:
    until: datetime | None

    def active(self, now: datetime) -> bool:
        return self.until is not None and self.until > now


async def get_subscription(conn: asyncpg.Connection, telegram_id: int) -> Subscription:
    until = await conn.fetchval("SELECT tugash_at FROM obunalar WHERE telegram_id = $1 AND active", telegram_id)
    return Subscription(until)


async def extend(conn: asyncpg.Connection, telegram_id: int, days: int, source: str, now: datetime) -> datetime:
    """Obunani `days` kunga uzaytiradi; yangi tugash vaqtini qaytaradi. Foydalanuvchi bazada bo'lishi kerak."""
    if days <= 0:
        raise ValueError("kun musbat bo'lishi kerak")
    return await conn.fetchval(
        """
        INSERT INTO obunalar (telegram_id, tugash_at, manba, active)
        VALUES ($1, $2::timestamptz + make_interval(days => $3), $4, true)
        ON CONFLICT (telegram_id) DO UPDATE SET
            tugash_at = greatest(coalesce(obunalar.tugash_at, $2::timestamptz), $2::timestamptz)
                        + make_interval(days => $3),
            manba = EXCLUDED.manba, active = true
        RETURNING tugash_at
        """,
        telegram_id, now, days, source,
    )


async def revoke(conn: asyncpg.Connection, telegram_id: int) -> bool:
    status = await conn.execute("UPDATE obunalar SET active = false WHERE telegram_id = $1 AND active", telegram_id)
    return status.endswith(" 1")


async def record_payment(conn: asyncpg.Connection, telegram_id: int, amount: int, currency: str, days: int,
                         charge_id: str, provider_charge_id: str | None, now: datetime) -> datetime | None:
    """To'lovni yozadi va obunani uzaytiradi (bitta tranzaksiya). Takroriy charge — None."""
    async with conn.transaction():
        new = await conn.fetchval(
            "INSERT INTO tolovlar (telegram_id, summa, valyuta, kun, telegram_charge_id, provider_charge_id) "
            "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (telegram_charge_id) DO NOTHING RETURNING id",
            telegram_id, amount, currency, days, charge_id, provider_charge_id)
        if new is None:
            return None
        return await extend(conn, telegram_id, days, "telegram", now)


def payload(telegram_id: int, days: int) -> str:
    return f"{PAYLOAD_PREFIX}:{telegram_id}:{days}"


def parse_payload(value: str) -> tuple[int, int] | None:
    parts = (value or "").split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    return int(parts[1]), int(parts[2])


def daily_limit(sub: Subscription, now: datetime, free_limit: int, premium_limit: int) -> int:
    return premium_limit if sub.active(now) else free_limit


def expires_text(until: datetime, tz) -> str:
    return until.astimezone(tz).strftime("%d.%m.%Y")

