"""Savol → javob zanjiri (spec 6–13).

    savol → retrieval (+ fast model so'rovlari) → manbalar konteksti → Claude (structured)
          → citation validation → [needs_more: ≤2 qo'shimcha qidiruv] → javob + bazadagi havolalar

Qat'iy qoidalar:
- noaniq savol / tarixiy versiya yo'q / manba topilmadi → Claude chaqirilmaydi, xavfsiz javob;
- havolalar faqat bazadan; model yozgan URL olib tashlanadi, noma'lum source_id rad etiladi;
- iqtibossiz javob bir marta qayta so'raladi, baribir bo'lmasa — "ma'lumot yetarli emas";
- needs_more halqasi ko'pi bilan 2 round (cheksiz halqa yo'q).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date

import asyncpg

from app.ai.client import LLM, LLMError, Usage
from app.ai.prompts import SourceArticle, SourceElement, render_user_message
from app.ai.validation import ValidatedAnswer, validate_answer
from app.retrieval.articles import Article, get_article
from app.retrieval.query import analyze
from app.retrieval.search import ArticleHit, SearchResult, retrieve, search_articles

log = logging.getLogger(__name__)

MAX_SOURCES = 5
MAX_EXTRA_ROUNDS = 2
MAX_ARTICLE_CHARS = 6000
EXTRA_PER_ROUND = 3

INSUFFICIENT_TEXT = (
    "Mavjud rasmiy manbalar asosida bu savolga qat'iy huquqiy xulosa berish uchun ma'lumot yetarli emas."
)
CLARIFY_TEXT = (
    "Savolingizni aniqlashtirib bering: qaysi soliq, hujjat yoki holat haqida so'rayapsiz? "
    "Masalan: \"QQS to'lovchisi bo'lish chegarasi qancha?\" yoki \"Soliq kodeksi 461-modda\"."
)
ERROR_TEXT = "Kechirasiz, javob tayyorlashda texnik xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring."


@dataclass
class FinalAnswer:
    status: str  # answered | insufficient | needs_clarification | historical_unavailable | not_found | error
    text: str
    request_id: str
    citations: list = field(default_factory=list)
    source_articles: list[SourceArticle] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    rounds: int = 0
    rejected_source_ids: list[str] = field(default_factory=list)
    removed_urls: list[str] = field(default_factory=list)
    needs_more: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    confidence: str | None = None
    processing_ms: int = 0

    @property
    def links(self) -> list[str]:
        return list(dict.fromkeys(c.source.link for c in self.citations))


def _source_id(db_id: int) -> str:
    return f"EL-{db_id}"


def article_to_source(article: Article, matched_element_ids: set[str] | None = None) -> SourceArticle:
    """Bazadagi moddani kontekstga aylantiradi; juda uzun moddada mos bandlar va qo'shnilari qoladi."""

    def conv(e) -> SourceElement:
        return SourceElement(source_id=_source_id(e.id), element_id=e.element_id, kind=e.kind, text=e.text, link=e.link)

    body = list(article.body)
    truncated = False
    if sum(len(e.text) for e in body) > MAX_ARTICLE_CHARS and matched_element_ids:
        keep: set[int] = {0}
        for i, e in enumerate(body):
            if e.element_id in matched_element_ids:
                keep.update({i - 1, i, i + 1})
        kept = [body[i] for i in sorted(k for k in keep if 0 <= k < len(body))]
        truncated = len(kept) < len(body)
        body = kept
    return SourceArticle(
        lex_id=article.document_lex_id,
        document_name=article.document_name,
        document_status=article.document_status,
        current_version=article.current_version,
        modda_raqami=article.number,
        heading=conv(article.heading),
        elements=[conv(e) for e in body],
        truncated=truncated,
    )


async def _articles_from_hits(conn: asyncpg.Connection, hits: list[ArticleHit]) -> list[SourceArticle]:
    out = []
    for h in hits:
        art = await get_article(conn, h.modda_raqami, h.lex_id)
        if art is not None:
            out.append(article_to_source(art, {m.element_id for m in h.matched}))
    return out


def _merge_hits(groups: list[list[ArticleHit]], limit: int) -> list[ArticleHit]:
    best: dict[tuple[str, str], ArticleHit] = {}
    for hits in groups:
        for h in hits:
            key = (h.lex_id, h.modda_raqami)
            if key not in best or h.score > best[key].score:
                best[key] = h
    return sorted(best.values(), key=lambda h: h.score, reverse=True)[:limit]


async def _search_text(conn: asyncpg.Connection, text: str, today: date, lex_ids: list[str] | None) -> list[ArticleHit]:
    plan = analyze(text, today)
    if lex_ids and not plan.lex_ids:
        plan.lex_ids = lex_ids
    if not plan.ts_terms:
        return []
    return await search_articles(conn, plan)


def format_answer(validated: ValidatedAnswer) -> str:
    lines = [validated.answer_markdown.strip(), "", "*Huquqiy asos:*"]
    grouped: dict[str, list] = {}
    for c in validated.citations:
        grouped.setdefault(c.source.link, []).append(c)
    for link, cs in grouped.items():
        a = cs[0].article
        claims = "; ".join(dict.fromkeys(c.claim for c in cs))
        lines.append(f"• {a.document_name}, {a.heading.text} — {claims}")
        lines.append(f"  {link}")
    return "\n".join(lines).strip()


