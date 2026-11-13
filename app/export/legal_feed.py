"""Faqat o'qiydigan eksport: `soliq.legal-feed/1.0` (Marketolog AI uchun; INTEGRATION_HANDOFF.md §11–12).

    python -m app.export.legal_feed --since 7d --out <marketolog>/exchange/inbox/
    python -m app.export.legal_feed --since 24h --out /tmp/x --dry-run     # fayl yozmaydi, faqat hisob

- Bitta ulanish, `default_transaction_read_only=on`: bazaga hech narsa yozilmaydi (urinish xato beradi).
- Faqat ochiq huquqiy ma'lumot: `hujjatlar`, `elementlar`, `hujjat_versiyalari`, `ozgarishlar`, `yangiliklar`
  (+ `xabarlar.holat` — faqat `admin_approved`). Shaxsiy jadvallar, `xabarlar.matn`, AI, Telegram — yo'q.
- Hodisalar:
  - `news_item` — davr ichidagi relevant RSS hujjati: metadata, holat, tahrir va (matni bo'lsa) bandlari;
  - `provision_changed` — haftalik/qayta yuklashda aniqlangan band o'zgarishi (`ozgarishlar`).
  `status_changed`, `amended_by`, band darajasidagi kuchga kirish sanasi bazada yo'q — chiqarilmaydi / `null`.
- `event_id` = "slf1-" + sha256("soliq.legal-feed/1|type|lex_id|version_token|element_id|hash")[:32]
  ("-" — qiymat yo'q). Matn yoki tahrir o'zgarsa — yangi `event_id`.
- `event_revision`: shu `event_id` mazmuni (vaqt belgilari va `producer`dan tashqari — Marketolog
  `substantive_hash` bilan bir xil qoida) avvalgi eksportdagidan farq qilsa +1. Holat lokal faylda
  (`--state`, sukut `.cache/legal_feed_state.json`), fayllar muvaffaqiyatli yozilgandan keyingina yangilanadi.
- Fayl: `legal-feed-v1-<UTC>.jsonl` (katta bo'lsa `-pN` bo'laklar), oldin `<fayl>.sha256`, so'ng `.tmp` →
  `os.replace` (atomar). `evidence_text` aynan Lex.uz matni, `text_hash = sha256(evidence_text)`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import asyncpg

import lexuz
from app.config import get_settings
from app.utils.logging import setup_logging

log = logging.getLogger(__name__)

SCHEMA = "soliq.legal-feed/1.0"
EXPORTER_VERSION = "0.1.0"
STALE_DAYS = 8
MAX_PROVISIONS = 40  # news_item ichida (Marketolog chegarasi 200)
MAX_EVIDENCE_CHARS = 20_000  # Marketolog chegarasi; uzunroq band chiqarilmaydi (xesh tufayli kesib bo'lmaydi)
MAX_FILE_BYTES = 18 * 1024 * 1024  # Marketolog chegarasi 20 MB
VOLATILE_TOP = ("emitted_at", "producer", "retrieval")
VOLATILE_DOC = ("status_checked_at", "last_successful_load")
EVIDENCE_KINDS = ("article", "text", "table")
CHANGE_TYPES = {"qo'shilgan": "added", "o'zgargan": "changed", "o'chirilgan": "removed"}
APPROVED = ("tasdiqlandi", "yuborildi")
_SINCE_RE = re.compile(r"^(\d+)([dh])$")


def parse_since(value: str) -> timedelta:
    m = _SINCE_RE.match(value.strip())
    if not m:
        raise argparse.ArgumentTypeError("--since: masalan 7d yoki 24h")
    n = int(m.group(1))
    return timedelta(days=n) if m.group(2) == "d" else timedelta(hours=n)


def event_id(event_type: str, lex_id: str, version_token: str | None, element_id: str | None,
             hash_: str | None) -> str:
    key = "|".join(["soliq.legal-feed/1", event_type, lex_id, version_token or "-", element_id or "-", hash_ or "-"])
    return "slf1-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def substantive_hash(event: dict) -> str:
    """Mazmun xeshi — vaqt belgilari va ishlab chiqaruvchisiz (Marketolog `packets.substantive_hash` bilan bir xil)."""
    core = {k: v for k, v in event.items() if k not in VOLATILE_TOP and k != "event_revision"}
    if isinstance(core.get("document"), dict):
        core["document"] = {k: v for k, v in core["document"].items() if k not in VOLATILE_DOC}
    blob = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_url(lex_id: str) -> str:
    return f"https://lex.uz/docs/{lex_id}"


def element_link(lex_id: str, element_id: str) -> str:
    return f"{doc_url(lex_id)}#{element_id}"


# --- o'qish ------------------------------------------------------------------------------


async def _documents(conn: asyncpg.Connection, lex_ids: list[str]) -> dict[str, asyncpg.Record]:
    rows = await conn.fetch(
        """
        SELECT h.*, v.on_date AS version_on_date
        FROM hujjatlar h
        LEFT JOIN hujjat_versiyalari v ON v.document_id = h.id AND v.version_token = h.current_version
        WHERE h.lex_id = ANY($1::text[])
        """,
        lex_ids,
    )
    return {r["lex_id"]: r for r in rows}


async def _provisions(conn: asyncpg.Connection, document_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT element_id, kind, modda_raqami, birlik, birlik_nomi, element_path, text, text_hash,
               amendment_note, future_version
        FROM elementlar WHERE document_id = $1 AND kind = ANY($2::text[]) ORDER BY order_no
        """,
        document_id, list(EVIDENCE_KINDS),
    )


