"""PHASE 2: Soliq kodeksi importi, /modda 461 va havola testlari (real Lex.uz fixture'lari)."""

import copy
import re
from dataclasses import replace
from datetime import date

import pytest

import lexuz
from app.collector.importer import import_document
from app.database.connection import connect
from app.retrieval.articles import get_article, normalize_article_number
from tests.conftest import run
from tests.test_lexuz_parser import SK_ID, card, soliq_kodeksi

TODAY = date(2026, 9, 27)
LINK_RE = re.compile(r"^https://lex\.uz/docs/-4674902#(-\d+|edi-?\d+)$")


def sk_card():
    return card("card1-soliq-kodeksi.html", SK_ID)


async def with_conn(dsn, fn):
    conn = await connect(dsn)
    try:
        return await fn(conn)
    finally:
        await conn.close()


async def reset(conn):
    await conn.execute("DELETE FROM hujjatlar WHERE lex_id = $1", SK_ID)


# --- normalize ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("461", "461"), (" 461 ", "461"), ("461-modda", "461"), ("modda 461", "461"), ("0461", "461"),
     ("121-1", "121-1"), ("121¹", "121-1"), ("121 1", "121-1"), ("121.1", "121-1"),
     ("abc", None), ("", None), ("461; DROP TABLE", None), ("99999", None)],
)
def test_normalize_article_number(raw, expected):
    assert normalize_article_number(raw) == expected


# --- import ------------------------------------------------------------------


def test_import_tax_code_then_reimport_is_noop(db):
    doc = soliq_kodeksi()

    async def scenario(conn):
        await reset(conn)
        first = await import_document(conn, doc, sk_card(), TODAY)
        second = await import_document(conn, doc, sk_card(), TODAY)
        row = await conn.fetchrow("SELECT * FROM hujjatlar WHERE lex_id = $1", SK_ID)
        count = await conn.fetchval("SELECT count(*) FROM elementlar WHERE document_id = $1", row["id"])
        changes = await conn.fetchval("SELECT count(*) FROM ozgarishlar WHERE document_id = $1", row["id"])
        versions = await conn.fetch(
            "SELECT version_token, on_date FROM hujjat_versiyalari WHERE document_id = $1", row["id"]
        )
        return first, second, row, count, changes, versions

    first, second, row, count, changes, versions = run(with_conn(db, scenario))
    assert first.first_import and first.added == len(doc.elements)
    assert not second.first_import
    assert (second.added, second.changed, second.removed) == (0, 0, 0)
    assert count == len(doc.elements) == 8137
    assert changes == 0  # birinchi import va o'zgarishsiz qayta import jurnalga yozilmaydi
    assert row["status"] == "amalda"
    assert row["status_raw"] == "Действующий"
    assert row["name"] == "O‘zbekiston Respublikasining Soliq kodeksi"
    assert row["type"] == "Кодекс"
    assert row["adoption_date"] == date(2019, 12, 30)
    assert row["effective_date"] == date(2020, 1, 1)
    assert row["current_version"] == "06.08.2026"
    assert row["source_url"] == "https://lex.uz/docs/-4674902?ONDATE=06.08.2026"
    assert row["text_available"] is True
    assert row["content_hash"] == doc.content_hash
    assert [(v["version_token"], v["on_date"]) for v in versions] == [("06.08.2026", date(2026, 8, 6))]