def format_insufficient(articles: list[SourceArticle], needs_more: list[str]) -> str:
    lines = [INSUFFICIENT_TEXT]
    if needs_more:
        lines.append("Aniqlashtirish kerak: " + "; ".join(needs_more[:3]) + ".")
    if articles:
        lines += ["", "Tekshirish uchun eng yaqin manbalar:"]
        for a in articles[:3]:
            lines.append(f"• {a.document_name}, {a.heading.text}")
            lines.append(f"  {a.heading.link}")
    return "\n".join(lines)


def format_historical(result: SearchResult) -> str:
    d = result.plan.historical_date
    when = {"year": f"{d.year}-yil", "month": f"{d.year}-yil {d.month}-oy"}.get(result.plan.historical_precision or "", d.isoformat())
    return (
        f"Siz {when} holatidagi normani so'rayapsiz. Bu davr uchun hujjat versiyasi hali tizimga yuklanmagan, "
        "joriy matn bilan javob berish esa noto'g'ri bo'lishi mumkin. Joriy holat bo'yicha so'rasangiz, javob beraman."
    )


async def answer_question(
    conn: asyncpg.Connection,
    llm: LLM,
    question: str,
    today: date,
    *,
    use_rewrite: bool = True,
    request_id: str | None = None,
) -> FinalAnswer:
    started = time.monotonic()
    rid = request_id or str(uuid.uuid4())
    usage = Usage()

    def done(**kw) -> FinalAnswer:
        fa = FinalAnswer(request_id=rid, usage=usage, **kw)
        fa.processing_ms = int((time.monotonic() - started) * 1000)
        log.info("answer status=%s rounds=%d sources=%d citations=%d rejected=%d ms=%d",
                 fa.status, fa.rounds, len(fa.source_articles), len(fa.citations),
                 len(fa.rejected_source_ids), fa.processing_ms)
        return fa

    result = await retrieve(conn, question, today, limit=MAX_SOURCES)
    queries = [question]

    if result.status == "needs_clarification":
        return done(status="needs_clarification", text=CLARIFY_TEXT)
    if result.status == "historical_unavailable":
        return done(status="historical_unavailable", text=format_historical(result))

    try:
        if result.direct_article is not None:
            articles = [article_to_source(result.direct_article)]
        else:
            groups = [result.hits]
            if use_rewrite:
                extra = await asyncio.to_thread(llm.rewrite_queries, question, usage)
                queries += extra
                for q in extra:
                    groups.append(await _search_text(conn, q, today, result.plan.lex_ids))
            hits = _merge_hits(groups, MAX_SOURCES)
            articles = await _articles_from_hits(conn, hits)
        if not articles:
            return done(status="not_found", text=format_insufficient([], []), search_queries=queries)

        rounds = 0
        note = None
        retried_citations = False
        validated: ValidatedAnswer | None = None
        rejected: list[str] = []
        removed: list[str] = []
        while True:
            # Sinxron SDK chaqiruvi alohida oqimda — bot boshqa foydalanuvchilarni kutdirmaydi.
            output = await asyncio.to_thread(llm.answer, render_user_message(question, articles, today, note), usage)
            validated = validate_answer(output, articles)
            rejected += validated.rejected_source_ids
            removed += validated.removed_urls

            if validated.needs_more and rounds < MAX_EXTRA_ROUNDS:
                present = {(a.lex_id, a.modda_raqami) for a in articles}
                new_hits: list[ArticleHit] = []
                for q in validated.needs_more[:3]:
                    queries.append(q)
                    for h in await _search_text(conn, q, today, None):
                        if (h.lex_id, h.modda_raqami) not in present and len(new_hits) < EXTRA_PER_ROUND:
                            present.add((h.lex_id, h.modda_raqami))
                            new_hits.append(h)
                rounds += 1
                if new_hits:
                    articles += await _articles_from_hits(conn, new_hits)
                    note = "So'rovingiz bo'yicha qo'shimcha manbalar qo'shildi."
                    continue
                break  # yangi manba topilmadi — qayta so'rashdan foyda yo'q

            if not validated.has_valid_citations and not validated.needs_more and not retried_citations:
                retried_citations = True
                note = ("Oldingi javobda iqtiboslar yaroqsiz edi. Faqat <element id> qiymatlarini source_id sifatida "
                        "ishlat; manba bo'lmasa needs_more ni to'ldir.")
                continue
            break
    except LLMError as exc:
        log.error("answer llm_error type=%s msg=%s", type(exc).__name__, exc)
        return done(status="error", text=ERROR_TEXT, search_queries=queries)

    common = dict(
        source_articles=articles, rounds=rounds, rejected_source_ids=rejected, removed_urls=removed,
        needs_more=validated.needs_more, search_queries=queries, confidence=validated.confidence,
    )
    if validated.needs_more or not validated.has_valid_citations:
        return done(status="insufficient", text=format_insufficient(articles, validated.needs_more), **common)
    return done(status="answered", text=format_answer(validated), citations=validated.citations, **common)
