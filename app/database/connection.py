"""PostgreSQL ulanishi (asyncpg pool).

search_path ga `extensions` qo'shiladi: pg_trgm funksiyalari (similarity, %) o'sha sxemada
(migrations/002_hardening.sql). Supabase pooler (transaction mode) uchun prepared statement
kesh o'chiriladi.
"""

from __future__ import annotations

import asyncpg

SERVER_SETTINGS = {"search_path": "public, extensions", "application_name": "soliq-maslahatchi"}


async def connect(dsn: str) -> asyncpg.Connection:
    return await asyncpg.connect(dsn, server_settings=SERVER_SETTINGS, statement_cache_size=0)


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 5) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        server_settings=SERVER_SETTINGS,
        statement_cache_size=0,
        command_timeout=60,
    )