def document_block(lex_id: str, doc: asyncpg.Record | None, news: asyncpg.Record | None) -> dict:
    """Hujjat metadata — bazadagi hujjatdan; import qilinmagan yangilik bo'lsa RSS'dan (holat noma'lum)."""
    if doc is None:
        return {
            "lex_id": lex_id, "title": news["title"], "doc_type": news["doc_type"], "doc_form_raw": None,
            "number": news["number"], "adoption_date": _iso(news["adoption_date"]),
            "effective_date": _iso(news["effective_date"]), "repeal_date": None, "status": "noma'lum",
            "status_raw": None, "status_checked_at": None, "url": doc_url(lex_id), "version": None,
            "text_available": None, "last_successful_load": None,
        }
    token = doc["current_version"]
    vdate = doc["version_on_date"] or (lexuz.version_date(token) if token else None)
    version = None
    if token:
        version = {"token": token, "date": _iso(vdate),
                   "url": doc["source_url"] if doc["source_url"] and "ONDATE=" in doc["source_url"] else None,
                   "content_hash": doc["content_hash"]}
    return {
        "lex_id": lex_id, "title": doc["name"], "doc_type": news["doc_type"] if news else None,
        "doc_form_raw": doc["type"], "number": doc["number"], "adoption_date": _iso(doc["adoption_date"]),
        "effective_date": _iso(doc["effective_date"]), "repeal_date": _iso(doc["repeal_date"]),
        "status": doc["status"], "status_raw": doc["status_raw"], "status_checked_at": _iso(doc["status_checked_at"]),
        "url": doc_url(lex_id), "version": version, "text_available": doc["text_available"],
        "last_successful_load": _iso(doc["last_successful_load"]),
    }


def provision_block(lex_id: str, e, *, text: str | None = None, change: dict | None = None) -> dict | None:
    evidence = e["text"] if text is None else text
    if evidence is not None and len(evidence) > MAX_EVIDENCE_CHARS:
        return None
    article = e["modda_raqami"] if e is not None else None
    return {
        "element_id": e["element_id"],
        "kind": e["kind"],
        "unit": {"type": "article" if article else "section", "article_number": article,
                 "section_key": e["birlik"], "section_name": e["birlik_nomi"]},
        "path": e["element_path"] or None,
        "evidence_text": evidence,
        "text_hash": _sha(evidence) if evidence is not None else None,
        "link": element_link(lex_id, e["element_id"]),
        "amendment_note": e["amendment_note"],
        "amended_by": [],
        "future_version_token": e["future_version"],
        "provision_effective_date": None,
        "change": change,
    }


def flags_for(document: dict, provisions: list[dict], news: dict | None, now: datetime,
              renumbering: bool = False) -> list[str]:
    flags = set()
    status = document["status"]
    if status == "noma'lum":
        flags.add("status_unknown")
    elif status == "kuchga_kirmagan":
        flags.add("not_yet_effective")
    elif status == "kuchini_yoqotgan":
        flags.add("repealed")
    if document["text_available"] is False or (document["text_available"] is None and not provisions):
        flags.add("text_not_published")
    if any(p["future_version_token"] for p in provisions):
        flags.add("future_amendment_pending")
    if any(p["change"] and p["change"]["type"] == "removed" for p in provisions):
        flags.add("repealed")  # band joriy matndan chiqarilgan
    loaded = document["last_successful_load"]
    if loaded is None or now - datetime.fromisoformat(loaded) > timedelta(days=STALE_DAYS):
        flags.add("stale_source")
    if news:
        if news["relevance_method"] == "keyword":
            flags.add("keyword_relevance_only")
        if news["ai_summary"]:
            flags.add("ai_summary_unverified")
    if renumbering:
        flags.add("element_renumbering_possible")
    return sorted(flags)


