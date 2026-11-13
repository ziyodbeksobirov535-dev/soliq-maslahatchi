"""soliq.legal-feed/1.0 eksporti: event_id formulasi, faqat o'qish, xesh va havolalar, revision, fayl yozish.

DB testlari TEST_DATABASE_URL talab qiladi; hujjatlar — tests/test_sections.py dagi farmon va qonun namunasi.
"""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import asyncpg
import pytest

from app.collector.importer import import_document
from app.database.connection import connect
from app.export import legal_feed as lf
from tests.conftest import run
from tests.test_sections import ARTICLE_DOC_ID, DOC_ID, code_like, decree

TODAY = date(2026, 9, 27)
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def test_event_id_matches_handoff_example():
    # INTEGRATION_HANDOFF.md §12.3 (PF-100, 2-band)
    assert lf.event_id("provision_snapshot", "-8236831", "28.08.2026", "-8237064",
                       "962a44bbea78801f887531c5adaea09ae5c30fff923acb2bc9ae666e2f2758d9") \
        == "slf1-07c228e4b39acdd693beb3c4513972e7"
    assert lf.event_id("news_item", "-1", None, None, None) == lf.event_id("news_item", "-1", None, None, None)
    assert lf.event_id("news_item", "-1", "01.01.2026", None, "a") != lf.event_id("news_item", "-1", "02.01.2026", None, "a")


def test_parse_since():
    assert lf.parse_since("7d") == timedelta(days=7) and lf.parse_since("24h") == timedelta(hours=24)
    with pytest.raises(Exception):
        lf.parse_since("week")


def test_revisions_bump_only_on_content_change():
    ev = {"event_id": "slf1-x", "emitted_at": "a", "producer": {"commit": "1"}, "retrieval": {"retrieved_at": "a"},
          "document": {"status": "amalda", "last_successful_load": "a", "status_checked_at": "a"}, "event_revision": 1}
    state = lf.apply_revisions([ev], {})
    assert ev["event_revision"] == 1
    again = dict(ev, emitted_at="b", producer={"commit": "2"}, retrieval={"retrieved_at": "b"},
                 document={"status": "amalda", "last_successful_load": "b", "status_checked_at": "b"})
    state = lf.apply_revisions([again], state)
    assert again["event_revision"] == 1  # faqat vaqt belgilari o'zgardi
    changed = dict(ev, document={"status": "kuchini_yoqotgan", "last_successful_load": "a", "status_checked_at": "a"})
    lf.apply_revisions([changed], state)
    assert changed["event_revision"] == 2


# --- baza bilan ------------------------------------------------------------------------


@pytest.fixture
def fdb(db):
    async def clean(conn):
        await conn.execute("DELETE FROM xabarlar")
        await conn.execute("DELETE FROM yangiliklar")
        await conn.execute("DELETE FROM hujjatlar WHERE lex_id = ANY($1::text[])", [DOC_ID, ARTICLE_DOC_ID])

    async def setup():
        conn = await connect(db)
        try:
            await clean(conn)
            await import_document(conn, decree(), None, TODAY)
            await import_document(conn, code_like(), None, TODAY)
            changed = code_like()
            changed.elements[2].text = "Aksiz stavkalari Vazirlar Mahkamasi tomonidan belgilanadi."
            await import_document(conn, changed, None, TODAY)  # → ozgarishlar: o'zgargan
            await conn.execute(
                "INSERT INTO yangiliklar (lex_id, title, doc_type, number, url, pub_date, keyword_hits, relevant, "
                "relevance_method, summary, imported) VALUES ($1, 'Soliq hisobotini soddalashtirish', "
                "'Prezident farmoni', 'PF-1', $2, $3, '{soliq}', true, 'llm', 'AI xulosa', true), "
                "('-9900077', 'Matni yo''q qaror', 'VM qarori', '5', 'https://lex.uz/docs/-9900077', $3, '{soliq}', "
                "true, 'keyword', NULL, false)",
                DOC_ID, f"https://lex.uz/docs/{DOC_ID}", NOW - timedelta(days=1))
            await conn.execute("INSERT INTO xabarlar (turi, kalit, lex_id, matn, havola, usul, holat) VALUES "
                               "('yangilik', $1, $2, 'x', $3, 'llm', 'yuborildi')",
                               f"yangilik:{DOC_ID}", DOC_ID, f"https://lex.uz/docs/{DOC_ID}")
            await conn.execute("UPDATE hujjatlar SET last_successful_load = $1 WHERE lex_id = $2",
                               NOW - timedelta(days=2), DOC_ID)
        finally:
            await conn.close()

    run(setup())
    yield db

    async def teardown():
        conn = await connect(db)
        try:
            await clean(conn)
        finally:
            await conn.close()

    run(teardown())


