"""Skill bilimlari (spec 19) — yo'naltiruvchi: mos bo'limdagi ishoralar bo'yicha Lex.uz manbalari kontekstga.

    "QQS to'lovchi bo'lish chegarasi" → bilimlar-bazasi.md bo'limi → "461-modda", "PF-..." → modda/farmon bo'limi

- Bo'lim matni javobga kirmaydi (Lex.uz ustun, spec 2): faqat undagi "N-modda" (Soliq kodeksi) va "PF-N"/"PQ-N"
  (Prezident hujjati) ishoralari olinadi; hujjat bazada bo'lsa — savolga eng mos bo'limi.
- Bo'lim savolning mazmunli so'zlarining kamida yarmini (va kamida 2 tasini, agar 2+ bo'lsa) qamrashi kerak.
"""

from __future__ import annotations

import math
import re

import asyncpg

from app.retrieval.articles import Article, get_article, get_section, normalize_article_number
from app.retrieval.query import QueryPlan, normalize

SK = "-4674902"
MAX_RECORDS = 3
MAX_ARTICLES = 2
_ACT_RE = re.compile(r"\b(PF|PQ)-(\d{1,4})\b")


def terms(plan: QueryPlan) -> list[str]:
    out = []
    for t in plan.terms:
        if t == "soli":
            continue
        forms = [t, *plan.variants.get(t, [])]
        out.append("(" + " | ".join(f"{f}:*" for f in forms) + ")" if len(forms) > 1 else f"{t}:*")
    return out


def references(text: str) -> list[tuple[str, str]]:
    """Matndagi ishoralar: [("modda", "461"), ("PF", "153")] — tartib bo'yicha, takrorsiz. Bob oralig'i
    ("1-15-modda", "30-60-modda") — ishora emas, tashlanadi; qo'shni moddalar ("339-340-modda") qoladi."""
    found: list[tuple[int, str, str]] = []
    for m in re.finditer(r"(\d{1,3}[¹²³⁴⁵⁶⁷⁸⁹]?(?:\s*(?:,|va|—|-)\s*\d{1,3}[¹²³⁴⁵⁶⁷⁸⁹]?)*)-modda", text):
        span = re.fullmatch(r"(\d{1,3})\s*[-—]\s*(\d{1,3})", m.group(1))
        if span and int(span.group(2)) - int(span.group(1)) > 1:
            continue
        for num in re.findall(r"\d{1,3}[¹²³⁴⁵⁶⁷⁸⁹]?", m.group(1)):
            found.append((m.start(), "modda", num))
    for m in _ACT_RE.finditer(text):
        found.append((m.start(), m.group(1), m.group(2)))
    out: list[tuple[str, str]] = []
    for _, kind, num in sorted(found):
        if (kind, num) not in out:
            out.append((kind, num))
    return out


def _chunks(text: str) -> list[str]:
    """Xatboshilar va ro'yxat bandlari (Markdown'da bitta gap bir necha qatorga bo'lingan bo'ladi)."""
    chunks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            chunks.append("")
        elif re.match(r"^([-*•]|\d+[.)])\s", stripped) or not chunks or not chunks[-1]:
            chunks.append(stripped)
        else:
            chunks[-1] += " " + stripped
    return [c for c in chunks if c]


def relevant_references(plan: QueryPlan, topic: str, text: str) -> list[tuple[str, str]]:
    """Bo'limdagi ishoralar faqat sarlavhadan va savol so'zi uchragan qatorlardan (bo'lim boshqa mavzudagi
    qatorlari kontekstga shovqin qo'shmasin: "Asosiy stavkalar" bo'limida QQS qatori ≠ norezident qatori)."""
    stems = [[t, *plan.variants.get(t, [])] for t in plan.terms if t != "soli"]
    lines = [topic] + [chunk for chunk in _chunks(text)
                       if any(any(w.startswith(f) for f in forms for w in normalize(chunk).split()) for forms in stems)]
    out: list[tuple[str, str]] = []
    for line in lines:
        out += [r for r in references(line) if r not in out]
    return out


async def matching_records(conn: asyncpg.Connection, plan: QueryPlan, limit: int = MAX_RECORDS) -> list[asyncpg.Record]:
    ts = terms(plan)
    if not ts:
        return []
    need = max(min(2, len(ts)), math.ceil(len(ts) / 2))
    try:
        return await conn.fetch(
            """
            WITH t AS (SELECT to_tsquery('simple', q) AS q FROM unnest($1::text[]) AS q),
                 b AS (
                SELECT b.record_key, b.topic, b.text, (SELECT count(*) FROM t WHERE b.search_vector @@ t.q) AS hits
                FROM bilimlar b
                WHERE b.turi = 'bilim' AND b.search_vector @@ to_tsquery('simple', array_to_string($1::text[], ' | ')))
            SELECT * FROM b WHERE hits >= $2 ORDER BY hits DESC, record_key LIMIT $3
            """,
            ts, need, limit,
        )
    except asyncpg.UndefinedColumnError:  # 013 qo'llanmagan baza
        return []


async def _act_lex_id(conn: asyncpg.Connection, kind: str, number: str) -> str | None:
    full = f"{kind}-{number}"
    lex_id = await conn.fetchval(
        "SELECT lex_id FROM topilgan_hujjatlar WHERE number = $1 UNION SELECT lex_id FROM yangiliklar WHERE number = $1 "
        "LIMIT 1", full)
    if lex_id is None and kind == "PF":
        lex_id = await conn.fetchval("SELECT lex_id FROM hujjatlar WHERE type IN ('Указ', 'Farmon') AND number = $1",
                                     number)
    if lex_id and await conn.fetchval("SELECT 1 FROM hujjatlar WHERE lex_id = $1", lex_id):
        return lex_id
    return None


async def knowledge_articles(conn: asyncpg.Connection, plan: QueryPlan, present: set[tuple[str, str]],
                             limit: int = MAX_ARTICLES) -> list[Article]:
    """Mos bilim bo'limlari ishora qilgan moddalar/hujjat bo'limlari (kontekstda yo'q, bazada bor)."""
    from app.retrieval.search import search_articles  # aylanma importdan qochish

    out: list[Article] = []
    for record in await matching_records(conn, plan):
        for kind, num in relevant_references(plan, record["topic"], record["text"]):
            if len(out) >= limit:
                return out
            if kind == "modda":
                number = normalize_article_number(num)
                if not number or (SK, number) in present:
                    continue
                present.add((SK, number))
                article = await get_article(conn, number, SK)
            else:
                lex_id = await _act_lex_id(conn, kind, num)
                if lex_id is None or (lex_id, "") in present:
                    continue
                present.add((lex_id, ""))
                scoped = QueryPlan(question=plan.question, normalized=plan.normalized, terms=plan.terms,
                                   variants=plan.variants, lex_ids=[lex_id])
                hits = await search_articles(conn, scoped, limit=1)
                if not hits:
                    continue
                h = hits[0]
                article = (await get_article(conn, h.modda_raqami, lex_id) if h.modda_raqami
                           else await get_section(conn, lex_id, h.birlik))
            if article is not None:
                out.append(article)
    return out
