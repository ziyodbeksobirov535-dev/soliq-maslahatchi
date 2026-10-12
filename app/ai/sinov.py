"""API kalitisiz model sinovi: botning aynan o'sha promptini faylga yig'ish va model javobini tekshirish.

Claude API chaqirilmaydi. Prompt qo'lda istalgan modelga beriladi (Claude Code, claude.ai), javob JSON'i
faylga saqlanadi va bot qanday ko'rsatishi (citation validation + Telegram formati) tekshiriladi.

    python -m app.ai.sinov tayyorla "savol"                       # sinov/<NN>-<savol>/prompt.txt
    python -m app.ai.sinov tayyorla                               # console.py dagi 5 ta savol
    python -m app.ai.sinov tayyorla "savol" --qidiruv "so'rov"    # fast model o'rniga qo'shimcha qidiruv
    python -m app.ai.sinov tayyorla "savol" --profil "rejim=aylanma soliq" --profil "soha=savdo"
    python -m app.ai.sinov tekshir sinov/01-.../javob-opus.json   # bot ko'rsatadigan javob + tahlil
    python -m app.ai.sinov tekshir --model haiku                  # oxirgi sinov, javob clipboard'dan

Bitta savol tayyorlanganda prompt clipboard'ga nusxalanadi (macOS: pbcopy) — modelga Cmd+V bilan bering,
javobini nusxalab `tekshir --model <nom>` ni ishga tushiring.

Farqi: botda qidiruv so'rovlarini fast model qo'shadi (bu yerda `--qidiruv` bilan qo'lda), needs_more
bo'lsa bot o'zi qayta qidiradi (bu yerda `tekshir` tayyor buyruqni ko'rsatadi). Claude Code va claude.ai
o'z system prompti bilan ishlaydi — natija API'dagiga yaqin, lekin aynan bir xil emas.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from app.ai.console import QUESTIONS
from app.ai.prompts import SYSTEM_PROMPT, SourceArticle, SourceElement, render_user_message
from app.ai.schemas import AnswerOutput
from app.ai.validation import validate_answer
from app.config import get_settings
from app.database.connection import connect
from app.retrieval.search import retrieve
from app.services.answer import (
    CLARIFY_TEXT,
    MAX_SOURCES,
    _articles_from_hits,
    _merge_hits,
    _search_text,
    article_to_source,
    format_answer,
    format_historical,
    format_insufficient,
)
from app.utils.logging import setup_logging

SINOV_DIR = Path(__file__).resolve().parents[2] / "sinov"
PROMPT_FILE = "prompt.txt"
SOURCES_FILE = "manbalar.json"

FORMAT_INSTRUCTION = """Javobni FAQAT bitta JSON obyekt sifatida qaytar — undan oldin ham, keyin ham matn yozma.
JSON quyidagi sxemaga mos bo'lsin:
"""


def slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().replace("ʻ", "").replace("'", "").replace("’", ""))
    return s.strip("-")[:limit].rstrip("-") or "savol"


def parse_profile(items: list[str]) -> dict | None:
    profile = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key.strip() not in ("soha", "rejim", "shakl"):
            raise SystemExit(f"--profil noto'g'ri: {item!r} (namuna: rejim=aylanma soliq; maydonlar: soha, rejim, shakl)")
        profile[key.strip()] = value.strip()
    return profile or None


def build_prompt(user_message: str) -> str:
    schema = json.dumps(AnswerOutput.model_json_schema(), ensure_ascii=False, indent=2)
    return (f"<tizim_korsatmasi>\n{SYSTEM_PROMPT.strip()}\n</tizim_korsatmasi>\n\n"
            f"<javob_formati>\n{FORMAT_INSTRUCTION}{schema}\n</javob_formati>\n\n{user_message}\n")


def articles_to_json(articles: list[SourceArticle]) -> list[dict]:
    return [asdict(a) for a in articles]


def articles_from_json(data: list[dict]) -> list[SourceArticle]:
    out = []
    for d in data:
        d = dict(d)
        d["heading"] = SourceElement(**d["heading"])
        d["elements"] = [SourceElement(**e) for e in d["elements"]]
        out.append(SourceArticle(**d))
    return out


def copy_to_clipboard(text: str) -> bool:
    if not shutil.which("pbcopy"):
        return False
    subprocess.run(["pbcopy"], input=text, text=True, check=True)
    return True


def read_clipboard() -> str:
    if not shutil.which("pbpaste"):
        raise SystemExit("Clipboard o'qilmadi (pbpaste yo'q) — javobni faylga saqlab, yo'lini bering.")
    return subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout


def latest_dir() -> Path:
    dirs = sorted((p for p in SINOV_DIR.glob("*") if (p / SOURCES_FILE).exists()), key=lambda p: p.stat().st_mtime)
    if not dirs:
        raise SystemExit("Hali sinov yo'q — avval: python -m app.ai.sinov tayyorla \"savol\"")
    return dirs[-1]


def next_dir(question: str) -> Path:
    nums = [int(m.group(1)) for p in SINOV_DIR.glob("*") if (m := re.match(r"(\d+)-", p.name))]
    return SINOV_DIR / f"{max(nums, default=0) + 1:02d}-{slug(question)}"


async def collect(dsn: str, question: str, extra_queries: list[str], today: date) -> tuple[str, list[SourceArticle]]:
    """answer_question'ning Claude'gacha bo'lgan qismi. Qaytaradi: (holat, manbalar)."""
    conn = await connect(dsn)
    try:
        result = await retrieve(conn, question, today, limit=MAX_SOURCES)
        if result.status == "needs_clarification":
            return "needs_clarification", []
        if result.status == "historical_unavailable":
            print(format_historical(result))
            return "historical_unavailable", []
        if result.direct_article is not None:
            return "ok", [article_to_source(result.direct_article)]
        groups = [result.hits]
        for q in extra_queries:
            groups.append(await _search_text(conn, q, today, result.plan.lex_ids))
        articles = await _articles_from_hits(conn, _merge_hits(groups, MAX_SOURCES))
        return ("ok" if articles else "not_found"), articles
    finally:
        await conn.close()


