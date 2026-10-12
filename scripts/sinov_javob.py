"""Savol-javobni API kalitsiz sinash: botning qidiruvi va tekshiruvi, javobni esa tashqi model (masalan, Claude Code
sessiyasidagi Claude) yozadi.

    1) python scripts/sinov_javob.py kontekst "QQS stavkasi qancha?"
       → botning qidiruvi (imlo, kirill/rus, davomiy savol yo'q) va Claude'ga beriladigan xabar
         .cache/sinov/kontekst.txt ga yoziladi; ekranga manbalar ro'yxati.
    2) Model kontekst bo'yicha AnswerOutput JSON yozadi: .cache/sinov/javob.json
       {"answer_markdown": "...", "citations": [{"source_id": "EL-123", "claim": "..."}],
        "needs_more": [], "confidence": "high"}
    3) python scripts/sinov_javob.py javob "QQS stavkasi qancha?"
       → botning iqtibos tekshiruvi (validate_answer) va Telegram formatidagi yakuniy javob.

Bazaga yozmaydi (suhbatlar jurnali yo'q). Fast-model so'rov kengaytirish (rewrite_queries) ishlatilmaydi.
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
    article_to_source,
    format_answer,
)

OUT = Path(__file__).resolve().parents[1] / ".cache" / "sinov"


async def sources(conn, question: str):
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    result = await retrieve(conn, question, today, limit=MAX_SOURCES)
    if result.direct_article is not None:
        articles = [article_to_source(result.direct_article)]
    else:
        articles = await _articles_from_hits(conn, result.hits)
    return result, articles, today


def plain(html: str) -> str:
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2 (\1)", html)
    return re.sub(r"</?(b|i|code)>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


async def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("kontekst", "javob"):
        raise SystemExit(__doc__)
    mode, question = sys.argv[1], sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    conn = await connect(get_settings().supabase_db_url.get_secret_value())
    try:
        result, articles, today = await sources(conn, question)
    finally:
        await conn.close()

    if mode == "kontekst":
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
