"""Retrieval baholash to'plami (spec 26: kamida 10 ta realistik savol).

Kutilgan moddalar qidiruvdan MUSTAQIL, modda sarlavhalarini o'qib belgilangan (PROGRESS.md).
Har bir savol uchun:
- `expected` — tegishli deb hisoblanadigan (lex_id, modda) juftliklari;
- `primary` — eng to'g'ri javob bo'lishi kerak bo'lgan modda(lar);
- `expected_status` — kutilgan natija turi (ok | needs_clarification | historical_unavailable).
"""

from __future__ import annotations

from dataclasses import dataclass

SK = "-4674902"
MK = "-6257288"
BK = "-2876354"
BX = "-2931253"


@dataclass(frozen=True)
class EvalCase:
    question: str
    expected_status: str
    expected: frozenset[tuple[str, str]] = frozenset()
    primary: frozenset[tuple[str, str]] = frozenset()
    note: str = ""


def _set(lex_id: str, *numbers: str) -> frozenset[tuple[str, str]]:
    return frozenset((lex_id, n) for n in numbers)


CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "Aylanma solig'idan QQSga qachon o'tish kerak?", "ok",
        expected=_set(SK, "461", "462", "237"), primary=_set(SK, "461", "462", "237"),
        note="aylanma soliq to'lovchilari (461), qo'llash xususiyatlari (462), QQS to'lovchilari (237)",
    ),
    EvalCase(
        "Norezidentga to'lovda qanday soliq majburiyati bor?", "ok",
        expected=_set(SK, "351", "352", "353", "354", "355", "356", "357", "358", "400", "401", "241"),
        primary=_set(SK, "351", "353", "356", "400"),
        note="norezident daromadlariga to'lov manbaida soliq (XV bo'lim), JSHDS (400), xizmat joyi (241)",
    ),
    EvalCase(
        "Hisobot topshirish muddati qachon?", "ok",
        expected=_set(SK, "82", "389", "273", "292", "339", "349", "362", "407", "417", "431", "447", "81", "83"),
        primary=_set(SK, "82", "389"),
        note="savol umumiy: soliq hisobotini taqdim etish tartibi/muddatlari",
    ),
    EvalCase(
        "Soliq imtiyozidan foydalanish uchun qanday shartlar bor?", "ok",
        expected=_set(SK, "75", "414", "421", "428", "436", "472", "474", "483"),
        primary=_set(SK, "75"),
    ),
    EvalCase(
        "Jarima qanday hisoblanadi?", "ok",
        expected=_set(SK, "110", "218", "219", "220", "222", "223", "224", "225", "228") | _set(BK, "349"),
        primary=_set(SK, "218", "110"),
        note="moliyaviy sanksiyalar (218) va penya (110)",
    ),
    EvalCase(
        "2024-yilda bu norma qanday edi?", "needs_clarification",
        note="mavzu yo'q + tarixiy: joriy matn bilan javob berilmasligi kerak",
    ),
    EvalCase(
        "Qaysi modda bu talabni belgilaydi?", "needs_clarification",
        note="oldingi kontekstga ishora, mavzu yo'q",
    ),
    EvalCase(
        "Korxona xodim bilan qanday mehnat shartnomasi tuzadi?", "ok",
        expected=_set(MK, "103", "104", "106", "107", "108", "109", "110", "111", "112", "113", "126"),
        primary=_set(MK, "103", "104", "106"),
    ),
    EvalCase(
        "Importda bojxona to'lovi qanday aniqlanadi?", "ok",
        expected=_set(BK, "289", "292", "293", "301", "302", "322", "323", "324", "53"),
        primary=_set(BK, "289", "293", "301", "302", "322", "323"),
    ),
    EvalCase(
        "Buxgalteriya hujjatini qancha vaqt saqlash kerak?", "ok",
        expected=_set(BX, "29") | _set(SK, "84"), primary=_set(BX, "29"),
    ),
)
