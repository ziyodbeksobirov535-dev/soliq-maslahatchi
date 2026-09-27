"""PHASE 6 collector testlari (bazasiz): Lex.uz qidiruvi va RSS parserlari (real fixture'lar), kalit so'z filtri,
discovery va RSS pipeline (soxta pool/Lex.uz/LLM bilan), /yangiliklar formati, scheduler job'lari."""

import asyncio
import gzip
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import lexuz
from app.ai.client import LLMError
from app.ai.schemas import NewsClassification
from app.bot.formatting import format_news
from app.collector import discovery, news
from app.config import Settings
from app.scheduler.scheduler import build_scheduler

FIXTURES = Path(__file__).parent / "fixtures" / "lexuz"
SEARCH_URL = "https://lex.uz/uz/search/nat?searchtitle=soliq+imtiyoz&status=Y&lang=4"


def fixture_text(name: str) -> str:
    path = FIXTURES / name
    if path.suffix == ".gz":
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    return path.read_text(encoding="utf-8")


def search_page(name: str, url: str = SEARCH_URL) -> lexuz.SearchPage:
    return lexuz.parse_search(fixture_text(name), url)


def rss_items() -> list[lexuz.RssItem]:
    return lexuz.parse_rss(fixture_text("rss.xml"))


# --- soxta baza -------------------------------------------------------------


class FakeConn:
    def __init__(self, fetch_rows=None, fetchval=0):
        self.executed: list[tuple[str, tuple]] = []
        self.fetch_rows = fetch_rows or []
        self._fetchval = fetchval

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetch(self, sql, *args):
        return self.fetch_rows

    async def fetchval(self, sql, *args):
        return self._fetchval


class FakePool:
    def __init__(self, conn: FakeConn):
        self.conn = conn

    @asynccontextmanager
    async def _acquire(self):
        yield self.conn

    def acquire(self):
        return self._acquire()


def inserts(conn: FakeConn, table: str) -> list[tuple]:
    return [args for sql, args in conn.executed if f"INSERT INTO {table}" in sql]


# --- qidiruv parseri --------------------------------------------------------


def test_parse_search_first_page():
    page = search_page("search-soliq-imtiyoz.html.gz")
    assert page.total == 30
    assert len(page.items) == 20
    assert len({i.lex_id for i in page.items}) == 20
    assert all(i.url == f"https://lex.uz/docs/{i.lex_id}" for i in page.items)
    assert {i.site_status for i in page.items} == {"y"}


def test_parse_search_badge_with_number():
    item = next(i for i in search_page("search-soliq-imtiyoz.html.gz").items if i.lex_id == "-7106760")
    assert item.doc_type == "Oʻzbekiston Respublikasi Prezidentining Farmoni"
    assert item.number == "PF-140"
    assert item.reg_number is None
    assert item.adoption_date == date(2024, 9, 18)
    assert item.title.startswith("Oʻzbekiston Respublikasi Prezidentining soliq va bojxona imtiyozlarini")


def test_parse_search_badge_with_registration():
    item = next(i for i in search_page("search-soliq-imtiyoz.html.gz").items if i.lex_id == "-7282554")
    assert item.doc_type == ("Oʻzbekiston Respublikasi Iqtisodiyot va moliya vazirligi "
                             "Oʻzbekiston Respublikasi Soliq qoʻmitasining qarori")
    assert item.number is None
    assert item.reg_number == "3590"
    assert item.adoption_date == date(2024, 12, 25)


def test_parse_search_every_badge_is_recognised():
    for name in ("search-soliq-imtiyoz.html.gz", "search-soliq-imtiyoz-p2.html.gz", "search-aralash-holat.html.gz"):
        for item in search_page(name).items:
            assert item.adoption_date is not None, item.badge
            assert (item.number is None) != (item.reg_number is None), item.badge


def test_parse_search_postback_for_next_page():
    page = search_page("search-soliq-imtiyoz.html.gz")
    assert page.next_url == SEARCH_URL
    assert page.next_data["__EVENTTARGET"] == "ucFoundActsControl$LinkButton1"
    assert page.next_data["__EVENTARGUMENT"] == ""
    assert page.next_data["__VIEWSTATE"]
    assert "__VIEWSTATEGENERATOR" in page.next_data


