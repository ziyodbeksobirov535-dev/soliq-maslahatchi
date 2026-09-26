"""Parser testlari — real Lex.uz sahifalari asosida (tests/fixtures/lexuz/, 2026-09-26 holati)."""

import gzip
from datetime import date
from functools import lru_cache
from pathlib import Path

import httpx
import pytest

import lexuz
from lexuz import LexUzClient, LexUzError, LexUzHTTPError

FIXTURES = Path(__file__).parent / "fixtures" / "lexuz"
SK_ID = "-4674902"
SK2007_ID = "1286689"


def fixture_text(name: str) -> str:
    path = FIXTURES / name
    if path.suffix == ".gz":
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def soliq_kodeksi() -> lexuz.Document:
    return lexuz.parse_doc(fixture_text("soliq-kodeksi.html.gz"), SK_ID)


@lru_cache(maxsize=None)
def soliq_kodeksi_2007() -> lexuz.Document:
    return lexuz.parse_doc(fixture_text("soliq-kodeksi-2007-ru.html.gz"), SK2007_ID)


def by_id(doc: lexuz.Document, element_id: str) -> lexuz.Element:
    return next(e for e in doc.elements if e.element_id == element_id)


# --- hujjat metadata ---------------------------------------------------


def test_document_metadata():
    doc = soliq_kodeksi()
    assert doc.doc_id == SK_ID
    assert doc.url == "https://lex.uz/docs/-4674902"
    assert doc.title == "30.12.2019. Oʻzbekiston Respublikasining Soliq kodeksi"
    assert doc.name == "Oʻzbekiston Respublikasining Soliq kodeksi"
    assert doc.adoption_date == date(2019, 12, 30)
    assert doc.effective_date == date(2020, 1, 1)
    assert doc.number is None  # kodeksda raqam yo'q
    assert doc.text_available


def test_versions_include_current_and_future():
    doc = soliq_kodeksi()
    assert doc.version == "06.08.2026"
    assert doc.versions[:3] == ["12.12.2026 01", "12.12.2026", "06.08.2026"]
    assert "27.07.2026" in doc.versions
    assert len(doc.versions) == len(set(doc.versions)) > 50


def test_decree_metadata_with_number():
    doc = lexuz.parse_doc(fixture_text("pf-206-matnsiz.html"), "-8509858")
    assert doc.number == "PF-206"
    assert doc.adoption_date == date(2026, 9, 23)
    assert doc.effective_date == date(2026, 9, 25)
    assert "Prezidentining Farmoni" in doc.header_label


def test_document_without_published_text():
    doc = lexuz.parse_doc(fixture_text("pf-206-matnsiz.html"), "-8509858")
    assert doc.elements == []
    assert doc.text_available is False


def test_full_document_parsing_counts():
    doc = soliq_kodeksi()
    articles = doc.articles()
    assert len(articles) == 500
    assert all(a.modda_raqami for a in articles)
    assert len({a.modda_raqami for a in articles}) == 500
    assert articles[-1].modda_raqami == "483"
    ids = [e.element_id for e in doc.elements]
    assert len(ids) == len(set(ids))
    assert [e.order_no for e in doc.elements] == list(range(1, len(doc.elements) + 1))


def test_content_hash_is_deterministic():
    html = fixture_text("soliq-kodeksi.html.gz")
    assert lexuz.parse_doc(html, SK_ID).content_hash == soliq_kodeksi().content_hash


# --- elementlar ---------------------------------------------------------


def test_title_element():
    title = by_id(soliq_kodeksi(), "-4675087")
    assert title.type == "ACT_TITLE"
    assert title.kind == lexuz.KIND_TITLE
    assert title.text == "Oʻzbekiston Respublikasining Soliq kodeksi"


