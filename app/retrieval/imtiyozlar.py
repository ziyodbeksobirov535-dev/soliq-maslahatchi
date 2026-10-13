"""Imtiyoz savollari: rasmiy imtiyozlar ro'yxatidan (bilimlar, turi='imtiyoz') mos bandlar → ular ko'rsatgan
Soliq kodeksi moddalari kontekstga (manba — Lex.uz matni, ro'yxat emas; spec 2, 19).

    "Qishloq xo'jaligi uchun qanday soliq imtiyozlari bor?"
      → ro'yxatdagi "qishloq xo'jaligi ..." bandlari (muddati o'tmagan) → 378-, 426-, 243-moddalar ...

- Savol imtiyozga oid: "imtiyoz", "ozod", "preferensiya", "kamaytirilgan", "chegirma" so'zlari.
- Bandlar savolning boshqa (mavzu) so'zlari bo'yicha: kamida yarmi mos kelishi kerak.
- Muddati o'tgan band (amal_muddati < bugun) olinmaydi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import asyncpg

from app.retrieval.query import QueryPlan

BENEFIT_PREFIXES = ("imtiyoz", "ozod", "preferens", "kamaytir", "chegirm")
MAX_RECORDS = 8
MAX_ARTICLES = 3


@dataclass(frozen=True)
class BenefitRecord:
    record_key: str
    topic: str
    text: str
    lex_id: str | None
    modda_raqami: str | None
    hujjat: str | None
    amal_muddati: date | None


def is_benefit_question(plan: QueryPlan) -> bool:
    return any(t.startswith(BENEFIT_PREFIXES) for t in plan.terms)


def topic_terms(plan: QueryPlan) -> list[str]:
    """Imtiyoz so'zlaridan tashqari mavzu so'zlari (fe'l oilasi va qisqartma to'liq nomi bilan OR guruh)."""
    out = []
    for t in plan.terms:
        if t.startswith(BENEFIT_PREFIXES) or t == "soli":
            continue
        out.append(plan.term_query(t))
    return out


async def find_benefits(conn: asyncpg.Connection, plan: QueryPlan, today: date,
                        limit: int = MAX_RECORDS) -> list[BenefitRecord]:
    terms = topic_terms(plan)
    if not terms:
        return []
    need = max(1, math.ceil(len(terms) / 2))
    try:
        rows = await conn.fetch(
            """
            WITH t AS (SELECT to_tsquery('simple', q) AS q FROM unnest($1::text[]) AS q),
                 b AS (
                SELECT b.*, (SELECT count(*) FROM t WHERE b.search_vector @@ t.q) AS hits
                FROM bilimlar b
                WHERE b.turi = 'imtiyoz' AND (b.amal_muddati IS NULL OR b.amal_muddati >= $2)
                  AND b.search_vector @@ to_tsquery('simple', array_to_string($1::text[], ' | ')))
            SELECT * FROM b WHERE hits >= $3
            ORDER BY hits DESC, ts_rank(search_vector, to_tsquery('simple', array_to_string($1::text[], ' | '))) DESC
            LIMIT $4
            """,
            terms, today, need, limit,
        )
    except asyncpg.UndefinedColumnError:  # 013 qo'llanmagan baza — imtiyozlarsiz
        return []
    return [BenefitRecord(r["record_key"], r["topic"], r["text"], r["lex_id"], r["modda_raqami"], r["hujjat"],
                          r["amal_muddati"]) for r in rows]


def article_refs(records: list[BenefitRecord], limit: int = MAX_ARTICLES) -> list[tuple[str, str]]:
    """Bandlar ko'rsatgan moddalar (ko'p uchragani birinchi), takrorsiz."""
    counts: dict[tuple[str, str], int] = {}
    for r in records:
        if r.lex_id and r.modda_raqami:
            counts[(r.lex_id, r.modda_raqami)] = counts.get((r.lex_id, r.modda_raqami), 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:limit]