def test_parse_search_last_page_has_no_next():
    page = search_page("search-soliq-imtiyoz-p2.html.gz")
    assert page.total == 30
    assert len(page.items) == 10
    assert page.next_url is None and page.next_data is None
    first = {i.lex_id for i in search_page("search-soliq-imtiyoz.html.gz").items}
    assert not first & {i.lex_id for i in page.items}


def test_parse_search_mixed_statuses():
    page = search_page("search-aralash-holat.html.gz")
    assert page.total == 84
    statuses = [i.site_status for i in page.items]
    assert statuses.count("y") == 17 and statuses.count("r") == 3


def test_parse_search_empty():
    page = search_page("search-bosh.html.gz")
    assert page.items == [] and page.total == 0 and page.next_url is None


def test_parse_search_rejects_empty_html():
    with pytest.raises(lexuz.LexUzError):
        lexuz.parse_search("  ", SEARCH_URL)


def test_search_url():
    url = lexuz.search_url(title="soliq  imtiyoz", form="farmon")
    assert url == "https://lex.uz/uz/search/nat?searchtitle=soliq+imtiyoz&form_id=3973&status=Y&lang=4"
    assert "exact2=1" in lexuz.search_url(title="soliq", exact=True)
    assert "status" not in lexuz.search_url(title="soliq", status=None)
    for kwargs in ({"title": "ab"}, {"title": "x" * 101}, {"title": "soliq", "form": "buyruq"},
                   {"title": "soliq", "status": "Z"}, {"status": None}):
        with pytest.raises(ValueError):
            lexuz.search_url(**kwargs)


# --- qidiruv sahifalash (soxta client) ----------------------------------------


class FakeSearchClient:
    """GET → 1-sahifa; POST → `post_page` (sukut: oxirgi sahifa)."""

    def __init__(self, post_page="search-soliq-imtiyoz-p2.html.gz"):
        self.calls: list[tuple[str, dict | None, bool]] = []
        self.post_page = post_page

    def fetch(self, url, *, use_cache=True, data=None):
        self.calls.append((url, data, use_cache))
        return fixture_text("search-soliq-imtiyoz.html.gz" if data is None else self.post_page)


def test_search_follows_postback_pages():
    client = FakeSearchClient()
    items, total = lexuz.search(SEARCH_URL, client=client)
    assert total == 30 and len(items) == 30 and len({i.lex_id for i in items}) == 30
    assert len(client.calls) == 2
    assert client.calls[0] == (SEARCH_URL, None, False)  # qidiruv natijasi keshlanmaydi
    url, data, _ = client.calls[1]
    assert url == SEARCH_URL and data["__EVENTTARGET"] == "ucFoundActsControl$LinkButton1"


def test_search_stops_when_site_repeats_page():
    client = FakeSearchClient(post_page="search-soliq-imtiyoz.html.gz")
    items, _ = lexuz.search(SEARCH_URL, client=client, max_pages=10)
    assert len(items) == 20 and len(client.calls) == 2


def test_search_max_pages_logs_truncation(caplog):
    with caplog.at_level(logging.WARNING, logger="lexuz"):
        items, total = lexuz.search(SEARCH_URL, client=FakeSearchClient(), max_pages=1)
    assert len(items) == 20 and total == 30
    assert "truncated" in caplog.text


# --- RSS parseri -------------------------------------------------------------


def test_parse_rss_items():
    items = rss_items()
    assert len(items) == 131
    assert len({i.lex_id for i in items}) == 131
    assert all(i.url == f"https://lex.uz/docs/{i.lex_id}" for i in items)
    assert all(i.pub_date is not None and i.adoption_date is not None for i in items)


def test_parse_rss_first_item_fields():
    item = rss_items()[0]
    assert item.lex_id == "-8509858"
    assert item.title.startswith("“Yashil makon” umummilliy loyihasini")
    assert item.doc_type == "Oʻzbekiston Respublikasi Prezidentining Farmoni"
    assert item.number == "PF-206"
    assert item.adoption_date == date(2026, 9, 23)
    assert item.effective_date == date(2026, 9, 25)
    assert item.pub_date == datetime(2026, 9, 23, 1, 24, 23, tzinfo=timezone.utc)


