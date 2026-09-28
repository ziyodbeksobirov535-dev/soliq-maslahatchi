"""Soliq kalkulyatori: hisob-kitob, son o'qish va stavkalarning real Soliq kodeksi matni bilan mosligi."""

from decimal import Decimal
from functools import lru_cache

import pytest

from app.services import kalkulyator as k
from tests.test_lexuz_parser import soliq_kodeksi


@lru_cache(maxsize=None)
def article_text(number: str) -> str:
    return "\n".join(e.text for e in soliq_kodeksi().article(number))


@pytest.mark.parametrize("rate", [k.QQS, k.JSHDS, *k.AYLANMA.values()])
def test_rate_quotes_exist_in_real_tax_code(rate):
    assert rate.quote in article_text(rate.modda)
    assert str(rate.percent) in rate.quote  # iqtibosdagi raqam = kodda ishlatiladigan stavka


def test_penya_rule_exists_in_real_tax_code():
    assert k.PENYA_QUOTE in article_text(k.PENYA_MODDA)


@pytest.mark.parametrize("text,value", [
    ("10 000 000", "10000000"), ("10,000,000", "10000000"), ("1 500 000.50", "1500000.50"), ("2500,5", "2500.5"),
    ("10000000 so'm", "10000000"), ("abc", None), ("0", None), ("-5", None), ("", None),
])
def test_parse_amount(text, value):
    assert k.parse_amount(text) == (Decimal(value) if value else None)


def values(result):
    return {name: v for name, v in result.lines}


def test_qqs_add_and_extract_are_inverse():
    add = k.calculate("qqs_qosh", "10 000 000")
    assert values(add) == {"Summa (QQSsiz)": 10_000_000, "QQS (12%)": 1_200_000, "Jami (QQS bilan)": 11_200_000}
    extract = k.calculate("qqs_ajrat", "11 200 000")
    assert values(extract)["shu jumladan QQS (12%)"] == 1_200_000
    assert values(extract)["QQSsiz summa"] == 10_000_000
    assert add.modda == extract.modda == "258"


def test_jshds_and_turnover():
    j = k.calculate("jshds", "5 000 000")
    assert values(j)["JSHDS (12%)"] == 600_000 and values(j)["Qo'lga (JSHDS ushlangandan keyin)"] == 4_400_000
    assert values(k.calculate("aylanma", "50 000 000"))["Soliq (4%)"] == 2_000_000
    assert values(k.calculate("aylanma", "50 000 000", "1"))["Soliq (1%)"] == 500_000


def test_penya():
    r = k.calculate("penya", "10 000 000 30 15")  # 15% / 300 = 0.05% kuniga → 30 kun = 1.5%
    assert values(r)["Penya"] == 150_000 and values(r)["Jami (qarz + penya)"] == 10_150_000
    assert r.modda == "110" and "o'zingiz kiritdingiz" in r.note
    assert k.calculate("penya", "10000000 30") is None
    assert k.calculate("penya", "10000000 0 15") is None


def test_invalid_input_returns_none():
    assert k.calculate("qqs_qosh", "qancha") is None
    assert k.calculate("nomalum", "100") is None


def test_fmt():
    assert k.fmt(Decimal("1234567")) == "1 234 567"
