"""Retrieval (spec 6–7): savol → reja → PostgreSQL qidiruvi → 3–6 ta modda.

Qat'iy qoidalar:
- aniq modda so'ralsa ("461-modda") — birinchi navbatda to'g'ridan-to'g'ri olinadi;
- savol mazmunsiz/ishorali bo'lsa — qidirilmaydi, `needs_clarification` qaytadi;
- tarixiy savolda joriy matn manba sifatida QAYTARILMAYDI (spec 15). O'sha sana uchun
  versiya matni bazada bo'lmasa — `historical_unavailable` (keyingi bosqichda Lex.uz'dan
  `lexuz.load(on_date=...)` bilan olinadi);
- faqat `amalda` holatdagi hujjatlar qidiriladi (kelajakdagi/kuchini yo'qotganlar emas);
- havolalar faqat bazadan (parser Lex.uz ID'sidan qurgan) — hech narsa o'ylab topilmaydi.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date

import asyncpg

from app.retrieval.articles import SOLIQ_KODEKSI_LEX_ID, Article, get_article
from app.retrieval.query import QueryPlan, analyze

DEFAULT_LIMIT = 6
# Modda savoldagi mazmunli so'zlarning kamida shuncha ulushini qamrashi kerak (aks holda tasodifiy moslik).
MIN_COVERAGE = 0.5


@dataclass(frozen=True)
class MatchedElement:
    element_id: str
    kind: str
    text: str
    link: str
    score: float


@dataclass(frozen=True)
class ArticleHit:
    lex_id: str
    document_name: str
    document_status: str
    modda_raqami: str
    heading: str
    heading_element_id: str
    heading_link: str
    score: float
    matched_terms: int
    matched: list[MatchedElement]


@dataclass
class SearchResult:
    plan: QueryPlan
    hits: list[ArticleHit] = field(default_factory=list)
    direct_article: Article | None = None
    status: str = "ok"  # ok | not_found | needs_clarification | historical_unavailable

    @property
    def source_links(self) -> list[str]:
        if self.direct_article is not None:
            return [self.direct_article.link]
        return [h.heading_link for h in self.hits]


async def search_articles(
    conn: asyncpg.Connection,
    plan: QueryPlan,
    *,
    limit: int = DEFAULT_LIMIT,
    statuses: tuple[str, ...] = ("amalda",),
) -> list[ArticleHit]:
    if not plan.ts_terms:
        return []
    rows = await conn.fetch(
        "SELECT * FROM search_articles($1::text[], $2, $3::text[], $4::text[], $5, 300, $6::float8[])",
        plan.ts_terms,
        plan.trigram_text or None,
        plan.lex_ids,
        list(statuses),
        limit,
        plan.ts_weights,
    )
    hits = []
    for r in rows:
        matched = r["matched"]
        if isinstance(matched, str):
            matched = json.loads(matched)
        hits.append(
            ArticleHit(
                lex_id=r["lex_id"],
                document_name=r["document_name"],
                document_status=r["document_status"],
                modda_raqami=r["modda_raqami"],
                heading=r["heading"],
                heading_element_id=r["heading_element_id"],
                heading_link=r["heading_link"],
                score=float(r["score"]),
                matched_terms=r["matched_terms"],
                matched=[MatchedElement(**{k: m[k] for k in MatchedElement.__dataclass_fields__}) for m in matched],
            )
        )
    return hits


async def retrieve(conn: asyncpg.Connection, question: str, today: date, *, limit: int = DEFAULT_LIMIT) -> SearchResult:
    plan = analyze(question, today)
    result = SearchResult(plan=plan)

    if plan.article_number is not None:
        lex_ids = plan.lex_ids or [SOLIQ_KODEKSI_LEX_ID]
        if len(lex_ids) == 1 and not plan.is_historical:
            result.direct_article = await get_article(conn, plan.article_number, lex_ids[0])
            result.status = "ok" if result.direct_article else "not_found"
            return result

    if plan.needs_clarification:
        result.status = "needs_clarification"
        return result

    if plan.is_historical:
        # Tarixiy versiya matni hali bazada yo'q — joriy matnni manba qilib bermaymiz.
        has_versions = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM versiya_elementlari)")
        if not has_versions:
            result.status = "historical_unavailable"
            return result

    hits = await search_articles(conn, plan, limit=limit)
    needed = max(1, math.ceil(MIN_COVERAGE * len(plan.terms)))
    result.hits = [h for h in hits if h.matched_terms >= needed]
    result.status = "ok" if result.hits else "not_found"
    return result