def test_parse_rss_departmental_registration_number():
    """Idoraviy hujjat: "...buyrugʻi рег. № МЮ 3941." — raqam 3941, turda "рег" qolmaydi."""
    items = [i for i in rss_items() if "рег." in i.description]
    assert len(items) == 23
    first = next(i for i in items if "МЮ 3941" in i.description)
    assert first.number == "3941"
    assert first.doc_type == "Oʻzbekiston Respublikasi Istiqbolli loyihalar milliy agentligi direktorining buyrugʻi"
    assert all(i.number and i.number[0].isdigit() for i in items)
    assert not any(i.doc_type.endswith("рег") for i in items)


def test_parse_rss_without_number():
    item = next(i for i in rss_items() if i.description.startswith("Oʻzbekiston Respublikasi bilan Serbiya"))
    assert item.number is None
    assert item.doc_type == "Oʻzbekiston Respublikasi bilan Serbiya Respublikasi oʻrtasida Qoʻshma deklaratsiya"


@pytest.mark.parametrize("xml", ["", "   ", "<rss><channel>"])
def test_parse_rss_invalid(xml):
    with pytest.raises(lexuz.LexUzError):
        lexuz.parse_rss(xml)


def test_parse_rss_does_not_resolve_entities():
    xml = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           '<rss><channel><item><title>&x;</title><link>https://lex.uz/docs/-1</link>'
           '<description>Qonun №1</description></item></channel></rss>')
    items = lexuz.parse_rss(xml)
    assert len(items) == 1 and "root:" not in items[0].title


# --- kalit so'z filtri ------------------------------------------------------


def test_keyword_filter_on_real_rss():
    counts = {"kuchli": 0, "soha": 0, "yoq": 0}
    for item in rss_items():
        hits = news.keyword_hits(item)
        counts["kuchli" if news.has_strong_hit(hits) else "soha" if hits else "yoq"] += 1
    assert counts == {"kuchli": 27, "soha": 48, "yoq": 56}


@pytest.mark.parametrize("text, expected", [
    ("Ish haqi to'lash tartibi", ["ish haqi"]),
    ("QQS stavkasi", ["qqs"]),
    ("Oʻzbekiston soligʻi", ["solig"]),
    # so'z o'rtasidan mos kelmaydi
    ("Ruxsatnomalar olish haqida", ["ruxsatnoma"]),
    ("Tartibga solish to'g'risida", []),
    ("Akkreditatsiya tartibi", []),
    ("Yangibozor tumani", []),
])
def test_keyword_hits_word_start_only(text, expected):
    assert news.text_keyword_hits(text) == expected


def test_strong_and_domain_words():
    assert news.has_strong_hit(["soliq"])
    assert not news.has_strong_hit(["bank", "kredit"])
    assert not set(news.KUCHLI_SOZLAR) & set(news.SOHA_SOZLARI)


def test_cyrillic_doc_type_item_is_filtered_by_latin_title():
    """RSS'dagi yagona kirillcha element (2026-09-27 fixture va 2026-09-28 jonli RSS'da ham): turi kirillcha
    (Senat qarori), nomi lotincha — filtr nom bo'yicha ishlaydi."""
    item = next(i for i in rss_items() if i.description.startswith("Ўзбекистон Республикаси Олий Мажлиси"))
    assert item.doc_type == "Ўзбекистон Республикаси Олий Мажлиси Сенатининг қарори"
    assert item.number == "СҚ-355-V"
    assert news.keyword_hits(item) == ["kochmas mulk"]


# --- discovery (soxta Lex.uz va baza) ----------------------------------------


def test_discover_merges_queries_and_isolates_errors(monkeypatch):
    p1 = search_page("search-soliq-imtiyoz.html.gz").items
    p2 = search_page("search-soliq-imtiyoz-p2.html.gz").items
    results = {"soliq": (p1 + p2, 30), "imtiyoz": (p1[:5], 5)}

    def fake_search(url, *, client, max_pages):
        assert max_pages == discovery.MAX_PAGES_PER_QUERY
        for q, res in results.items():
            if f"searchtitle={q}&" in url:
                return res
        raise lexuz.LexUzError("xato")

    monkeypatch.setattr(lexuz, "search", fake_search)
    conn = FakeConn(fetchval=7)
    stats = asyncio.run(discovery.discover(FakePool(conn), client=None, queries=("soliq", "imtiyoz", "aksiz")))
    assert (stats.queries, stats.errors, stats.found, stats.unique, stats.relevant) == (2, 1, 35, 30, 7)
    rows = inserts(conn, "topilgan_hujjatlar")
    assert len(rows) == 30
    by_id = {r[0]: r for r in rows}
    assert by_id[p1[0].lex_id][8] == ["soliq", "imtiyoz"]
    assert by_id[p2[0].lex_id][8] == ["soliq"]


