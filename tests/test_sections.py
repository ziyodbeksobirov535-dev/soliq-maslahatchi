"""009 bo'limlar va PHASE 6 bazali qismlari (TEST_DATABASE_URL kerak):
hisobla_birliklar (bob/ilova/bo'laklash), bo'lim bo'yicha qidiruv, get_section, <bolim> konteksti,
discovery upsert/import_pending SQL, tracked_documents, recent_news.

Moddasiz hujjat sun'iy, lekin element turlari va tartibi real farmon/qarorlardagidek (sarlavha, preambula,
rim raqamli bob, raqamli bandlar, jadval, o'zgartirish izohi, "1-ILOVA" qatori, imzo).
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import lexuz
from app.ai.prompts import render_sources
from app.collector import discovery
from app.collector.importer import import_document
from app.collector.jobs import tracked_documents
from app.collector.news import recent_news
from app.database.connection import connect, create_pool
from app.retrieval.articles import get_section
from app.retrieval.query import analyze
from app.retrieval.search import search_articles
from app.services.answer import article_to_source
from tests.conftest import run
from tests.test_collector import search_page

TODAY = date(2026, 9, 27)
DOC_ID = "-9900001"
ARTICLE_DOC_ID = "-9900002"
BIG_BAND = "Yuridik shaxslar hisobotni belgilangan tartibda taqdim etadi. " * 50  # ~3 000 belgi
FILLER = "Qo'shimcha tushuntirish matni. " * 50  # ~1 500 belgi, band raqamisiz
HUGE = "Jadval qatori ma'lumotlari. " * 330  # ~9 000 belgi


def element(doc_id: str, n: int, kind: str, text: str, **kw) -> lexuz.Element:
    eid = f"-{int(doc_id.lstrip('-')) * 100 + n}"
    return lexuz.Element(element_id=eid, doc_id=doc_id, order_no=n, type=kind.upper(), kind=kind, text=text,
                         link=lexuz.elem_link(doc_id, eid), **kw)


def eid(n: int, doc_id: str = DOC_ID) -> str:
    return f"-{int(doc_id.lstrip('-')) * 100 + n}"


def decree() -> lexuz.Document:
    parts = [
        ("title", "Soliq hisobotini soddalashtirish to'g'risida"),       # 1  — bo'limga kirmaydi
        ("text", "Tadbirkorlik subyektlariga qulaylik yaratish maqsadida:"),  # 2  — "Asosiy qism"
        ("text", "1. Hisobot shakllari qisqartirilsin."),                 # 3
        ("header", "I. Umumiy qoidalar"),                                 # 4  — bo'lim sarlavhasi
        ("text", "2. Aksiz to'lovchilar hisobotni har oy topshiradi."),   # 5
        ("amendment", "O'zbekiston Respublikasi Prezidentining farmoni tahririda"),  # 6 — izoh, kirmaydi
        ("table", "Aksiz stavkalari jadvali"),                            # 7
        ("header", "II. Bo'sh bob"),                                      # 8  — keyin matn yo'q
        ("other", "1-ILOVA"),                                             # 9  — ilova boshi
        ("header", "1-bob. Hisobot topshirish tartibi"),                  # 10
        ("text", "1. " + BIG_BAND),                                       # 11
        ("text", FILLER),                                                 # 12 — hali 4 000 ga yetmagan
        ("text", "2. Hisobot elektron shaklda topshiriladi."),            # 13 — 4 000+ va band → yangi bo'lak
        ("text", HUGE),                                                   # 14
        ("text", "Yakuniy qoida."),                                       # 15 — 8 000+ → band bo'lmasa ham bo'lak
        ("other", "O'zbekiston Respublikasi Prezidenti"),                 # 16 — imzo, kirmaydi
    ]
    elements = [element(DOC_ID, n, kind, text) for n, (kind, text) in enumerate(parts, 1)]
    return lexuz.Document(doc_id=DOC_ID, url=lexuz.doc_url(DOC_ID), title="Farmon", name="Sinov farmoni",
                          number="PF-1", adoption_date=date(2026, 1, 5), effective_date=date(2026, 1, 6),
                          header_label=None, version=None, versions=[], elements=elements)


def code_like() -> lexuz.Document:
    elements = [
        element(ARTICLE_DOC_ID, 1, "title", "Sinov qonuni"),
        element(ARTICLE_DOC_ID, 2, "article", "1-modda. Aksiz", modda="1-modda", modda_raqami="1"),
        element(ARTICLE_DOC_ID, 3, "text", "Aksiz stavkalari qonun bilan belgilanadi.", modda="1-modda",
                modda_raqami="1"),
    ]
    return lexuz.Document(doc_id=ARTICLE_DOC_ID, url=lexuz.doc_url(ARTICLE_DOC_ID), title="Qonun",
                          name="Sinov qonuni", number=None, adoption_date=None, effective_date=None,
                          header_label=None, version=None, versions=[], elements=elements)


async def with_conn(dsn, fn):
    conn = await connect(dsn)
    try:
        return await fn(conn)
    finally:
        await conn.close()


async def import_active(conn, doc):
    await import_document(conn, doc, None, TODAY)
    await conn.execute("UPDATE hujjatlar SET status = 'amalda' WHERE lex_id = $1", doc.doc_id)


@pytest.fixture
def sec_db(db):
    async def setup(conn):
        await conn.execute("DELETE FROM hujjatlar WHERE lex_id = ANY($1::text[])", [DOC_ID, ARTICLE_DOC_ID])
        await import_active(conn, decree())
        await import_active(conn, code_like())

    run(with_conn(db, setup))
    yield db
    run(with_conn(db, lambda c: c.execute("DELETE FROM hujjatlar WHERE lex_id = ANY($1::text[])",
                                          [DOC_ID, ARTICLE_DOC_ID])))


def units(dsn, doc_id=DOC_ID) -> dict[int, tuple[str | None, str | None]]:
    async def go(conn):
        rows = await conn.fetch(
            "SELECT e.order_no, e.birlik, e.birlik_nomi FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id "
            "WHERE h.lex_id = $1 ORDER BY e.order_no", doc_id)
        return {r["order_no"]: (r["birlik"], r["birlik_nomi"]) for r in rows}

    return run(with_conn(dsn, go))


# --- hisobla_birliklar ------------------------------------------------------------


def test_sections_are_computed_on_import(sec_db):
    u = units(sec_db)
    main = (eid(2), "Asosiy qism")
    chapter = (eid(4), "I. Umumiy qoidalar")
    annex = (eid(10), "1-ilova, 1-bob. Hisobot topshirish tartibi")
    assert u[1] == (None, None)  # sarlavha
    assert u[2] == u[3] == main
    assert u[4] == u[5] == u[7] == chapter  # bob sarlavhasi bo'limning boshi
    assert u[6] == (None, None)  # o'zgartirish izohi
    assert u[8] == (None, None)  # matnsiz bob
    assert u[9] == (None, None)  # "1-ILOVA" qatori
    assert u[10] == u[11] == u[12] == annex


def test_large_section_is_split_at_band_then_by_size(sec_db):
    u = units(sec_db)
    assert u[13] == u[14] == (eid(13), "1-ilova, 1-bob. Hisobot topshirish tartibi, 2-band")
    assert u[15] == (eid(15), "1-ilova, 1-bob. Hisobot topshirish tartibi (davomi)")
    assert u[16] == (None, None)  # imzo


def test_articles_have_no_sections(sec_db):
    assert set(units(sec_db, ARTICLE_DOC_ID).values()) == {(None, None)}


def test_recompute_is_idempotent(sec_db):
    async def go(conn):
        doc_pk = await conn.fetchval("SELECT id FROM hujjatlar WHERE lex_id = $1", DOC_ID)
        return await conn.fetchval("SELECT hisobla_birliklar($1)", doc_pk)

    assert run(with_conn(sec_db, go)) == 0


def test_reimport_recomputes_sections(sec_db):
    doc = decree()
    doc.elements.insert(1, element(DOC_ID, 17, "header", "Kirish"))
    for n, e in enumerate(doc.elements, 1):
        e.order_no = n
    run(with_conn(sec_db, lambda c: import_document(c, doc, None, TODAY)))
    u = units(sec_db)
    assert u[3] == u[4] == (eid(17), "Kirish")  # preambula endi "Kirish" bo'limida


# --- qidiruv, get_section, kontekst ---------------------------------------------


def test_search_returns_section_and_article(sec_db):
    plan = analyze("Aksiz hisobotini qachon topshirish kerak?", TODAY)
    plan.lex_ids = [DOC_ID, ARTICLE_DOC_ID]
    hits = run(with_conn(sec_db, lambda c: search_articles(c, plan)))
    by_unit = {h.unit_key: h for h in hits}
    section = by_unit[("b", eid(4))]
    assert section.lex_id == DOC_ID and section.modda_raqami is None
    assert section.birlik_nomi == "I. Umumiy qoidalar"
    assert section.heading == "I. Umumiy qoidalar" and section.heading_element_id == eid(4)
    assert section.heading_link == lexuz.elem_link(DOC_ID, eid(4))
    assert eid(5) in {m.element_id for m in section.matched}
    article = by_unit[("m", "1")]
    assert article.lex_id == ARTICLE_DOC_ID and article.birlik is None and article.birlik_nomi is None


def test_get_section(sec_db):
    art = run(with_conn(sec_db, lambda c: get_section(c, DOC_ID, eid(4))))
    assert art.number is None and art.birlik == eid(4)
    assert art.heading.element_id == eid(4)
    assert [e.element_id for e in art.body] == [eid(5), eid(7)]  # izoh (6) bo'limda emas
    assert run(with_conn(sec_db, lambda c: get_section(c, DOC_ID, "-1"))) is None
    assert run(with_conn(sec_db, lambda c: get_section(c, "-1", eid(4)))) is None


def test_section_context_uses_bolim_tag(sec_db):
    art = run(with_conn(sec_db, lambda c: get_section(c, DOC_ID, eid(4))))
    src = article_to_source(art)
    assert src.key == (DOC_ID, "b", eid(4)) and src.title == "I. Umumiy qoidalar"
    xml = render_sources([src])
    assert '<bolim hujjat="Sinov farmoni"' in xml and 'nomi="I. Umumiy qoidalar"' in xml
    assert xml.count("<element ") == 3 and "</bolim>" in xml and "<modda" not in xml


# --- discovery, tracked_documents, recent_news ---------------------------------


@pytest.fixture
def pool_db(db):
    async def clean(conn):
        await conn.execute("DELETE FROM topilgan_hujjatlar")
        await conn.execute("DELETE FROM yangiliklar")
        await conn.execute("DELETE FROM hujjatlar WHERE lex_id NOT IN ('-4674902')")

    run(with_conn(db, clean))
    yield db
    run(with_conn(db, clean))


def with_pool(dsn, fn):
    async def go():
        pool = await create_pool(dsn, min_size=1, max_size=2)
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return run(go())


def test_discover_upsert_merges_queries(pool_db, monkeypatch):
    items = search_page("search-soliq-imtiyoz.html.gz").items
    monkeypatch.setattr(lexuz, "search", lambda url, *, client, max_pages: (items, len(items)))

    async def go(pool):
        await discovery.discover(pool, client=None, queries=("soliq",))
        await discovery.discover(pool, client=None, queries=("imtiyoz",))
        async with pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM topilgan_hujjatlar ORDER BY lex_id")

    rows = with_pool(pool_db, go)
    assert len(rows) == 20
    assert all(sorted(r["queries"]) == ["imtiyoz", "soliq"] for r in rows)
    pf = next(r for r in rows if r["lex_id"] == "-7106760")
    assert pf["number"] == "PF-140" and pf["relevant"] and not pf["imported"] and pf["site_status"] == "y"


def test_import_pending_orders_and_marks(pool_db, monkeypatch):
    items = search_page("search-soliq-imtiyoz.html.gz").items
    monkeypatch.setattr(lexuz, "search", lambda url, *, client, max_pages: (items, len(items)))
    loaded = []

    def fake_load(lex_id, *, client):
        loaded.append(lex_id)
        if lex_id == "-7106760":
            raise lexuz.LexUzError("vaqtincha xato")
        doc = decree()
        doc.doc_id, doc.url = lex_id, lexuz.doc_url(lex_id)
        doc.elements = [element(DOC_ID, 1, "text", "1. Soliq imtiyozi.")]
        doc.elements[0].doc_id, doc.elements[0].link = lex_id, lexuz.elem_link(lex_id, doc.elements[0].element_id)
        return doc

    monkeypatch.setattr(lexuz, "load", fake_load)
    monkeypatch.setattr(lexuz, "load_card", lambda lex_id, *, client: None)

    async def go(pool):
        await discovery.discover(pool, client=None, queries=("soliq",))
        stats = await discovery.import_pending(pool, client=None, limit=3, today=TODAY)
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT lex_id, imported, import_attempts, last_error FROM topilgan_hujjatlar "
                                    "WHERE lex_id = ANY($1::text[])", loaded)
        return stats, {r["lex_id"]: r for r in rows}

    stats, rows = with_pool(pool_db, go)
    # avval Prezident va Vazirlar Mahkamasi hujjatlari, ichida yangilari
    top = sorted((i for i in items if discovery.is_wanted(i.doc_type, i.title, i.site_status)),
                 key=lambda i: (any(k in (i.doc_type or "") for k in ("Prezident", "Vazirlar Mahkamasi")),
                                i.adoption_date), reverse=True)
    assert loaded == [i.lex_id for i in top[:3]]
    assert "Prezident" in top[0].doc_type
    assert (stats.candidates, stats.imported, stats.errors) == (3, 2, 1)
    assert rows["-7106760"]["import_attempts"] == 1 and rows["-7106760"]["last_error"] == "LexUzError"
    assert sum(r["imported"] for r in rows.values()) == 2


def test_tracked_documents_and_recent_news(pool_db):
    now = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)

    async def go(pool):
        async with pool.acquire() as conn:
            await import_active(conn, decree())
            await import_active(conn, code_like())
            await conn.execute(
                "INSERT INTO topilgan_hujjatlar (lex_id, title, url, relevant, imported) VALUES ($1, 't', $2, true, true)",
                DOC_ID, lexuz.doc_url(DOC_ID))
            await conn.execute("UPDATE hujjatlar SET status = 'kuchini_yoqotgan' WHERE lex_id = $1", ARTICLE_DOC_ID)
            await conn.execute(
                "INSERT INTO yangiliklar (lex_id, title, url, relevant, imported, pub_date) VALUES "
                "($1, 'Yangi farmon', $2, true, true, $3), ($4, 'Eski', $5, true, false, $6), "
                "($7, 'Aloqasiz', $8, false, false, $3)",
                ARTICLE_DOC_ID, lexuz.doc_url(ARTICLE_DOC_ID), now,
                "-9900003", lexuz.doc_url("-9900003"), now - timedelta(days=30),
                "-9900004", lexuz.doc_url("-9900004"))
            news = await recent_news(conn, TODAY)
        return await tracked_documents(pool), news

    tracked, news = with_pool(pool_db, go)
    assert DOC_ID in tracked  # qidiruvdan import qilingan
    assert ARTICLE_DOC_ID not in tracked  # kuchini yo'qotgan
    assert tracked[0] == "-4674902"  # asosiy hujjatlar birinchi
    assert [(n.lex_id, n.status) for n in news] == [(ARTICLE_DOC_ID, "kuchini_yoqotgan")]