def cmd_tayyorla(args: argparse.Namespace) -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    settings.require("supabase_db_url")
    dsn = settings.supabase_db_url.get_secret_value()
    profile = parse_profile(args.profil)
    today = date.today()

    questions = args.savol or list(QUESTIONS)
    for question in questions:
        status, articles = asyncio.run(collect(dsn, question, args.qidiruv, today))
        print(f"\n■ {question}")
        if status == "needs_clarification":
            print(f"  Bot Claude'ni chaqirmaydi, aniqlashtirish so'raydi:\n  {CLARIFY_TEXT}")
            continue
        if status == "historical_unavailable":
            print("  Bot Claude'ni chaqirmaydi (tarixiy versiya yo'q).")
            continue
        if status == "not_found":
            print("  Manba topilmadi — bot Claude'ni chaqirmaydi. --qidiruv bilan boshqa atamani sinang.")
            continue

        out = next_dir(question)
        out.mkdir(parents=True)
        prompt = build_prompt(render_user_message(question, articles, today, profile=profile))
        (out / PROMPT_FILE).write_text(prompt, encoding="utf-8")
        (out / SOURCES_FILE).write_text(json.dumps(
            {"savol": question, "sana": today.isoformat(), "profil": profile, "qidiruv": args.qidiruv,
             "manbalar": articles_to_json(articles)}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Manbalar ({len(articles)}):")
        for a in articles:
            print(f"   - {a.document_name[:60]}, {a.title[:70]} [{a.document_status}]")
        print(f"  Prompt: {out / PROMPT_FILE} ({len(prompt):,} belgi)")
        if len(questions) == 1 and copy_to_clipboard(prompt):
            print("\n  ✅ Prompt clipboard'ga nusxalandi. claude.ai'da yangi chat oching, Cmd+V → yuboring.")
            print("     Model javobini nusxalang (Copy tugmasi) va bu yerda ishga tushiring:")
            print("     .venv/bin/python -m app.ai.sinov tekshir --model <model-nomi>")
        else:
            print(f"  Javobni saqlang: {out}/javob-<model>.json")


def extract_json(text: str) -> dict:
    """Model javobidan JSON obyektni ajratadi (```json bloklari va atrofdagi matnga chidamli)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("Javobda JSON obyekt topilmadi")
    return json.loads(candidate)


def check(answer_text: str, articles: list[SourceArticle]) -> tuple[str, list[str]]:
    """Bot ko'rsatadigan matn va tahlil qatorlari."""
    output = AnswerOutput.model_validate(extract_json(answer_text))
    v = validate_answer(output, articles)
    notes = [f"confidence: {v.confidence}", f"to'g'ri iqtiboslar: {len(v.citations)} / {len(output.citations)}"]
    if v.rejected_source_ids:
        notes.append(f"RAD ETILGAN source_id (kontekstda yo'q — uydirma): {', '.join(v.rejected_source_ids)}")
    if v.removed_urls:
        notes.append(f"javobdan olib tashlangan URL'lar: {len(v.removed_urls)}")
    if v.needs_more:
        notes.append("needs_more: " + "; ".join(v.needs_more))
    if v.needs_more:
        status = "insufficient (botda yana qidiradi, ko'pi bilan 2 round)"
        text = format_insufficient(articles, v.needs_more)
    elif not v.has_valid_citations:
        status = "insufficient (botda iqtibos uchun bir marta qayta so'raydi)"
        text = format_insufficient(articles, [])
    else:
        status = "answered"
        text = format_answer(v)
    notes.insert(0, f"holat: {status}")
    return text, notes


def cmd_tekshir(args: argparse.Namespace) -> None:
    target = Path(args.javob) if args.javob else latest_dir()
    if target.is_dir():
        clipboard = read_clipboard()
        if "<tizim_korsatmasi>" in clipboard:
            raise SystemExit("Clipboard'da hali promptning o'zi turibdi — model javobi nusxalanmagan.\n"
                             "claude.ai'da javob ostidagi Copy tugmasini bosing va buyruqni qayta ishga tushiring.")
        answer_path = target / f"javob-{slug(args.model)}.json"
        answer_path.write_text(clipboard, encoding="utf-8")
        print(f"Javob clipboard'dan olindi → {answer_path}\n")
    else:
        answer_path = target
    meta = json.loads((answer_path.parent / SOURCES_FILE).read_text(encoding="utf-8"))
    articles = articles_from_json(meta["manbalar"])
    try:
        text, notes = check(answer_path.read_text(encoding="utf-8"), articles)
    except (ValueError, ValidationError) as exc:
        raise SystemExit(f"Javob sxemaga mos emas — botda bu 'Structured output olinmadi' xatosi bo'lardi:\n{exc}")

    print("TAHLIL\n" + "\n".join(f"  {n}" for n in notes))
    print("\nBOT TELEGRAM'DA KO'RSATADIGAN JAVOB\n" + "─" * 60 + f"\n{text}\n" + "─" * 60)
    needs_more = [n for n in notes if n.startswith("needs_more: ")]
    if needs_more:
        extra = " ".join(f'--qidiruv "{q}"' for q in needs_more[0].removeprefix("needs_more: ").split("; ")[:3])
        print(f'\nBotdagi kabi qayta qidirish:\n  python -m app.ai.sinov tayyorla "{meta["savol"]}" {extra}')

    report = answer_path.with_name(f"natija-{answer_path.stem.removeprefix('javob-')}.md")
    report.write_text(f"# {meta['savol']}\n\nJavob fayli: `{answer_path.name}`\n\n## Tahlil\n\n"
                      + "\n".join(f"- {n}" for n in notes) + f"\n\n## Bot javobi\n\n{text}\n", encoding="utf-8")
    print(f"\nHisobot: {report}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.ai.sinov", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tayyorla", help="savol(lar) uchun prompt fayli")
    p.add_argument("savol", nargs="*")
    p.add_argument("--qidiruv", action="append", default=[], help="qo'shimcha qidiruv so'rovi (bir necha marta)")
    p.add_argument("--profil", action="append", default=[], help="soha=… / rejim=… / shakl=…")
    p.set_defaults(func=cmd_tayyorla)
    t = sub.add_parser("tekshir", help="model javobini bot qoidalari bilan tekshirish")
    t.add_argument("javob", nargs="?", help="javob fayli yoki sinov papkasi (bo'lmasa — oxirgi sinov); "
                                             "papka berilsa javob clipboard'dan olinadi")
    t.add_argument("--model", default="model", help="javob qaysi modelniki (fayl nomi uchun): haiku, sonnet, opus")
    t.set_defaults(func=cmd_tekshir)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