def test_discover_relevance_needs_strong_word_and_active_status(monkeypatch):
    base = search_page("search-soliq-imtiyoz.html.gz").items[0]
    items = [
        base,
        lexuz.SearchItem(**{**base.__dict__, "lex_id": "-1", "title": "Bank xizmatlari to'g'risida"}),
        lexuz.SearchItem(**{**base.__dict__, "lex_id": "-2", "site_status": "r"}),
    ]
    monkeypatch.setattr(lexuz, "search", lambda url, *, client, max_pages: (items, 3))
    conn = FakeConn()
    asyncio.run(discovery.discover(FakePool(conn), client=None, queries=("soliq",)))
    relevant = {r[0]: r[10] for r in inserts(conn, "topilgan_hujjatlar")}
    assert relevant == {base.lex_id: True, "-1": False, "-2": False}


def test_import_pending_disabled_by_zero_limit():
    conn = FakeConn(fetch_rows=[{"lex_id": "-1", "in_db": False}])
    stats = asyncio.run(discovery.import_pending(FakePool(conn), client=None, limit=0, today=date(2026, 9, 27)))
    assert stats.candidates == 0 and conn.executed == []


def test_import_pending_imports_skips_known_and_counts_errors(monkeypatch):
    rows = [{"lex_id": "-1", "in_db": False}, {"lex_id": "-2", "in_db": True}, {"lex_id": "-3", "in_db": False}]
    conn = FakeConn(fetch_rows=rows)

    def fake_load(lex_id, *, client):
        if lex_id == "-3":
            raise lexuz.LexUzError("404")
        return f"doc{lex_id}"

    imported = []

    async def fake_import(conn, doc, card, today):
        imported.append(doc)

    monkeypatch.setattr(lexuz, "load", fake_load)
    monkeypatch.setattr(lexuz, "load_card", lambda lex_id, *, client: None)
    monkeypatch.setattr(discovery, "import_document", fake_import)
    stats = asyncio.run(discovery.import_pending(FakePool(conn), client=None, limit=10, today=date(2026, 9, 27)))
    assert (stats.candidates, stats.imported, stats.already, stats.errors) == (3, 1, 1, 1)
    assert imported == ["doc-1"]
    updates = [(sql, args) for sql, args in conn.executed if sql.startswith("UPDATE")]
    assert [a[0] for s, a in updates if "imported = true" in s] == ["-1", "-2"]
    assert [a for s, a in updates if "import_attempts" in s] == [("-3", "LexUzError")]


# --- RSS pipeline (soxta Lex.uz, baza va LLM) --------------------------------


class FakeRssClient:
    def fetch(self, url, *, use_cache=True, data=None):
        assert url == lexuz.RSS_URL and use_cache is False
        return fixture_text("rss.xml")


@pytest.fixture
def rss_env(monkeypatch):
    loaded, imported = [], []
    monkeypatch.setattr(lexuz, "load", lambda lex_id, *, client: loaded.append(lex_id) or None)
    monkeypatch.setattr(lexuz, "load_card", lambda lex_id, *, client: None)

    async def fake_import(conn, doc, card, today):
        imported.append(doc)

    monkeypatch.setattr(news, "import_document", fake_import)
    return loaded, imported


def saved_news(conn: FakeConn) -> dict[str, tuple]:
    return {args[0]: args for args in inserts(conn, "yangiliklar")}


def test_process_rss_without_llm_uses_strong_words_only(rss_env, monkeypatch):
    loaded, _ = rss_env
    monkeypatch.setattr(lexuz, "load", lambda lex_id, *, client: loaded.append(lex_id) or f"doc{lex_id}")
    conn = FakeConn()
    stats = asyncio.run(news.process_rss(FakePool(conn), FakeRssClient(), None, date(2026, 9, 27)))
    assert (stats.items, stats.new, stats.keyword_hits, stats.relevant, stats.errors) == (131, 131, 27, 27, 0)
    assert stats.imported == news.MAX_IMPORTS_PER_RUN == len(loaded)
    saved = saved_news(conn)
    assert len(saved) == 131
    assert sum(1 for a in saved.values() if a[9]) == 27  # relevant
    assert sum(1 for a in saved.values() if a[13]) == 20  # imported
    assert {a[10] for a in saved.values()} == {"keyword"}