def test_article_461():
    doc = soliq_kodeksi()
    heading = doc.articles()[[a.modda_raqami for a in doc.articles()].index("461")]
    assert heading.element_id == "-4688907"
    assert heading.type == "CLAUSE_DEFAULT"
    assert heading.text == "461-modda. Soliq toʻlovchilar"
    assert heading.bob == "66-bob. Aylanmadan olinadigan soliqni hisoblab chiqarish va toʻlash"
    assert heading.element_path == (
        "MAXSUS QISM > XX BOʻLIM. AYLANMADAN OLINADIGAN SOLIQ > "
        "66-bob. Aylanmadan olinadigan soliqni hisoblab chiqarish va toʻlash > 461-modda. Soliq toʻlovchilar"
    )
    chapter = by_id(doc, heading.parent_element_id)
    assert chapter.kind == lexuz.KIND_HEADER and chapter.text.startswith("66-bob.")


def test_clause_text_and_canonical_link():
    clause = by_id(soliq_kodeksi(), "-7966265")
    assert clause.type == "ACT_TEXT"
    assert clause.kind == lexuz.KIND_TEXT
    assert clause.text.startswith("1) soliq davrida jami daromadi bir milliard soʻmdan oshmagan")
    assert clause.modda_raqami == "461"
    assert clause.parent_element_id == "-4688907"
    assert clause.link == "https://lex.uz/docs/-4674902#-7966265"


def test_all_links_are_canonical():
    doc = soliq_kodeksi()
    for e in doc.elements:
        assert e.link == f"https://lex.uz/docs/{SK_ID}#{e.element_id}"


def test_superscript_article_number():
    doc = soliq_kodeksi()
    heading = next(a for a in doc.articles() if a.modda_raqami == "121-1")
    assert heading.text.startswith("121¹-modda.")


def test_chapter_hierarchy():
    doc = soliq_kodeksi()
    part = next(e for e in doc.elements if e.text == "UMUMIY QISM")
    section = next(e for e in doc.elements if e.text == "I BOʻLIM. UMUMIY QOIDALAR")
    chapter = next(e for e in doc.elements if e.text == "1-bob. Asosiy qoidalar")
    assert part.parent_element_id is None
    assert section.parent_element_id == part.element_id
    assert chapter.parent_element_id == section.element_id


def test_rate_table_keeps_rows_and_columns():
    doc = soliq_kodeksi()
    table = next(e for e in doc.elements if e.kind == lexuz.KIND_TABLE and e.modda_raqami == "289-1")
    lines = table.text.split("\n")
    assert lines[0] == "T/r | Tamaki mahsulotlari turlari | Soliq stavkalari"
    assert lines[1].startswith("1. | Filtrli, filtrsiz sigaretalar")


# --- izohlar (COMMENT, CHANGES_ORIGINS) -----------------------------------


def test_amendment_note_attached_to_previous_element():
    doc = soliq_kodeksi()
    note = by_id(doc, "-7966267")
    assert note.type == "CHANGES_ORIGINS"
    assert note.kind == lexuz.KIND_AMENDMENT
    assert note.text.startswith("(461-moddaning birinchi qismi")
    assert note.parent_element_id == "-7966266"
    assert "OʻRQ-1108" in by_id(doc, "-7966266").amendment_note


def test_previous_edition_comment_attached_to_next_element():
    doc = soliq_kodeksi()
    note = by_id(doc, "edi-7966263")
    assert note.type == "COMMENT"
    assert note.kind == lexuz.KIND_EDITION_NOTE
    assert note.text == "Oldingi tahrirga qarang."
    assert note.parent_element_id == "-7966264"
    assert note.link == "https://lex.uz/docs/-4674902#edi-7966263"
    assert any("ONDATE=" in r for r in note.refs)


