"""Keyingi bosqichlar uchun test skeleti (spec 27–28).

Bu testlar hozircha SKIP — funksionallik PHASE 4 (Claude API, citation validation) da yoziladi. Ular "green" ko'rinishi uchun soxtalashtirilmaydi:
har biri o'z bosqichida haqiqiy tekshiruv bilan almashtiriladi.
"""

import pytest

PHASE4 = pytest.mark.skip(reason="PHASE 4: Claude API va citation validation hali yozilmagan")

# PHASE 3 (search) testlari haqiqiy testlar bilan almashtirildi: tests/test_search.py,
# 10 savol bo'yicha hisobot: docs/retrieval_report.md.


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
