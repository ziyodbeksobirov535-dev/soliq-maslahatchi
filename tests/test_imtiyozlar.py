"""Rasmiy imtiyozlar ro'yxati (spec 19): import, kirill → lotin, imtiyoz savolida moddalar kontekstga."""

from datetime import date

import pytest

from app.collector.bilimlar import import_records, latin, parse_imtiyozlar
from app.database.connection import connect
from app.retrieval.imtiyozlar import article_refs, find_benefits, is_benefit_question, topic_terms
from app.retrieval.query import analyze
from tests.conftest import run

TODAY = date(2026, 10, 13)


@pytest.mark.parametrize("cyr,lat", [
    ("Қўшилган қиймат солиғи", "Qoʻshilgan qiymat soligʻi"),
    ("ЖШДС", "JShDS"),  # rasmiy lotin qisqartmasi shunday
    ("Ер солиғи", "Yer soligʻi"),
    ("объектидир", "obʼektidir"),
])
def test_latin_keeps_case_and_apostrophes(cyr, lat):
    assert latin(cyr) == lat


def test_parse_real_csv():
    records = parse_imtiyozlar()
    assert len(records) == 507
    assert len({r.record_key for r in records}) == 507
    sk = [r for r in records if r.modda_raqami]
    assert len(sk) == 322 and all(r.lex_id == "-4674902" for r in sk)
    first = records[0]
    assert first.modda_raqami == "238" and first.topic == "Qoʻshilgan qiymat soligʻi imtiyozi"
    assert first.text.startswith("(SK 238-m.)") and first.asl_matn.startswith("(СК 238-м.)")
    assert all(r.amal_muddati for r in records)


def test_benefit_question_detection():
    assert is_benefit_question(analyze("Qishloq xo'jaligi uchun qanday soliq imtiyozlari bor?", TODAY))
    assert is_benefit_question(analyze("QQSdan ozod qilinadigan tovarlar", TODAY))
    assert not is_benefit_question(analyze("QQS stavkasi qancha?", TODAY))
    assert topic_terms(analyze("Qishloq xo'jaligi uchun qanday soliq imtiyozlari bor?", TODAY)) == \
        ["qishlo:*", "xojali:*"]


def test_find_benefits_skips_expired_and_points_to_articles(db):
    records = [r for r in parse_imtiyozlar() if "қишлоқ хўжалиги" in r.asl_matn.lower()]
    assert records

    async def go():
        conn = await connect(db)
        try:
            await conn.execute("DELETE FROM bilimlar")
            await import_records(conn, records)
            again = await import_records(conn, records)  # idempotent
            n = await conn.fetchval("SELECT count(*) FROM bilimlar WHERE turi = 'imtiyoz'")
            plan = analyze("Qishloq xo'jaligi uchun qanday soliq imtiyozlari bor?", TODAY)
            found = await find_benefits(conn, plan, TODAY)
            expired = await find_benefits(conn, plan, date(2100, 1, 1))
            return again, n, found, expired
        finally:
            await conn.close()

    again, n, found, expired = run(go())
    assert again == n == len(records)
    assert found and all("qishloq xoʻjaligi" in r.text.lower() for r in found)
    assert expired == []  # muddati o'tgan bandlar ko'rsatilmaydi
    refs = article_refs(found)
    assert refs and all(lex == "-4674902" for lex, _ in refs) and len(refs) <= 3