def test_readonly_connection_rejects_writes(fdb):
    async def go():
        conn = await lf.connect_readonly(fdb)
        try:
            await conn.execute("DELETE FROM yangiliklar")
        finally:
            await conn.close()

    with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
        run(go())


def test_export_files_events_and_contract(fdb, tmp_path):
    state = tmp_path / "state.json"
    res = run(lf.export(fdb, timedelta(days=7), tmp_path / "inbox", state, now=NOW))
    assert res.by_type["news_item"] == 2 and res.by_type["provision_changed"] >= 1
    [path] = res.files
    assert path.name.startswith("legal-feed-v1-20261114T120000Z") and path.suffix == ".jsonl"
    sidecar = path.with_name(path.name + ".sha256").read_text().split()[0]
    assert sidecar == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not list(path.parent.glob("*.tmp"))
    events = [json.loads(line) for line in path.read_text().splitlines()]

    for ev in events:
        assert ev["schema"] == "soliq.legal-feed/1.0" and ev["event_revision"] == 1
        assert ev["event_id"].startswith("slf1-") and len(ev["event_id"]) == 37
        doc = ev["document"]
        assert doc["url"] == f"https://lex.uz/docs/{doc['lex_id']}"
        assert doc["status"] in ("amalda", "kuchga_kirmagan", "kuchini_yoqotgan", "noma'lum")
        for p in ev["provisions"]:
            assert p["text_hash"] == hashlib.sha256(p["evidence_text"].encode()).hexdigest()
            assert p["link"] == f"https://lex.uz/docs/{doc['lex_id']}#{p['element_id']}"
        assert "telegram_id" not in json.dumps(ev) and "matn" not in ev

    news = {e["document"]["lex_id"]: e for e in events if e["event_type"] == "news_item"}
    imported = news[DOC_ID]
    assert imported["news"]["admin_approved"] is True and imported["news"]["ai_summary"] == "AI xulosa"
    assert "ai_summary_unverified" in imported["uncertainty"]["flags"]
    assert "stale_source" not in imported["uncertainty"]["flags"]  # 2 kun oldin yuklangan
    texts = [p["evidence_text"] for p in imported["provisions"]]
    assert "2. Aksiz to'lovchilar hisobotni har oy topshiradi." in texts
    assert all(p["kind"] in ("article", "text", "table") for p in imported["provisions"])  # izoh/sarlavha emas

    textless = news["-9900077"]
    assert textless["document"]["status"] == "noma'lum" and textless["provisions"] == []
    assert {"status_unknown", "text_not_published", "keyword_relevance_only", "stale_source"} <= \
        set(textless["uncertainty"]["flags"])

    [change] = [e for e in events if e["event_type"] == "provision_changed"]
    p = change["provisions"][0]
    assert p["change"]["type"] == "changed" and p["change"]["old_text"] == "Aksiz stavkalari qonun bilan belgilanadi."
    assert p["evidence_text"] == "Aksiz stavkalari Vazirlar Mahkamasi tomonidan belgilanadi."
    assert p["unit"] == {"type": "article", "article_number": "1", "section_key": None, "section_name": None}


def test_reexport_keeps_revision_and_bumps_on_status_change(fdb, tmp_path):
    state = tmp_path / "state.json"
    first = run(lf.export(fdb, timedelta(days=7), tmp_path / "a", state, now=NOW))
    second = run(lf.export(fdb, timedelta(days=7), tmp_path / "b", state, now=NOW + timedelta(minutes=5)))

    def load(res):
        return {e["event_id"]: e for p in res.files for e in map(json.loads, p.read_text().splitlines())}

    a, b = load(first), load(second)
    assert a.keys() == b.keys() and all(e["event_revision"] == 1 for e in b.values())

    async def repeal():
        conn = await connect(fdb)
        try:
            await conn.execute("UPDATE hujjatlar SET status = 'kuchini_yoqotgan' WHERE lex_id = $1", DOC_ID)
        finally:
            await conn.close()

    run(repeal())
    c = load(run(lf.export(fdb, timedelta(days=7), tmp_path / "c", state, now=NOW + timedelta(minutes=10))))
    news_id = next(i for i, e in c.items() if e["document"]["lex_id"] == DOC_ID and e["event_type"] == "news_item")
    assert c[news_id]["event_revision"] == 2 and "repealed" in c[news_id]["uncertainty"]["flags"]


def test_dry_run_and_empty_window_write_nothing(fdb, tmp_path):
    res = run(lf.export(fdb, timedelta(days=7), tmp_path / "x", tmp_path / "s.json", now=NOW, dry_run=True))
    assert res.events > 0 and res.files == [] and not (tmp_path / "x").exists()
    res = run(lf.export(fdb, timedelta(hours=1), tmp_path / "y", tmp_path / "s.json",
                        now=NOW + timedelta(days=30)))
    assert res.events == 0 and res.files == [] and not (tmp_path / "s.json").exists()
