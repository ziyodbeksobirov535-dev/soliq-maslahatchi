"""Foydalanuvchilar, kunlik limit va suhbatlar jurnali (spec 5: foydalanuvchilar, suhbatlar).

- Kunlik limit Asia/Tashkent kuni bo'yicha: `foydalanuvchilar.daily_limit` (NULL → DAILY_QUESTION_LIMIT).
- Adminlar (ADMIN_TELEGRAM_IDS) limitga tushmaydi.
- Loglarga savol matni yozilmaydi (PII); savol faqat `suhbatlar` jadvalida (audit uchun, spec talabi).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import asyncpg

from app.services.answer import FinalAnswer

# /profil orqali o'zgartirish mumkin bo'lgan maydonlar (erkin matn emas — faqat shu kalitlar).
PROFILE_FIELDS = {
    "soha": "Faoliyat sohasi (masalan: savdo, qurilish, IT)",
    "rejim": "Soliq rejimi (masalan: aylanma soliq, QQS)",
    "shakl": "Tashkiliy shakl (masalan: MChJ, YaTT)",
}
PROFILE_VALUE_MAX = 100


@dataclass(frozen=True)
class User:
    telegram_id: int
    language: str
    daily_limit: int | None
    active: bool
    profile: dict


def _profile(value) -> dict:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


async def ensure_user(conn: asyncpg.Connection, telegram_id: int) -> User:
    row = await conn.fetchrow(
        """
        INSERT INTO foydalanuvchilar (telegram_id) VALUES ($1)
        ON CONFLICT (telegram_id) DO UPDATE SET bloklagan = false  -- yana yozdi — bot bloklanmagan
        RETURNING telegram_id, language, daily_limit, active, profile
        """,
        telegram_id,
    )
    return User(row["telegram_id"], row["language"], row["daily_limit"], row["active"], _profile(row["profile"]))


async def set_profile_field(conn: asyncpg.Connection, telegram_id: int, key: str, value: str) -> dict:
    if key not in PROFILE_FIELDS:
        raise ValueError(f"Noma'lum maydon: {key}")
    value = " ".join(value.split())[:PROFILE_VALUE_MAX]
    row = await conn.fetchrow(
        """
        UPDATE foydalanuvchilar
        SET profile = CASE WHEN $3 = '' THEN profile - $2 ELSE profile || jsonb_build_object($2::text, $3::text) END
        WHERE telegram_id = $1
        RETURNING profile
        """,
        telegram_id, key, value,
    )
    return _profile(row["profile"])


def day_start(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    return datetime.combine(local.date(), time.min, tzinfo=tz)


async def questions_today(conn: asyncpg.Connection, telegram_id: int, now: datetime, tz: ZoneInfo) -> int:
    start = day_start(now, tz)
    return await conn.fetchval(
        """
        SELECT count(*) FROM suhbatlar
        WHERE telegram_id = $1 AND created_at >= $2 AND created_at < $3
          AND coalesce(status, '') NOT IN ('limit_exceeded', 'error', 'unavailable')
        """,
        telegram_id, start, start + timedelta(days=1),
    )


def effective_limit(user: User, default_limit: int) -> int:
    return default_limit if user.daily_limit is None else user.daily_limit


def _element_db_ids(fa: FinalAnswer) -> list[int]:
    ids = []
    for a in fa.source_articles:
        for el in a.all_elements():
            if el.source_id.startswith("EL-") and el.source_id[3:].isdigit():
                ids.append(int(el.source_id[3:]))
    return ids


async def log_conversation(conn: asyncpg.Connection, telegram_id: int, question: str, fa: FinalAnswer) -> None:
    used = [
        {"source_id": c.source.source_id, "element_id": c.source.element_id, "link": c.source.link,
         "lex_id": c.article.lex_id, "modda": c.article.modda_raqami, "birlik": c.article.birlik,
         "claim": c.claim}
        for c in fa.citations
    ]
    await conn.execute(
        """
        INSERT INTO suhbatlar (request_id, telegram_id, question, search_queries, retrieved_element_ids, answer,
                               used_sources, extra_needed_queries, model, input_tokens, output_tokens,
                               cache_read_tokens, cache_creation_tokens, processing_ms, status)
        VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $13, $14, $15)
        ON CONFLICT (request_id) DO NOTHING
        """,
        fa.request_id, telegram_id, question, json.dumps(fa.search_queries, ensure_ascii=False),
        _element_db_ids(fa), fa.text, json.dumps(used, ensure_ascii=False),
        json.dumps(fa.needs_more, ensure_ascii=False), fa.usage.model, fa.usage.input_tokens,
        fa.usage.output_tokens, fa.usage.cache_read_tokens, fa.usage.cache_creation_tokens,
        fa.processing_ms, fa.status,
    )


async def log_simple(conn: asyncpg.Connection, request_id: str, telegram_id: int, question: str, status: str,
                     answer: str) -> None:
    await conn.execute(
        "INSERT INTO suhbatlar (request_id, telegram_id, question, answer, status) VALUES ($1::uuid, $2, $3, $4, $5) "
        "ON CONFLICT (request_id) DO NOTHING",
        request_id, telegram_id, question, answer, status,
    )


async def set_rating(conn: asyncpg.Connection, request_id: str, telegram_id: int, value: int) -> bool:
    """Javobga baho (1 / -1). Faqat o'z savoliga; topilmasa False."""
    if value not in (1, -1):
        raise ValueError("Baho 1 yoki -1 bo'lishi kerak")
    status = await conn.execute(
        "UPDATE suhbatlar SET rating = $3 WHERE request_id = $1::uuid AND telegram_id = $2",
        request_id, telegram_id, value,
    )
    return status.endswith(" 1")


@dataclass(frozen=True)
class Stats:
    users: int
    active_today: int
    questions_today: int
    questions_total: int
    by_status_today: dict[str, int]
    tokens_today: tuple[int, int]
    avg_ms_today: int | None
    documents: list[tuple[str, str, str, int]]  # (lex_id, name, status, elements)


async def collect_stats(conn: asyncpg.Connection, now: datetime, tz: ZoneInfo) -> Stats:
    start = day_start(now, tz)
    users = await conn.fetchval("SELECT count(*) FROM foydalanuvchilar")
    today = await conn.fetchrow(
        """
        SELECT count(*) AS n, count(DISTINCT telegram_id) AS u,
               coalesce(sum(input_tokens), 0) AS tin, coalesce(sum(output_tokens), 0) AS tout,
               avg(processing_ms)::int AS ms
        FROM suhbatlar WHERE created_at >= $1
        """,
        start,
    )
    total = await conn.fetchval("SELECT count(*) FROM suhbatlar")
    by_status = {
        r["status"] or "—": r["n"]
        for r in await conn.fetch(
            "SELECT status, count(*) AS n FROM suhbatlar WHERE created_at >= $1 GROUP BY status ORDER BY n DESC", start
        )
    }
    docs = [
        (r["lex_id"], r["name"], r["status"], r["n"])
        for r in await conn.fetch(
            "SELECT h.lex_id, h.name, h.status, count(e.id) AS n FROM hujjatlar h "
            "LEFT JOIN elementlar e ON e.document_id = h.id GROUP BY h.id ORDER BY h.id"
        )
    ]
    return Stats(users, today["u"], today["n"], total, by_status, (today["tin"], today["tout"]), today["ms"], docs)
