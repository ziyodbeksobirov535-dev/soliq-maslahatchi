"""Soliq kodeksi tuzilmasi bo'yicha yo'naltirish: soliq turi + jihat → o'sha bo'limdagi modda."""

from datetime import date

import pytest

from app.retrieval.query import analyze
from app.retrieval.structure import CodeArticle, detect, route

TODAY = date(2026, 10, 13)


def art(order, number, heading, bob, section):
    return CodeArticle(order, number, heading, bob, section)


QQS = "x bolim. qoshilgan qiymat soligi"
MOL = "xv bolim. mol-mulk soligi"
AYL = "xx bolim. aylanmadan olinadigan soliq"
ARTICLES = [
    art(1, "237", "237-modda. soliq tolovchilar", "31-bob. soliq tolovchilar va soliq solish obyekti", QQS),
    art(2, "243", "243-modda. soliq solishdan ozod etiladigan tovarlarni realizatsiya qilish boyicha aylanma",
        "33-bob. soliq solishdan ozod etiladigan aylanmalar", QQS),
    art(3, "244", "244-modda. soliq solishdan ozod etiladigan moliyaviy xizmatlar", "33-bob. ozod", QQS),
    art(4, "258", "258-modda. soliq stavkalari", "35-bob. soliq stavkalari. soliq davri", QQS),
    art(5, "278", "278-modda. soliq tolovchilar",
        "39-bob. elektron shaklda xizmatlar korsatuvchi chet el yuridik shaxslari", QQS),
    art(10, "410", "410-modda. soliq tolovchilar", "59-bob. yuridik shaxslarning mol-mulkiga solinadigan soliq", MOL),
    art(11, "415", "415-modda. soliq stavkalari", "59-bob. yuridik shaxslarning mol-mulkiga solinadigan soliq", MOL),
    art(12, "418", "418-modda. soliq tolovchilar", "60-bob. jismoniy shaxslarning mol-mulkiga solinadigan soliq",
        MOL),
    art(13, "422", "422-modda. soliq stavkalari. soliq davri",
        "60-bob. jismoniy shaxslarning mol-mulkiga solinadigan soliq", MOL),
    art(20, "461", "461-modda. soliq tolovchilar", "66-bob. aylanmadan olinadigan soliq", AYL),
    art(21, "467", "467-modda. soliq stavkalari", "66-bob. aylanmadan olinadigan soliq", AYL),
]


@pytest.mark.parametrize("question,expected", [
    ("Aylanma solig'ini kimlar to'laydi?", ["461"]),  # leksik qidiruv "aylanma" (oborot) moddalarini berardi
    ("QQSni kim to'laydi?", ["237"]),
    ("Qo'shilgan qiymat solig'i stavkasi necha foiz?", ["258"]),
    ("Moliyaviy xizmatlar QQSdan ozodmi?", ["244", "243"]),  # savol so'zlari sarlavhaga ko'proq mos — birinchi
    ("Uyim uchun mol-mulk solig'ini kim to'laydi?", ["418"]),  # "uy" — jismoniy shaxslar bobi
    ("Korxona mol-mulk solig'i stavkasi", ["415"]),
    ("Firmam QQS to'lovchi bo'ladimi?", ["237"]),  # "firma" QQS'da bob tanlamaydi (278 — chet el kompaniyalari)
    ("Кто платит налог с оборота?", ["461"]),
    ("Налог на имущество для физических лиц", ["418", "422"]),  # jihatsiz — to'lovchilar va stavkalar
])
def test_route(question, expected):
    assert route(analyze(question, TODAY), ARTICLES) == expected


@pytest.mark.parametrize("question", [
    "Aylanma solig'idan QQSga qachon o'tish kerak?",  # ikki soliq, jihat yo'q, boshqa mazmunli so'z bor
    "Yillik aylanmam 5 mlrd",  # soliq nomi yo'q ("aylanma" — oborot)
    "Mehnat ta'tili necha kun?",
])
def test_no_route(question):
    assert route(analyze(question, TODAY), ARTICLES) == []


def test_detect_tax_and_aspect():
    assert detect(analyze("Yer qa'ridan foydalanganlik uchun soliqni kim to'laydi?", TODAY)) == \
        (["yer qa'ri"], ["tolovchi"])
    assert detect(analyze("Jismoniy shaxslar yer solig'ini qachon to'laydi?", TODAY)) == (["yer"], ["tolash"])
    assert detect(analyze("NDS stavkasi qancha?", TODAY)) == (["qqs"], ["stavka"])
