"""Savol-javobni API kalitsiz sinash: botning qidiruvi va tekshiruvi, javobni esa tashqi model (masalan, Claude Code
sessiyasidagi Claude) yozadi.

    1) python scripts/sinov_javob.py kontekst "QQS stavkasi qancha?" ["qo'shimcha so'rov" ...]
       (qo'shimcha so'rovlar — botdagi fast model `rewrite_queries` o'rnida, 2–4 ta rasmiy qidiruv so'rovi;
        `--kerak q1 q2 ...` dan keyingilari — model `needs_more` qaytarganda botdagi qo'shimcha qidiruv raundi:
        har biri bo'yicha yangi manbalar, raundga ko'pi bilan 3 ta; ikkinchi `--kerak` — ikkinchi raund, botdagidek
        ko'pi bilan 2 raund)
       → botning qidiruvi (imlo, kirill/rus, davomiy savol yo'q) va Claude'ga beriladigan xabar
         .cache/sinov/kontekst.txt ga yoziladi; ekranga manbalar ro'yxati.
    2) Model kontekst bo'yicha AnswerOutput JSON yozadi: .cache/sinov/javob.json
       {"answer_markdown": "...", "citations": [{"source_id": "EL-123", "claim": "..."}],
        "needs_more": [], "confidence": "high"}
    3) python scripts/sinov_javob.py javob "QQS stavkasi qancha?" ["qo'shimcha so'rov" ...]  (1-qadamdagidek)
       → botning iqtibos tekshiruvi (validate_answer) va Telegram formatidagi yakuniy javob.

Bazaga yozmaydi (suhbatlar jurnali yo'q). Qo'shimcha so'rovlar bo'yicha natijalar botdagidek birlashtiriladi.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.prompts import render_user_message  # noqa: E402
from app.ai.schemas import AnswerOutput  # noqa: E402
from app.ai.validation import validate_answer  # noqa: E402
from app.bot.formatting import format_final_answer  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database.connection import connect  # noqa: E402
from app.retrieval.search import retrieve  # noqa: E402
from app.services.answer import (  # noqa: E402
    MAX_SOURCES,
    FinalAnswer,
    _articles_from_hits,
    MAX_EXTRA_ROUNDS,
    _merge_hits,
    _search_text,
    article_to_source,
    format_answer,
    benefit_sources,
    knowledge_sources,
    referenced_sources,
    round_sources,
)

OUT = Path(__file__).resolve().parents[1] / ".cache" / "sinov"


async def sources(conn, question: str, extra: list[str], rounds: list[list[str]] | None = None):
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    result = await retrieve(conn, question, today, limit=MAX_SOURCES)
    if result.direct_article is not None:
        articles = [article_to_source(result.direct_article)]
        articles += await referenced_sources(conn, articles, [])
    else:
        groups = [result.hits] + [await _search_text(conn, q, today, result.plan.lex_ids) for q in extra]
        hits = _merge_hits(groups, MAX_SOURCES)
        articles = await _articles_from_hits(conn, hits)
        articles += await referenced_sources(conn, articles, hits)  # botdagidek: havolalar zanjiri
        articles += await benefit_sources(conn, result.plan, today, articles)  # imtiyoz savoli: ro'yxatdan
        articles += await knowledge_sources(conn, result.plan, articles)  # skill bilimlari yo'naltirgan
        for needs_more in (rounds or [])[:MAX_EXTRA_ROUNDS]:  # botdagidek: yangi birliklar va bilim manbalari
            articles += await round_sources(conn, needs_more, articles, today)
    return result, articles, today


def plain(html: str) -> str:
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2 (\1)", html)
    return re.sub(r"</?(b|i|code)>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


async def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("kontekst", "javob"):
        raise SystemExit(__doc__)
    mode, question, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    parts: list[list[str]] = [[]]  # birinchisi — qo'shimcha so'rovlar, keyingilari — needs_more raundlari
    for arg in rest:
        if arg == "--kerak":
            parts.append([])
        else:
            parts[-1].append(arg)
    extra, rounds = parts[0], parts[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    conn = await connect(get_settings().supabase_db_url.get_secret_value())
    try:
        result, articles, today = await sources(conn, question, extra, rounds)
    finally:
        await conn.close()

    if mode == "kontekst":
        if result.status == "ok" and not articles:
            result.status = "not_found"
        print(f"holat: {result.status}; til: {result.plan.language}; imlo: {result.corrections or '-'}; "
              f"qidiruv so'zlari: {result.plan.terms}")
        for a in articles:
            print(f"  [{a.document_name[:50]}] {a.title[:80]} — elementlar: "
                  f"{', '.join(e.source_id for e in a.all_elements())[:120]}")
        if result.status in ("needs_clarification", "historical_unavailable") or not articles:
            print("Bot bu holatda Claude'ni chaqirmaydi (aniqlashtirish/tarixiy/topilmadi).")
            return
        (OUT / "kontekst.txt").write_text(render_user_message(question, articles, today), encoding="utf-8")
        print(f"kontekst: {OUT / 'kontekst.txt'}")
        return

    output = AnswerOutput.model_validate_json((OUT / "javob.json").read_text(encoding="utf-8"))
    validated = validate_answer(output, articles)
    print(f"iqtiboslar: {len(validated.citations)} to'g'ri, rad etilgan: {validated.rejected_source_ids or '-'}, "
          f"olib tashlangan URL: {validated.removed_urls or '-'}")
    status = "answered" if validated.has_valid_citations and not validated.needs_more else "insufficient"
    fa = FinalAnswer(status=status, text=format_answer(validated), request_id="sinov",
                     citations=validated.citations, source_articles=articles,
                     corrections=result.corrections, language=result.plan.language)
    print("\n--- Telegram'da ko'rinishi ---\n")
    print(plain(format_final_answer(fa)))
    (OUT / "javob.html").write_text(format_final_answer(fa), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