def test_change_detection_on_reimport(db):
    doc = soliq_kodeksi()
    modified = copy.copy(doc)
    changed_el = next(e for e in doc.elements if e.element_id == "-7966265")
    removed_el = next(e for e in doc.elements if e.element_id == "-7966266")
    new_el = replace(changed_el, element_id="-99999999", link=lexuz.elem_link(SK_ID, "-99999999"), text="yangi band")
    modified.elements = [
        (replace(e, text="1) o'zgargan matn") if e is changed_el else e)
        for e in doc.elements
        if e is not removed_el
    ] + [new_el]

    async def scenario(conn):
        await reset(conn)
        await import_document(conn, doc, sk_card(), TODAY)
        result = await import_document(conn, modified, sk_card(), TODAY)
        again = await import_document(conn, modified, sk_card(), TODAY)
        doc_id = result.document_id
        changes = await conn.fetch(
            "SELECT element_id, change_type, old_text, new_text FROM ozgarishlar WHERE document_id = $1 "
            "ORDER BY element_id",
            doc_id,
        )
        exists = await conn.fetchval(
            "SELECT count(*) FROM elementlar WHERE document_id = $1 AND element_id = '-7966266'", doc_id
        )
        text = await conn.fetchval(
            "SELECT text FROM elementlar WHERE document_id = $1 AND element_id = '-7966265'", doc_id
        )
        return result, again, changes, exists, text

    result, again, changes, exists, text = run(with_conn(db, scenario))
    assert (result.added, result.changed, result.removed) == (1, 1, 1)
    assert (again.added, again.changed, again.removed) == (0, 0, 0)
    by_id = {c["element_id"]: c for c in changes}
    assert by_id["-99999999"]["change_type"] == "qo'shilgan"
    assert by_id["-7966265"]["change_type"] == "o'zgargan"
    assert by_id["-7966265"]["old_text"].startswith("1) soliq davrida jami daromadi")
    assert by_id["-7966265"]["new_text"] == "1) o'zgargan matn"
    assert by_id["-7966266"]["change_type"] == "o'chirilgan"
    assert len(changes) == 3
    assert exists == 0
    assert text == "1) o'zgargan matn"


def test_import_without_card_keeps_unknown_status(db):
    async def scenario(conn):
        await reset(conn)
        await import_document(conn, soliq_kodeksi(), None, TODAY)
        return await conn.fetchrow("SELECT status, status_raw, status_checked_at FROM hujjatlar WHERE lex_id = $1", SK_ID)

    row = run(with_conn(db, scenario))
    assert row["status"] == "noma'lum"
    assert row["status_raw"] is None and row["status_checked_at"] is None


def test_import_rejects_card_of_other_document(db):
    other = card("card1-pf-206.html", "-8509858")
    with pytest.raises(ValueError):
        run(with_conn(db, lambda conn: import_document(conn, soliq_kodeksi(), other, TODAY)))


def test_future_status_from_card(db):
    """Kelajakda kuchga kiradigan hujjat bazaga "kuchga_kirmagan" bo'lib tushadi."""
    html_doc = lexuz.parse_doc(
        "<html><head><title>22.09.2026. Test qaror</title></head><body></body></html>", "-8503735"
    )
    future_card = card("card1-vm-508-kelajakda.html", "-8503735")

    async def scenario(conn):
        await conn.execute("DELETE FROM hujjatlar WHERE lex_id = '-8503735'")
        result = await import_document(conn, html_doc, future_card, TODAY)
        row = await conn.fetchrow("SELECT status, effective_date, text_available FROM hujjatlar WHERE id = $1", result.document_id)
        await conn.execute("DELETE FROM hujjatlar WHERE id = $1", result.document_id)
        return row

    row = run(with_conn(db, scenario))
    assert row["status"] == "kuchga_kirmagan"
    assert row["effective_date"] == date(2026, 12, 24)
    assert row["text_available"] is False


# --- /modda ------------------------------------------------------------------


@pytest.fixture(scope="module")
def imported_db(db):
    async def scenario(conn):
        await reset(conn)
        await import_document(conn, soliq_kodeksi(), sk_card(), TODAY)

    run(with_conn(db, scenario))
    return db