def test_process_rss_skips_already_imported(rss_env):
    items = rss_items()
    conn = FakeConn(fetch_rows=[{"lex_id": i.lex_id, "imported": True} for i in items[:100]]
                    + [{"lex_id": i.lex_id, "imported": False} for i in items[100:]])
    stats = asyncio.run(news.process_rss(FakePool(conn), FakeRssClient(), None, date(2026, 9, 27)))
    assert stats.new == 0
    assert len(saved_news(conn)) == 31


class FakeNewsLLM:
    def __init__(self, relevant_ids=(), fail=False):
        self.relevant_ids, self.fail, self.calls = set(relevant_ids), fail, []

    def classify_news(self, title, meta, excerpt, usage):
        self.calls.append(title)
        if self.fail:
            raise LLMError("kredit yo'q")
        return NewsClassification(relevant=title in self.relevant_ids, topics=["soliq", "a", "b", "c"],
                                  summary=" Qisqa xulosa. ")


def test_process_rss_llm_checks_domain_words(rss_env):
    items = rss_items()
    strong = [i for i in items if news.has_strong_hit(news.keyword_hits(i))]
    llm = FakeNewsLLM(relevant_ids={strong[0].title})
    conn = FakeConn()
    stats = asyncio.run(news.process_rss(FakePool(conn), FakeRssClient(), llm, date(2026, 9, 27)))
    assert len(llm.calls) == stats.keyword_hits == 27 + 48
    assert stats.relevant == 1
    row = saved_news(conn)[strong[0].lex_id]
    assert row[9] is True and row[10] == "llm" and row[11] == ["soliq", "a", "b"] and row[12] == "Qisqa xulosa."


def test_process_rss_llm_error_falls_back_to_keyword(rss_env):
    conn = FakeConn()
    stats = asyncio.run(news.process_rss(FakePool(conn), FakeRssClient(), FakeNewsLLM(fail=True), date(2026, 9, 27)))
    assert stats.errors == 0
    assert stats.relevant == 27 + 48  # model javob bermasa, kalit so'z natijasi saqlanadi
    assert {a[10] for a in saved_news(conn).values() if a[9]} == {"keyword"}


# --- /yangiliklar formati ----------------------------------------------------


def test_format_news_escapes_and_shows_metadata():
    entry = news.NewsEntry(
        lex_id="-1", title="Soliq <b>imtiyoz</b> & boshqalar", doc_type="Prezident farmoni", number="PF-206",
        adoption_date=date(2026, 9, 23), effective_date=date(2026, 9, 25), url="https://lex.uz/docs/-1",
        summary="QQS <5%", status="kuchga_kirmagan")
    text = format_news([entry])
    assert "Soliq &lt;b&gt;imtiyoz&lt;/b&gt; &amp; boshqalar" in text
    assert 'href="https://lex.uz/docs/-1"' in text
    assert "Prezident farmoni, №PF-206, qabul qilingan 23.09.2026, kuchga kirish 25.09.2026" in text
    assert "QQS &lt;5%" in text
    assert "Holati:" in text


def test_format_news_active_document_has_no_status_line():
    entry = news.NewsEntry(lex_id="-1", title="Qonun", doc_type=None, number=None, adoption_date=None,
                           effective_date=None, url="https://lex.uz/docs/-1", summary=None, status="amalda")
    assert "Holati" not in format_news([entry])


# --- scheduler ---------------------------------------------------------------


def test_scheduler_jobs():
    scheduler = build_scheduler(pool=None, settings=Settings(_env_file=None), llm=None)
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"rss", "future_recheck", "weekly_refresh", "discover", "import_found", "heartbeat"}

    def cron(job_id):
        return {f.name: str(f) for f in jobs[job_id].trigger.fields if not f.is_default}

    assert cron("rss") == {"hour": "7", "minute": "10"}
    assert cron("future_recheck") == {"hour": "7", "minute": "40"}
    assert cron("weekly_refresh") == {"day_of_week": "sun", "hour": "3", "minute": "20"}
    assert cron("discover") == {"day_of_week": "sat", "hour": "4", "minute": "10"}
    assert cron("import_found") == {"hour": "8", "minute": "10"}
    assert jobs["heartbeat"].trigger.interval.total_seconds() == 300
    assert str(jobs["rss"].trigger.timezone) == "Asia/Tashkent"