def test_future_edition_marked_on_element():
    doc = soliq_kodeksi()
    notes = [e for e in doc.elements if e.kind == lexuz.KIND_EDITION_NOTE and e.future_version]
    assert notes, "kelajakdagi tahrir izohlari topilmadi"
    current = lexuz.pick_version(doc.versions, date(2026, 9, 27))
    for note in notes:
        # Real sahifada ikkala shakl uchraydi: "12.12.2026" va "12.12.2026 01"
        assert note.future_version in doc.versions
        assert note.future_version.split()[0] == "12.12.2026" != current
        assert by_id(doc, note.parent_element_id).future_version == note.future_version


def test_lexuz_commentary_is_kept_separately():
    doc = soliq_kodeksi()
    comments = [e for e in doc.elements if e.kind == lexuz.KIND_LEXUZ_COMMENT]
    assert len(comments) > 100
    owner = by_id(doc, comments[0].parent_element_id)
    assert comments[0].text not in (owner.amendment_note or "")


def test_no_comment_is_dropped():
    """Matnli barcha COMMENT/CHANGES_ORIGINS saqlanadi (Lex.uz'dagi 6 ta bo'sh "LexUZ sharhi"dan tashqari)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fixture_text("soliq-kodeksi.html.gz"), "lxml")
    raw = [
        b.find("div", id=True, recursive=False)
        for b in soup.select("#divCont > div.COMMENT, #divCont > div.CHANGES_ORIGINS")
    ]
    non_empty = {d["id"] for d in raw if d is not None and d.get_text(strip=True)}
    kept = {e.element_id for e in soliq_kodeksi().elements if e.type in ("COMMENT", "CHANGES_ORIGINS")}
    assert kept == non_empty
    assert len(raw) - len(non_empty) == 6


# --- rus tilidagi, kuchini yo'qotgan hujjat --------------------------------


def test_russian_document():
    doc = soliq_kodeksi_2007()
    assert doc.name == "Налоговый кодекс Республики Узбекистан"
    assert doc.adoption_date == date(2007, 12, 25)
    first = doc.articles()[0]
    assert first.modda_raqami == "1"
    assert first.element_path.startswith("ОБЩАЯ ЧАСТЬ > РАЗДЕЛ I. ОБЩИЕ ПОЛОЖЕНИЯ > Глава 1.")
    assert first.bob == "Глава 1. Основные положения"
    assert all(a.modda_raqami for a in doc.articles())
    assert any(a.modda_raqami == "159-1" for a in doc.articles())
    assert all(e.link.startswith("https://lex.uz/docs/1286689#") for e in doc.elements)


# --- kartochka va huquqiy holat --------------------------------------------

TODAY = date(2026, 9, 27)


def card(name: str, doc_id: str) -> lexuz.ActCard:
    return lexuz.parse_card(fixture_text(name), doc_id)


def test_card_current_code():
    c = card("card1-soliq-kodeksi.html", SK_ID)
    assert c.form == "Кодекс"
    assert c.adoption_date == date(2019, 12, 30)
    assert c.status_raw == "Действующий"
    assert c.effective_date == date(2020, 1, 1)
    assert c.repeal_date is None
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_AMALDA


def test_card_with_uzbek_values():
    c = card("card1-soliq-kodeksi-uz-qiymat.html", SK_ID)
    assert c.status_raw == "Amalda"
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_AMALDA


def test_card_decree_number():
    c = card("card1-pf-206.html", "-8509858")
    assert c.number == "206"
    assert c.form == "Указ"
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_AMALDA


def test_future_document_is_not_current_even_if_card_says_active():
    c = card("card1-vm-508-kelajakda.html", "-8503735")
    assert c.status_raw == "Действующий"
    assert c.effective_date == date(2026, 12, 24)
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_KUCHGA_KIRMAGAN
    assert lexuz.resolve_status(c, date(2026, 12, 24)) == lexuz.STATUS_AMALDA


def test_repealed_document():
    c = card("card1-soliq-kodeksi-2007.html", SK2007_ID)
    assert c.status_raw == "Утративший силу"
    assert c.repeal_date == date(2020, 1, 8)
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_KUCHINI_YOQOTGAN


def test_unknown_status_is_not_guessed_from_dates():
    c = lexuz.ActCard(SK_ID, None, None, None, None, None, None, date(2020, 1, 1), None, None)
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_NOMALUM
    c.status_raw = "Действующий"
    c.effective_date = None
    assert lexuz.resolve_status(c, TODAY) == lexuz.STATUS_NOMALUM


# --- versiya tanlash va load ------------------------------------------------


def test_pick_version():
    versions = soliq_kodeksi().versions
    assert lexuz.pick_version(versions, date(2026, 9, 27)) == "06.08.2026"
    assert lexuz.pick_version(versions, date(2026, 7, 30)) == "27.07.2026"
    assert lexuz.pick_version(versions, date(2026, 12, 12)) == "12.12.2026 01"
    assert lexuz.pick_version(["01.01.2020"], date(2019, 1, 1)) is None


def test_doc_url_with_version_token():
    assert lexuz.doc_url(SK_ID, "12.12.2026 01") == "https://lex.uz/docs/-4674902?ONDATE=12.12.2026 01"
    with pytest.raises(ValueError):
        lexuz.doc_url(SK_ID, "2024-12-01")


def _mock_client(pages: dict[str, tuple[int, str]]):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).replace("%20", " ")
        requested.append(url)
        status, body = pages.get(url, (404, "not found"))
        return httpx.Response(status, text=body)

    client = LexUzClient(
        delay_seconds=0, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, requested


def test_load_historical_picks_existing_version():
    html = fixture_text("soliq-kodeksi.html.gz")
    client, requested = _mock_client(
        {
            "https://lex.uz/docs/-4674902": (200, html),
            "https://lex.uz/docs/-4674902?ONDATE=27.07.2026": (200, html),
        }
    )
    doc = lexuz.load(SK_ID, date(2026, 7, 30), client=client)
    assert doc.doc_id == SK_ID
    assert requested == [
        "https://lex.uz/docs/-4674902",
        "https://lex.uz/docs/-4674902?ONDATE=27.07.2026",
    ]


def test_load_before_first_version_raises():
    client, _ = _mock_client({"https://lex.uz/docs/-4674902": (200, fixture_text("soliq-kodeksi.html.gz"))})
    with pytest.raises(LexUzError):
        lexuz.load(SK_ID, date(2010, 1, 1), client=client)


def test_load_http_error():
    client, _ = _mock_client({})
    with pytest.raises(LexUzHTTPError):
        lexuz.load(SK_ID, client=client)


# --- noto'g'ri kirish --------------------------------------------------------


@pytest.mark.parametrize("html", ["", "   ", "<html><body><p>xato</p></body></html>"])
def test_malformed_or_empty_html(html):
    with pytest.raises(LexUzError):
        lexuz.parse_doc(html, SK_ID)


def test_malformed_card():
    with pytest.raises(LexUzError):
        lexuz.parse_card("<html><body>yo'q</body></html>", SK_ID)


def test_broken_element_markup_is_tolerated():
    html = """<html><head><title>01.01.2024. Test hujjat</title></head><body><div id="divCont">
      <div class="CLAUSE_DEFAULT lx_elem"><div id="-1">5-modda. Sinov</div></div>
      <div class="ACT_TEXT lx_elem"><span>ID yo'q</span></div>
      <div class="ACT_TEXT lx_elem"><div id="-2">Matn <b>qalin</b></div></div>
      <div class="COMMENT lx_no_select"><div id="edi-3">Oldingi tahrirga qarang.</div></div>
    </div></body></html>"""
    doc = lexuz.parse_doc(html, "-9")
    assert [e.element_id for e in doc.elements] == ["-1", "-2", "edi-3"]
    assert doc.elements[1].text == "Matn qalin"
    assert doc.elements[1].modda_raqami == "5"
    assert doc.elements[2].parent_element_id == "-2"
