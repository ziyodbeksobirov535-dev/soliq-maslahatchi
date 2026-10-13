"""Modda havolalari zanjiri: real Soliq kodeksi matnidagi shakllar va kontekstga qo'shish."""

from datetime import date

import pytest

from app.database.connection import connect
from app.retrieval.references import find_references
from app.services.answer import article_to_source, referenced_sources
from tests.conftest import run
from tests.test_lexuz_parser import SK_ID, soliq_kodeksi

SK = "-4674902"


@pytest.mark.parametrize("text,expected", [
    ("ushbu Kodeksning 57-moddasida nazarda tutilgan mezonlarga javob beruvchi", [(SK, "57")]),
    ("Ushbu Kodeks 461-moddasi birinchi qismining 1-bandida", [(SK, "461")]),
    ("ushbu Kodeksning 104 va 105-moddalarida belgilangan tartibda", [(SK, "104"), (SK, "105")]),
    ("ushbu Kodeksning 121¹-moddasida nazarda tutilgan", [(SK, "121-1")]),
    ("mazkur Kodeksning 313-moddasi", [(SK, "313")]),
    ("O'zbekiston Respublikasi Soliq kodeksining 337-moddasi", [(SK, "337")]),
    ("Mehnat kodeksining 106-moddasiga muvofiq", [("-6257288", "106")]),
    ("ushbu Kodeksning 36-bobida", []),  # bob — modda emas
    ("ushbu moddaning ikkinchi qismi", []),
    ("25-moddasida", []),  # qaysi hujjat — noma'lum
])
def test_find_references(text, expected):
    assert find_references(text, SK) == expected


def test_real_article_337_points_to_57():
    text = "\n".join(e.text for e in soliq_kodeksi().article("337"))
    assert (SK, "57") in find_references(text, SK)


def test_profit_tax_rate_context_gets_referenced_article(db):
    from app.collector.importer import import_document
    from app.retrieval.articles import get_article
    from tests.test_lexuz_parser import card

    async def go():
        conn = await connect(db)
        try:
            if not await conn.fetchval("SELECT 1 FROM hujjatlar WHERE lex_id = $1", SK_ID):
                await import_document(conn, soliq_kodeksi(), card("card1-soliq-kodeksi.html", SK_ID), date(2026, 9, 27))
            a337 = article_to_source(await get_article(conn, "337", SK))
            return await referenced_sources(conn, [a337], [])
        finally:
            await conn.close()

    added = run(go())
    assert [a.modda_raqami for a in added][:1] == ["57"]
    assert len(added) <= 2