def envelope(event_type: str, eid: str, document: dict, provisions: list[dict], news: dict | None,
             retrieved_at: str | None, now: datetime, commit: str | None, renumbering: bool = False,
             extra: dict | None = None) -> dict:
    event = {
        "schema": SCHEMA, "event_id": eid, "event_type": event_type, "event_revision": 1,
        "emitted_at": now.isoformat(),
        "producer": {"system": "soliq-maslahatchi", "commit": commit, "exporter_version": EXPORTER_VERSION},
        "document": document, "news": news, "provisions": provisions,
        "retrieval": {"retrieved_at": retrieved_at, "method": "db_snapshot", "query": None, "score": None},
        "uncertainty": {"flags": flags_for(document, provisions, news, now, renumbering)},
    }
    if extra:
        event.update(extra)
    return event


async def news_events(conn: asyncpg.Connection, since: datetime, now: datetime, commit: str | None) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT y.*, EXISTS (SELECT 1 FROM xabarlar x WHERE x.kalit = 'yangilik:' || y.lex_id
                            AND x.holat = ANY($2::text[])) AS admin_approved
        FROM yangiliklar y
        WHERE y.relevant AND coalesce(y.pub_date, y.created_at) >= $1
        ORDER BY coalesce(y.pub_date, y.created_at), y.lex_id
        """,
        since, list(APPROVED),
    )
    docs = await _documents(conn, [r["lex_id"] for r in rows])
    events = []
    for y in rows:
        doc = docs.get(y["lex_id"])
        document = document_block(y["lex_id"], doc, y)
        provisions, total = [], 0
        if doc is not None:
            elements = await _provisions(conn, doc["id"])
            total = len(elements)
            for e in elements:
                p = provision_block(y["lex_id"], e)
                if p is not None:
                    provisions.append(p)
                if len(provisions) >= MAX_PROVISIONS:
                    break
        news = {"pub_date": _iso(y["pub_date"]), "relevance_method": y["relevance_method"],
                "keyword_hits": list(y["keyword_hits"]), "topics": list(y["topics"]), "ai_summary": y["summary"],
                "admin_approved": y["admin_approved"]}
        version = document["version"] or {}
        eid = event_id("news_item", y["lex_id"], version.get("token"), None, version.get("content_hash"))
        retrieved = document["last_successful_load"] or _iso(y["updated_at"])
        events.append(envelope("news_item", eid, document, provisions, news, retrieved, now, commit,
                               extra={"provisions_total": total}))
    return events


async def change_events(conn: asyncpg.Connection, since: datetime, now: datetime, commit: str | None) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT o.id, o.element_id, o.change_type, o.old_hash, o.new_hash, o.old_text, o.new_text, o.detected_at,
               h.lex_id,
               e.element_id AS cur_element_id, e.kind, e.modda_raqami, e.birlik, e.birlik_nomi, e.element_path,
               e.text, e.amendment_note, e.future_version
        FROM ozgarishlar o
        JOIN hujjatlar h ON h.id = o.document_id
        LEFT JOIN elementlar e ON e.document_id = o.document_id AND e.element_id = o.element_id
        WHERE o.detected_at >= $1
        ORDER BY o.detected_at, o.id
        """,
        since,
    )
    docs = await _documents(conn, list({r["lex_id"] for r in rows}))
    # Bir hujjatda bir yangilashda ham qo'shilgan, ham chiqarilgan band — Lex.uz qayta raqamlagan bo'lishi mumkin
    kinds: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        kinds.setdefault((r["lex_id"], r["detected_at"].date().isoformat()), set()).add(r["change_type"])
    events = []
    for r in rows:
        doc = docs[r["lex_id"]]
        document = document_block(r["lex_id"], doc, None)
        ctype = CHANGE_TYPES[r["change_type"]]
        change = {"type": ctype, "old_hash": r["old_hash"], "new_hash": r["new_hash"], "old_text": r["old_text"],
                  "detected_at": _iso(r["detected_at"])}
        text = r["new_text"] if ctype != "removed" else r["old_text"]
        if text is None:
            continue
        e = {"element_id": r["element_id"], "kind": r["kind"] or "text", "modda_raqami": r["modda_raqami"],
             "birlik": r["birlik"], "birlik_nomi": r["birlik_nomi"], "element_path": r["element_path"],
             "text": text, "amendment_note": r["amendment_note"], "future_version": r["future_version"]}
        p = provision_block(r["lex_id"], e, change=change)
        if p is None:
            continue
        h = r["new_hash"] if ctype != "removed" else r["old_hash"]
        if p["text_hash"] != h:  # bazadagi xesh matnga mos emas — chiqarilmaydi
            log.warning("export skip change id=%s: hash mismatch", r["id"])
            continue
        version = document["version"] or {}
        eid = event_id("provision_changed", r["lex_id"], version.get("token"), r["element_id"], h)
        renum = {"qo'shilgan", "o'chirilgan"} <= kinds[(r["lex_id"], r["detected_at"].date().isoformat())]
        events.append(envelope("provision_changed", eid, document, [p], None,
                               document["last_successful_load"], now, commit, renumbering=renum))
    return events


