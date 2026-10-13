"""Retrieval (spec 6–7): savol → reja → PostgreSQL qidiruvi → 3–6 ta modda yoki bo'lim.

Moddasiz hujjatlar (farmon, qaror, nizom) bo'limlar bo'yicha qidiriladi (migration 009): natijada
`modda_raqami = None`, `birlik` va `birlik_nomi` to'ldiriladi.

Qat'iy qoidalar:
- aniq modda so'ralsa ("461-modda") — birinchi navbatda to'g'ridan-to'g'ri olinadi;
- savol mazmunsiz/ishorali bo'lsa — qidirilmaydi, `needs_clarification` qaytadi;
- tarixiy savolda joriy matn manba sifatida QAYTARILMAYDI (spec 15). O'sha sana uchun
  versiya matni bazada bo'lmasa — `historical_unavailable` (keyingi bosqichda Lex.uz'dan
  `lexuz.load(on_date=...)` bilan olinadi);
- faqat `amalda` holatdagi hujjatlar qidiriladi (kelajakdagi/kuchini yo'qotganlar emas);
- havolalar faqat bazadan (parser Lex.uz ID'sidan qurgan) — hech narsa o'ylab topilmaydi;
- huquqiy ierarxiya (2026-10-12, 466 hujjatli bazada o'lchangan): kodeks/qonun natijasi o'zgarmaydi; farmon,
  qaror va boshqa hujjat natijasi — hujjat nomi yoki bo'lim sarlavhasi savol so'zlarining kamida yarmini
  qamrasa ×1.2 (savol aynan shu hujjat haqida), aks holda ×0.5 (katta ilovalar kodeks moddasini surib
  chiqarmasin). Kodeks savollari top-1 5→6/10, top-6 9→10/10; qaror savollari top-1 6→7/7.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date

import asyncpg

from app.retrieval.articles import SOLIQ_KODEKSI_LEX_ID, Article, get_article
from app.retrieval.query import ABBREVIATIONS, SYNONYMS, QueryPlan, analyze, normalize
from app.retrieval.spelling import apply_fixes, suggest

DEFAULT_LIMIT = 6
# Ierarxiya bo'yicha qayta tartiblash: SQL'dan ko'proq nomzod olinadi, og'irlikdan keyin `limit` tasi qoladi.
RERANK_CANDIDATES = 24
HIGH_LEVEL_TYPES = frozenset({"Кодекс", "Закон", "Kodeks", "Qonun"})
ON_TOPIC_WEIGHT = 1.2
OFF_TOPIC_WEIGHT = 0.5
MIN_TOPIC_COVERAGE = 0.5
# Sarlavha mos kelmasa ham, bitta elementi savol so'zlarining shuncha qismini qamragan bo'lim — jarimasiz (×1.0).
# 2026-10-13: PF-100 II bo'limi ("Biznes o'sishini rag'batlantirish...") 2-bandi savolning 7 so'zidan 7 tasini
# qamragan, lekin sarlavha bo'yicha ×0.5 olib, 6 so'zga mos Bojxona kodeksi 338-moddasidan pastga tushardi.
MIN_ELEMENT_COVERAGE = 0.75
MIN_ELEMENT_TERMS = 4  # qisqa savolda ("QQS stavkasi") har qaror bandi ikkala so'zni qamraydi — 258 6-o'ringa tushardi
MAX_ELEMENT_CHARS = 400  # uzun kirish qismi yoki o'zgartirishlar ro'yxati so'zlarni tasodifan qamraydi
_WORDS_RE = re.compile(r"[a-z0-9]+")
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
    modda_raqami: str | None  # bo'limda None
    heading: str
    heading_element_id: str
    heading_link: str
    score: float
    matched_terms: int
    matched: list[MatchedElement]
    birlik: str | None = None  # moddada None
    birlik_nomi: str | None = None

    @property
    def unit_key(self) -> tuple[str, str]:
        """Hujjat ichidagi birlik: ("m", modda) yoki ("b", bo'lim)."""
        return ("m", self.modda_raqami) if self.modda_raqami is not None else ("b", self.birlik or "")


@dataclass
class SearchResult:
    plan: QueryPlan
    hits: list[ArticleHit] = field(default_factory=list)
    direct_article: Article | None = None
    status: str = "ok"  # ok | not_found | needs_clarification | historical_unavailable
    corrections: dict[str, str] = field(default_factory=dict)  # imlo tuzatishlari: {savoldagi: qidirilgan}

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
        max(limit, RERANK_CANDIDATES),
        plan.ts_weights,
    )
    hits = []
    for r in rows:
        matched = r["matched"]
        if isinstance(matched, str):
            matched = json.loads(matched)
        matched = matched or []
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
                birlik=r["birlik"],
                birlik_nomi=r["birlik_nomi"],
            )
        )
    return await rerank_by_hierarchy(conn, plan, hits, limit)


