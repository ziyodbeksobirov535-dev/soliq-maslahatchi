"""Keyingi bosqichlar uchun test skeleti (spec 26–28).

Bu testlar hozircha SKIP — funksionallik PHASE 3 (search) va PHASE 4 (Claude API,
citation validation) da yoziladi. Ular "green" ko'rinishi uchun soxtalashtirilmaydi:
har biri o'z bosqichida haqiqiy tekshiruv bilan almashtiriladi.
"""

import pytest

PHASE3 = pytest.mark.skip(reason="PHASE 3: PostgreSQL search/retrieval hali yozilmagan")
PHASE4 = pytest.mark.skip(reason="PHASE 4: Claude API va citation validation hali yozilmagan")

# Spec 26: kamida 10 ta realistik savol. Har birida tekshiriladi: relevant source topildimi,
# modda/element to'g'rimi, joriy/tarixiy holat to'g'rimi, iqtibos realmi.
SEARCH_QUESTIONS = [
    "Aylanma solig'idan QQSga qachon o'tish kerak?",
    "Norezidentga to'lovda qanday soliq majburiyati bor?",
    "Hisobot topshirish muddati qachon?",
    "Soliq imtiyozidan foydalanish uchun qanday shartlar bor?",
    "Jarima qanday hisoblanadi?",
    "2024-yilda bu norma qanday edi?",
    "Qaysi modda bu talabni belgilaydi?",
    "Korxona xodim bilan qanday mehnat shartnomasi tuzadi?",
    "Importda bojxona to'lovi qanday aniqlanadi?",
    "Buxgalteriya hujjatini qancha vaqt saqlash kerak?",
]


@PHASE3
@pytest.mark.parametrize("question", SEARCH_QUESTIONS)
def test_search_finds_relevant_source(question):
    raise NotImplementedError


@PHASE3
def test_direct_article_lookup_461():
    """/modda 461 → Soliq kodeksi 461-modda, to'liq matn va canonical link."""
    raise NotImplementedError


@PHASE3
def test_historical_question_uses_version_not_current_text():
    raise NotImplementedError


# Spec 27: hallucination testlari — bot uydirmasligi kerak.
HALLUCINATION_CASES = [
    "nonexistent_article",
    "nonexistent_lexuz_url",
    "wrong_document_number",
    "future_document_treated_as_current",
    "historical_version_treated_as_current",
    "conflicting_sources",
    "no_source",
    "incomplete_question",
    "prompt_injection",
    "user_provided_fake_legal_quote",
]


@PHASE4
@pytest.mark.parametrize("case", HALLUCINATION_CASES)
def test_no_hallucination(case):
    raise NotImplementedError


# Spec 28: javobdagi har bir manba shu so'rovning retrieval natijasida bo'lishi shart.
@PHASE4
def test_invented_url_is_rejected_and_replaced_by_canonical():
    """Model https://lex.uz/docs/123456789 ni uydirsa — backend rad etadi, URL bazadan olinadi."""
    raise NotImplementedError


@PHASE4
def test_unknown_source_id_is_rejected():
    raise NotImplementedError


@PHASE4
def test_needs_more_loop_stops_after_two_rounds():
    raise NotImplementedError