def test_article_461(imported_db):
    art = run(with_conn(imported_db, lambda conn: get_article(conn, "461")))
    assert art is not None
    assert art.document_name == "O‘zbekiston Respublikasining Soliq kodeksi"
    assert art.document_status == "amalda"
    assert art.number == "461"
    assert art.heading.element_id == "-4688907"
    assert art.heading.text == "461-modda. Soliq toʻlovchilar"
    assert art.link == "https://lex.uz/docs/-4674902#-4688907"
    texts = [e.text for e in art.body]
    assert texts[0].startswith("Aylanmadan olinadigan soliqni toʻlovchilar")
    assert any(t.startswith("1) soliq davrida jami daromadi bir milliard soʻmdan oshmagan") for t in texts)
    assert all(e.kind in ("text", "table", "footnote") for e in art.body)
    assert any(n.kind == "amendment" and "OʻRQ-1108" in n.text for n in art.notes)


def test_article_body_matches_parser_exactly(imported_db):
    """Bazadan qaytgan 461-modda parser natijasi bilan bir xil (hech narsa yo'qolmagan/qo'shilmagan)."""
    art = run(with_conn(imported_db, lambda conn: get_article(conn, "461")))
    parsed = [e for e in soliq_kodeksi().article("461") if e.kind in ("text", "table", "footnote")]
    assert [(e.element_id, e.text) for e in art.body] == [(e.element_id, e.text) for e in parsed]


def test_superscript_article(imported_db):
    art = run(with_conn(imported_db, lambda conn: get_article(conn, "121¹")))
    assert art is not None and art.heading.text.startswith("121¹-modda.")


def test_article_with_future_changes(imported_db):
    art = run(with_conn(imported_db, lambda conn: get_article(conn, "19")))
    assert art is not None and art.has_future_changes


@pytest.mark.parametrize("number", ["9999", "0", "484", "abc", "461; DROP TABLE elementlar"])
def test_nonexistent_article_returns_none(imported_db, number):
    assert run(with_conn(imported_db, lambda conn: get_article(conn, number))) is None


def test_unknown_document_returns_none(imported_db):
    assert run(with_conn(imported_db, lambda conn: get_article(conn, "461", lex_id="-1"))) is None


# --- havolalar -----------------------------------------------------------------


def test_all_stored_links_are_canonical_and_unique(imported_db):
    async def scenario(conn):
        return await conn.fetch(
            "SELECT e.element_id, e.link FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id "
            "WHERE h.lex_id = $1",
            SK_ID,
        )

    rows = run(with_conn(imported_db, scenario))
    assert len(rows) == 8137
    for r in rows:
        assert LINK_RE.match(r["link"]), r["link"]
        assert r["link"].endswith("#" + r["element_id"])
    assert len({r["link"] for r in rows}) == len(rows)


def test_every_article_link_points_to_existing_anchor_in_source_html(imported_db):
    """Har bir modda havolasidagi anchor real Lex.uz HTML'ida mavjud (uydirma ID yo'q)."""
    from tests.test_lexuz_parser import fixture_text

    html = fixture_text("soliq-kodeksi.html.gz")
    anchors = set(re.findall(r'<div\b[^>]*\bid="([^"]+)"', html))
    assert len(anchors) > 8000

    async def scenario(conn):
        return await conn.fetch(
            "SELECT e.element_id FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id "
            "WHERE h.lex_id = $1",
            SK_ID,
        )

    ids = {r["element_id"] for r in run(with_conn(imported_db, scenario))}
    assert ids <= anchors


# --- REST (Supabase PostgREST) yo'li ---------------------------------------------