def topic_coverage(plan: QueryPlan, text: str) -> float:
    """Savol so'zlarining (fe'l oilasi bilan) qancha qismi matndagi so'z boshida uchraydi. Qisqartmaning to'liq nomi
    ("IV. Qo'shilgan qiymat solig'i bo'yicha soddalashtirilgan tartib" — "qqs") faqat boshqa savol so'zi ham
    uchraganda sanaladi: aks holda nomida QQS bor har qaror "QQS stavkasi" savoliga mos bo'lib qolardi."""
    norm = normalize(text or "")
    words = set(_WORDS_RE.findall(norm))
    terms = [[t, *plan.variants.get(t, [])] for t in plan.terms]
    if not terms or not words:
        return 0.0
    plain = sum(any(w.startswith(f) for f in forms for w in words) for forms in terms)
    by_name = sum(1 for forms in terms
                  if forms[0] in ABBREVIATIONS and not any(w.startswith(forms[0]) for w in words)
                  and any(name in norm for name in SYNONYMS.get(forms[0], ())))
    return (plain + (by_name if plain else 0)) / len(terms)


def hierarchy_weight(plan: QueryPlan, hit: ArticleHit, doc_type: str | None, doc_name: str | None) -> float:
    if doc_type in HIGH_LEVEL_TYPES:
        return 1.0
    unit_title = hit.birlik_nomi or hit.heading
    on_topic = max(topic_coverage(plan, doc_name or hit.document_name), topic_coverage(plan, unit_title))
    if on_topic >= MIN_TOPIC_COVERAGE:
        return ON_TOPIC_WEIGHT
    if len(plan.terms) >= MIN_ELEMENT_TERMS and any(
            len(m.text) <= MAX_ELEMENT_CHARS and topic_coverage(plan, m.text) >= MIN_ELEMENT_COVERAGE
            for m in hit.matched):
        return 1.0
    return OFF_TOPIC_WEIGHT


async def rerank_by_hierarchy(conn: asyncpg.Connection, plan: QueryPlan, hits: list[ArticleHit],
                              limit: int) -> list[ArticleHit]:
    if not hits:
        return hits
    rows = await conn.fetch("SELECT lex_id, type, name FROM hujjatlar WHERE lex_id = ANY($1::text[])",
                            list({h.lex_id for h in hits}))
    docs = {r["lex_id"]: (r["type"], r["name"]) for r in rows}
    weighted = [(h.score * hierarchy_weight(plan, h, *docs.get(h.lex_id, (None, None))), h) for h in hits]
    weighted.sort(key=lambda x: x[0], reverse=True)
    return [replace(h, score=score) for score, h in weighted[:limit]]


async def retrieve(conn: asyncpg.Connection, question: str, today: date, *, limit: int = DEFAULT_LIMIT) -> SearchResult:
    plan = analyze(question, today)
    corrections: dict[str, str] = {}
    if plan.article_number is None and plan.words:
        corrections = await suggest(conn, plan.words)
        if corrections:
            language = plan.language
            plan = analyze(apply_fixes(plan.normalized, corrections), today)
            plan.question, plan.language = question, language
    result = SearchResult(plan=plan, corrections=corrections)

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
