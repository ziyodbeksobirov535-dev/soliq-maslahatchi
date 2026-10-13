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
from app.retrieval.query import ABBREVIATIONS, DOMAIN_COMMON, SYNONYMS, QueryPlan, analyze, normalize
from app.retrieval.spelling import apply_fixes, suggest
from app.retrieval.structure import structural_articles

DEFAULT_LIMIT = 6
# Ierarxiya bo'yicha qayta tartiblash: SQL'dan ko'proq nomzod olinadi, og'irlikdan keyin `limit` tasi qoladi.
RERANK_CANDIDATES = 24
HIGH_LEVEL_TYPES = frozenset({"Кодекс", "Закон", "Kodeks", "Qonun"})
ON_TOPIC_WEIGHT = 1.2
OFF_TOPIC_WEIGHT = 0.5
MIN_TOPIC_COVERAGE = 0.5
# Kodeks/qonun moddasi: sarlavhasi savolga qanchalik aniq mos (heading_precision) — shuncha bonus. "Soliq agenti kim?"
# → "23-modda. Soliq agentlari" 6-o'rindan, "Penya" — 5-o'rindan (2026-10-13 sohalar sinovi).
CODE_HEADING_BONUS = 0.3
# Sarlavha savolning hamma so'zini qamraydi (263: bayram kunlari uchun haq to'lash); bitta qisqa band savolning
# ≥75% so'zini qamraydi (234: "Mehnat shartnomasi bekor qilinganda ... foydalanilmagan ... ta'tillari uchun pulli
# kompensatsiya"); "kim" savolida sarlavhada shaxs/rol ("subyektlari", "rahbari", "to'lovchilar").
CODE_COVERAGE_BONUS = 0.3
# Faqat uzun savolda (≥6 so'z): qisqa savolda bunday band deyarli har nomzodda bor (farqlamaydi) va sarlavha
# bonusini susaytiradi — "Soliq imtiyozidan foydalanish shartlari" 75 o'rniga 483 berardi.
CODE_ELEMENT_BONUS = 0.5
LONG_QUESTION_TERMS = 6
CODE_WHO_BONUS = 0.3
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
    hits = await rerank_by_hierarchy(conn, plan, hits, limit)
    if plan.lex_ids is None or SOLIQ_KODEKSI_LEX_ID in plan.lex_ids:
        hits = await with_structure(conn, plan, hits, limit)
    return hits


async def with_structure(conn: asyncpg.Connection, plan: QueryPlan, hits: list[ArticleHit],
                         limit: int) -> list[ArticleHit]:
    """Kodeks tuzilmasi bo'yicha topilgan moddalar (soliq turi + jihat: "aylanma ... kim to'laydi" → 461) — boshida.
    Qidiruvda ham topilgan bo'lsa, o'sha natija (mos elementlari bilan) ko'tariladi."""
    numbers = await structural_articles(conn, plan)
    if not numbers:
        return hits
    sk = SOLIQ_KODEKSI_LEX_ID
    existing = {h.modda_raqami: h for h in hits if h.lex_id == sk and h.modda_raqami}
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (e.modda_raqami) e.modda_raqami, e.element_id, e.link, e.text, h.name, h.status
        FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id
        WHERE h.lex_id = $1 AND e.kind = 'article' AND e.modda_raqami = ANY($2::text[])
        ORDER BY e.modda_raqami, e.order_no
        """,
        sk, numbers,
    )
    heads = {r["modda_raqami"]: r for r in rows}
    top = max((h.score for h in hits), default=1.0)
    routed: list[ArticleHit] = []
    for i, number in enumerate(numbers):
        hit = existing.get(number)
        if hit is None:
            r = heads.get(number)
            if r is None:
                continue
            hit = ArticleHit(lex_id=sk, document_name=r["name"], document_status=r["status"], modda_raqami=number,
                             heading=r["text"], heading_element_id=r["element_id"], heading_link=r["link"],
                             score=0.0, matched_terms=0, matched=[])
        routed.append(replace(hit, score=top + 0.01 * (len(numbers) - i),
                              matched_terms=max(hit.matched_terms, len(plan.terms))))
    keep = {h.modda_raqami for h in routed}
    rest = [h for h in hits if not (h.lex_id == sk and h.modda_raqami in keep)]
    return (routed + rest)[:limit]


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


def _heading_words(heading: str) -> list[str]:
    return [w for w in _WORDS_RE.findall(normalize(re.sub(r"^\S+-modda\.", "", heading or ""))) if len(w) >= 3]


def _question_stems(plan: QueryPlan) -> list[list[str]]:
    return [[t, *plan.variants.get(t, [])] for t in plan.terms] + [[g] for g in plan.generic_stems]


def heading_precision(plan: QueryPlan, heading: str) -> float:
    """Modda sarlavhasi so'zlarining qancha qismi savolda bor ("Soliq agentlari" — 1.0, "Soliq agentlari tomonidan
    soliqni hisoblab chiqarish tartibi" — 0.43). Umumiy so'zlar ("tartibi") ham sanaladi. Faqat "soliq" — 0."""
    words = _heading_words(heading)
    stems = _question_stems(plan)
    hit = [w for w in words if any(w.startswith(f) for forms in stems for f in forms)]
    if not words or not any(not w.startswith(tuple(DOMAIN_COMMON)) for w in hit):
        return 0.0
    return len(hit) / len(words)