# --- revision holati va fayl yozish -------------------------------------------------------


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def apply_revisions(events: list[dict], state: dict) -> dict:
    """Har event_id uchun: mazmun avvalgidan farq qilsa revision +1. Yangi holatni qaytaradi (hali saqlanmagan)."""
    new_state = dict(state)
    for ev in events:
        h = substantive_hash(ev)
        prev = state.get(ev["event_id"])
        if prev is None:
            rev = 1
        elif prev["hash"] == h:
            rev = prev["revision"]
        else:
            rev = prev["revision"] + 1
        ev["event_revision"] = rev
        new_state[ev["event_id"]] = {"revision": rev, "hash": h}
    return new_state


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_files(events: list[dict], out: Path, now: datetime) -> list[Path]:
    """JSONL bo'laklari (har biri ≤ MAX_FILE_BYTES); har biriga avval `.sha256`, keyin fayl (atomar)."""
    out.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(ev, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n" for ev in events]
    chunks: list[list[bytes]] = [[]]
    size = 0
    for line in lines:
        if chunks[-1] and size + len(line) > MAX_FILE_BYTES:
            chunks.append([])
            size = 0
        chunks[-1].append(line)
        size += len(line)
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths = []
    for i, chunk in enumerate(chunks, 1):
        name = f"legal-feed-v1-{stamp}" + (f"-p{i}" if len(chunks) > 1 else "") + ".jsonl"
        data = b"".join(chunk)
        path = out / name
        _atomic_write(path.with_name(name + ".sha256"), f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode())
        _atomic_write(path, data)
        paths.append(path)
    return paths


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True, cwd=Path(__file__).resolve().parents[2]).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


async def connect_readonly(dsn: str) -> asyncpg.Connection:
    """Faqat o'qiydigan ulanish: har qanday INSERT/UPDATE/DELETE server tomonida rad etiladi."""
    return await asyncpg.connect(dsn, statement_cache_size=0, server_settings={
        "search_path": "public, extensions", "application_name": "soliq-legal-feed-export",
        "default_transaction_read_only": "on"})


async def collect(dsn: str, since: timedelta, now: datetime, commit: str | None) -> list[dict]:
    conn = await connect_readonly(dsn)
    try:
        async with conn.transaction(readonly=True):
            start = now - since
            return await news_events(conn, start, now, commit) + await change_events(conn, start, now, commit)
    finally:
        await conn.close()


@dataclass
class ExportResult:
    events: int
    by_type: dict[str, int] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)


async def export(dsn: str, since: timedelta, out: Path, state_path: Path, *, now: datetime | None = None,
                 dry_run: bool = False) -> ExportResult:
    now = now or datetime.now(timezone.utc)
    events = await collect(dsn, since, now, git_commit())
    by_type: dict[str, int] = {}
    for ev in events:
        by_type[ev["event_type"]] = by_type.get(ev["event_type"], 0) + 1
    result = ExportResult(len(events), by_type)
    if dry_run or not events:
        return result
    state = load_state(state_path)
    new_state = apply_revisions(events, state)
    result.files = write_files(events, out, now)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(state_path, json.dumps(new_state, sort_keys=True).encode("utf-8"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="soliq.legal-feed/1.0 — faqat o'qiydigan eksport")
    parser.add_argument("--since", type=parse_since, default=parse_since("7d"), help="davr: 7d, 24h (sukut 7d)")
    parser.add_argument("--out", type=Path, required=True, help="chiqish papkasi (masalan Marketolog exchange/inbox)")
    parser.add_argument("--state", type=Path, default=Path(".cache/legal_feed_state.json"),
                        help="event_revision holati (lokal fayl)")
    parser.add_argument("--dry-run", action="store_true", help="fayl yozmasdan faqat hisob")
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    settings.require("supabase_db_url")
    res = asyncio.run(export(settings.supabase_db_url.get_secret_value(), args.since, args.out, args.state,
                             dry_run=args.dry_run))
    print(f"events={res.events} {json.dumps(res.by_type)}")
    for p in res.files:
        print(f"written {p}")


if __name__ == "__main__":
    main()
