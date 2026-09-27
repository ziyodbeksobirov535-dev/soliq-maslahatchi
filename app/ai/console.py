"""PHASE 4 konsol testi: 5 savol → to'liq zanjir (retrieval → Claude → citation validation).

    python -m app.ai.console                    # 5 ta savol, jonli Claude (ANTHROPIC_API_KEY kerak)
    python -m app.ai.console "savol matni"      # bitta savol
    python -m app.ai.console --no-llm           # Claude'siz: faqat retrieval va kontekst hajmi

Baza: SUPABASE_DB_URL (Postgres DSN). Natija `docs/phase4_console_report.md` ga ham yoziladi.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from app.ai.client import ClaudeLLM
from app.ai.prompts import SYSTEM_PROMPT, render_user_message
from app.config import get_settings
from app.database.connection import connect
from app.retrieval.search import retrieve
from app.services.answer import MAX_SOURCES, _articles_from_hits, answer_question
from app.utils.logging import request_context, setup_logging

QUESTIONS = (
    "Aylanma solig'idan QQSga qachon o'tish kerak?",
    "Norezidentga to'lovda qanday soliq majburiyati bor?",
    "Soliq imtiyozidan foydalanish uchun qanday shartlar bor?",
    "Importda bojxona to'lovi qanday aniqlanadi?",
    "Buxgalteriya hujjatini qancha vaqt saqlash kerak?",
)
REPORT = Path(__file__).resolve().parents[2] / "docs" / "phase4_console_report.md"


async def run_no_llm(dsn: str, questions: list[str], today: date) -> list[dict]:
    conn = await connect(dsn)
    out = []
    try:
        for q in questions:
            result = await retrieve(conn, q, today, limit=MAX_SOURCES)
            articles = await _articles_from_hits(conn, result.hits) if result.hits else []
            msg = render_user_message(q, articles, today)
            out.append({
                "question": q, "status": result.status,
                "articles": [f"{a.lex_id} {a.heading.text[:70]}" for a in articles],
                "context_chars": len(msg), "system_chars": len(SYSTEM_PROMPT),
            })
    finally:
        await conn.close()
    return out


async def run_llm(dsn: str, questions: list[str], today: date) -> list[dict]:
    settings = get_settings()
    llm = ClaudeLLM(settings)
    conn = await connect(dsn)
    out = []
    try:
        for q in questions:
            with request_context() as rid:
                fa = await answer_question(conn, llm, q, today, request_id=rid)
            out.append({
                "question": q, "status": fa.status, "confidence": fa.confidence, "rounds": fa.rounds,
                "search_queries": fa.search_queries,
                "sources": [f"{a.lex_id} {a.heading.text[:70]}" for a in fa.source_articles],
                "citations": [{"source_id": c.source.source_id, "link": c.source.link, "claim": c.claim} for c in fa.citations],
                "rejected_source_ids": fa.rejected_source_ids, "removed_urls": fa.removed_urls,
                "needs_more": fa.needs_more,
                "usage": {"model": fa.usage.model, "input": fa.usage.input_tokens, "output": fa.usage.output_tokens,
                          "cache_read": fa.usage.cache_read_tokens, "cache_write": fa.usage.cache_creation_tokens},
                "processing_ms": fa.processing_ms, "request_id": fa.request_id, "text": fa.text,
            })
    finally:
        await conn.close()
    return out


def write_report(rows: list[dict], live: bool) -> None:
    lines = [f"# PHASE 4 konsol testi ({'jonli Claude' if live else 'Claude’siz'})", ""]
    for i, r in enumerate(rows, 1):
        lines += [f"## {i}. {r['question']}", "", "```json", json.dumps({k: v for k, v in r.items() if k != "text"},
                  ensure_ascii=False, indent=2), "```", ""]
        if r.get("text"):
            lines += ["Javob:", "", r["text"], ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    settings.require("supabase_db_url")
    dsn = settings.supabase_db_url.get_secret_value()
    questions = [args.question] if args.question else list(QUESTIONS)
    today = date.today()
    rows = asyncio.run(run_no_llm(dsn, questions, today) if args.no_llm else run_llm(dsn, questions, today))
    for r in rows:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    write_report(rows, live=not args.no_llm)
    print(f"\nHisobot: {REPORT}")


if __name__ == "__main__":
    main()