def heading_covers_question(plan: QueryPlan, heading: str) -> bool:
    """Sarlavha savolning hamma so'zini (umumiylari bilan, kamida 3 ta) qamraydi: "Bayram kunlari ishlaganlik uchun
    haq to'lash" ↔ "Dam olish kunlarida yoki ishlanmaydigan bayram kunlarida mehnatga haq to'lash"."""
    stems = [forms for forms in _question_stems(plan) if forms[0] not in DOMAIN_COMMON]
    words = _heading_words(heading)
    return len(stems) >= 3 and all(any(w.startswith(f) for f in forms for w in words) for forms in stems)


def precise_element(plan: QueryPlan, hit: ArticleHit) -> bool:
    """Bitta qisqa band savol so'zlarining ≥75% ini qamraydi (savolda ≥4 so'z)."""
    return len(plan.terms) >= MIN_ELEMENT_TERMS and any(
        len(m.text) <= MAX_ELEMENT_CHARS and topic_coverage(plan, m.text) >= MIN_ELEMENT_COVERAGE for m in hit.matched)


_WHO_RE = re.compile(r"\bkim(lar|ga|ning)?\b")
_ROLE_RE = re.compile(r"subyekt|rahbar|tolovchi|agent|shaxslar|xodim|ishtirokchi|beruvchi|oluvchi|organ")


def hierarchy_weight(plan: QueryPlan, hit: ArticleHit, doc_type: str | None, doc_name: str | None) -> float:
    if doc_type in HIGH_LEVEL_TYPES:
        if hit.modda_raqami is None:
            return 1.0
        heading = normalize(hit.heading)
        return (1.0 + CODE_HEADING_BONUS * heading_precision(plan, hit.heading)
                + CODE_COVERAGE_BONUS * heading_covers_question(plan, hit.heading)
                + CODE_ELEMENT_BONUS * (len(plan.terms) >= LONG_QUESTION_TERMS and precise_element(plan, hit))
                + CODE_WHO_BONUS * answers_who(plan, hit, heading))
    unit_title = hit.birlik_nomi or hit.heading
    on_topic = max(topic_coverage(plan, doc_name or hit.document_name), topic_coverage(plan, unit_title))
    if on_topic >= MIN_TOPIC_COVERAGE:
        return ON_TOPIC_WEIGHT
    if precise_element(plan, hit):
        return 1.0
    return OFF_TOPIC_WEIGHT


def answers_who(plan: QueryPlan, hit: ArticleHit, heading: str) -> bool:
    """"Kim" savoli va sarlavhada shaxs/rol ("Buxgalteriya hisobi subyektlari", "Soliq agentlari"). Band matnidagi
    rol so'zi hisobga olinmaydi — "mas'ul shaxslar" kabi so'zlar har moddada uchraydi (2026-10-13 sinov)."""
    return bool(_WHO_RE.search(plan.normalized) and _ROLE_RE.search(heading))


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