def _fake_postgrest(dsn, calls, fail_rpc=False):
    """PostgREST'ning biz ishlatadigan 3 ta endpoint'ini lokal Postgres ustida taqlid qiladi."""
    import json as _json

    import httpx

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        assert request.headers["apikey"] == "service-key"
        conn = await connect(dsn)
        try:
            if request.method == "POST" and request.url.path == "/rest/v1/import_staging":
                rows = _json.loads(request.content)
                await conn.executemany(
                    "INSERT INTO import_staging (import_id, seq, element) VALUES ($1::uuid, $2, $3::jsonb)",
                    [(r["import_id"], r["seq"], _json.dumps(r["element"])) for r in rows],
                )
                return httpx.Response(201)
            if request.method == "POST" and request.url.path == "/rest/v1/rpc/finish_import":
                if fail_rpc:
                    return httpx.Response(500, json={"message": "boom"})
                body = _json.loads(request.content)
                raw = await conn.fetchval(
                    "SELECT finish_import($1::uuid, $2::jsonb, $3::date)",
                    body["p_import_id"], _json.dumps(body["p_doc"]), date.fromisoformat(body["p_today"]),
                )
                return httpx.Response(200, content=raw, headers={"content-type": "application/json"})
            if request.method == "DELETE" and request.url.path == "/rest/v1/import_staging":
                import_id = request.url.params["import_id"].removeprefix("eq.")
                await conn.execute("DELETE FROM import_staging WHERE import_id = $1::uuid", import_id)
                return httpx.Response(204)
            return httpx.Response(404)
        finally:
            await conn.close()

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_rest_import_matches_direct_import(db):
    from app.collector.importer import import_document_rest

    doc = soliq_kodeksi()
    calls = []

    async def scenario():
        conn = await connect(db)
        try:
            await reset(conn)
        finally:
            await conn.close()
        async with _fake_postgrest(db, calls) as client:
            first = await import_document_rest(
                "https://example.supabase.co/", "service-key", doc, sk_card(), TODAY, http_client=client
            )
            second = await import_document_rest(
                "https://example.supabase.co", "service-key", doc, sk_card(), TODAY, http_client=client
            )
        conn = await connect(db)
        try:
            count = await conn.fetchval(
                "SELECT count(*) FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id WHERE h.lex_id = $1", SK_ID
            )
            staging = await conn.fetchval("SELECT count(*) FROM import_staging")
            art = await get_article(conn, "461")
        finally:
            await conn.close()
        return first, second, count, staging, art

    first, second, count, staging, art = run(scenario())
    assert first.first_import and first.total == len(doc.elements)
    assert (second.added, second.changed, second.removed) == (0, 0, 0)
    assert count == len(doc.elements)
    assert staging == 0
    assert art.heading.element_id == "-4688907"
    chunks = [c for c in calls if c[1] == "/rest/v1/import_staging"]
    assert len(chunks) == 2 * -(-len(doc.elements) // 500)  # ikki import × bo'laklar soni
    assert all(c[2] == "Bearer service-key" for c in calls)


def test_rest_import_cleans_staging_on_failure(db):
    import httpx

    from app.collector.importer import import_document_rest

    calls = []

    async def scenario():
        async with _fake_postgrest(db, calls, fail_rpc=True) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await import_document_rest(
                    "https://example.supabase.co", "service-key", soliq_kodeksi(), sk_card(), TODAY,
                    http_client=client, chunk_size=3000,
                )
        conn = await connect(db)
        try:
            return await conn.fetchval("SELECT count(*) FROM import_staging")
        finally:
            await conn.close()

    assert run(scenario()) == 0
    assert calls[-1][0] == "DELETE"


def test_finish_import_rejects_duplicate_element_ids(db):
    import json as _json
    import uuid as _uuid

    async def scenario(conn):
        import_id = _uuid.uuid4()
        el = {"element_id": "-1", "order_no": 1, "type": "ACT_TEXT", "kind": "text", "text": "a",
              "text_hash": "h", "link": "https://lex.uz/docs/-5#-1"}
        async with conn.transaction():  # xatoda staging ham qaytariladi
            await conn.executemany(
                "INSERT INTO import_staging (import_id, seq, element) VALUES ($1, $2, $3::jsonb)",
                [(import_id, 1, _json.dumps(el)), (import_id, 2, _json.dumps(el))],
            )
            doc = {"lex_id": "-5", "name": "x", "url": "https://lex.uz/docs/-5"}
            await conn.fetchval("SELECT finish_import($1, $2::jsonb, $3)", import_id, _json.dumps(doc), TODAY)

    import asyncpg

    with pytest.raises(asyncpg.RaiseError):
        run(with_conn(db, scenario))
