"""Skill bilimlari (spec 19): bo'limlarga ajratish, ishoralar, savolga mos bo'lim → Lex.uz moddasi kontekstga."""

from datetime import date

from app.collector.bilimlar import SKILL_FILES, import_knowledge, parse_skill_knowledge
from app.database.connection import connect
from app.retrieval.bilimlar import knowledge_articles, references
from app.retrieval.query import analyze
from tests.conftest import run
from tests.test_lexuz_parser import SK_ID, card, soliq_kodeksi

TODAY = date(2026, 10, 13)


def test_parse_skill_sections():
    records = parse_skill_knowledge()
    assert len(records) == 57
    assert len({r.record_key for r in records}) == len(records)
    assert {r.source for r in records} == {f"skill-bilimlar/{f}" for f in SKILL_FILES}
    assert all("mijozlar" not in r.source and "yangiliklar-manbalari" not in r.source for r in records)
    first = records[0]
    assert first.topic.startswith("Asosiy stavkalar") and "Bilim bazasi" not in first.topic  # fayl sarlavhasisiz


def test_references_in_knowledge_text():
    text = "Norezidentga dividend (**351-modda**), shartnoma (**354, 357, 358-modda**); PF-153 va PQ-179; 339-340-modda"
    assert references(text) == [("modda", "351"), ("modda", "354"), ("modda", "357"), ("modda", "358"),
                                ("PF", "153"), ("PQ", "179"), ("modda", "339"), ("modda", "340")]


def test_knowledge_points_question_to_tax_code_articles(db):
    from app.collector.importer import import_document

    async def go():
        conn = await connect(db)
        try:
            if not await conn.fetchval("SELECT 1 FROM hujjatlar WHERE lex_id = $1", SK_ID):
                await import_document(conn, soliq_kodeksi(), card("card1-soliq-kodeksi.html", SK_ID), TODAY)
            await conn.execute("DELETE FROM bilimlar WHERE turi = 'bilim'")
            n = await import_knowledge(conn, parse_skill_knowledge())
            again = await import_knowledge(conn, parse_skill_knowledge())
            plan = analyze("Norezidentga to'lov manbaida ushlab qolinadigan soliq", TODAY)
            arts = await knowledge_articles(conn, plan, set())
            none = await knowledge_articles(conn, analyze("Mehnat ta'tili necha kun?", TODAY), set())
            return n, again, arts, none
        finally:
            await conn.close()

    n, again, arts, none = run(go())
    assert n == again == 57
    assert arts and all(a.document_lex_id == SK_ID for a in arts) and len(arts) <= 2
    assert {a.number for a in arts} & {"351", "353", "352", "357", "358"}
    assert none == []  # aloqasiz savol — hech narsa qo'shilmaydi


def test_act_band_references():
    text = "chegarasi (461-modda, PF-100 2-band); 6 foizli QQS (PF-100 5-band); PQ-179"
    assert references(text) == [("modda", "461"), ("PF", "100", "2"), ("PF", "100", "5"), ("PQ", "179")]


def test_chapter_ranges_are_not_references():
    assert references("1-bob (1-15-modda); 4-bob (30-60-modda)") == []
    assert references("339-340-modda") == [("modda", "339"), ("modda", "340")]


def test_only_references_near_question_words_are_used():
    from app.retrieval.bilimlar import relevant_references

    text = ("- QQS (umumiy): **12%**\n"
            "- Norezidentga dividend: **10%** (**351-modda**)\n\n"
            "Xato aniqlangan: 461-modda \"1 mlrd so'm\"\n"
            "chegarani ko'rsatadi")
    assert relevant_references(analyze("QQS stavkasi qancha?", TODAY), "Asosiy stavkalar", text) == []
    assert relevant_references(analyze("QQS to'lovchi bo'lish chegarasi", TODAY), "Tuzatish", text) == \
        [("modda", "461")]  # gap ikki qatorga bo'lingan — xatboshi bo'yicha
    assert relevant_references(analyze("Hisobot muddati", TODAY), "QQS (273-modda)", "matn") == \
        [("modda", "273")]  # sarlavhadagi ishora
