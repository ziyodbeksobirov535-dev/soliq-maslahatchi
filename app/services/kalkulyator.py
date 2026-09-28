"""Soliq kalkulyatori (/hisobla): QQS, JSHDS, aylanma solig'i, penya — formula va manba moddasi bilan.

Stavkalar xotiradan emas: har biri Soliq kodeksining joriy matnidagi aniq jumla bilan bog'langan (`quote`).
tests/test_kalkulyator.py bu jumlalar real Lex.uz matnida (tests/fixtures/lexuz/soliq-kodeksi.html.gz)
borligini tekshiradi — qonun o'zgarib fixture yangilansa, test yiqilib stavkani qayta ko'rishni talab qiladi.
Javobdagi havola — bazadagi modda havolasi (get_article). Penya uchun Markaziy bank qayta moliyalash stavkasi
tashqi ko'rsatkich — foydalanuvchi o'zi kiritadi (110-modda: uning uch yuzdan biri).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SK = "-4674902"
MAX_AMOUNT = Decimal("1e15")


@dataclass(frozen=True)
class Rate:
    percent: Decimal
    modda: str
    quote: str  # moddadagi aynan jumla (test real matnda tekshiradi)


QQS = Rate(Decimal("12"), "258", "soliq stavkasi 12 foiz miqdorida belgilanadi")
JSHDS = Rate(Decimal("12"), "381", "12 foizlik soliq stavkasi boʻyicha soliq solinadi")
AYLANMA = {
    "4": Rate(Decimal("4"), "467", "Iqtisodiyotning barcha tarmoqlaridagi soliq toʻlovchilar, bundan 2 — 5-bandlarda "
                                   "nazarda tutilganlar mustasno | 4"),
    "2": Rate(Decimal("2"), "467", "boshqa aholi punktlarida | 2"),
    "1": Rate(Decimal("1"), "467", "borish qiyin boʻlgan va togʻli tumanlarda | 1"),
}
AYLANMA_TITLES = {
    "4": "4% — umumiy (chakana savdo: 100 ming+ aholili shaharlarda ham)",
    "2": "2% — chakana savdo, boshqa aholi punktlarida",
    "1": "1% — chakana savdo, borish qiyin va tog'li tumanlarda",
}
PENYA_MODDA = "110"
PENYA_QUOTE = "qayta moliyalash stavkasining uch yuzdan biriga teng"

KINDS = {
    "qqs_qosh": "QQS qo'shish (summa QQSsiz)",
    "qqs_ajrat": "QQSni ajratish (summa QQS bilan)",
    "jshds": "JSHDS (ish haqidan)",
    "aylanma": "Aylanma solig'i",
    "penya": "Penya",
}
PROMPTS = {
    "qqs_qosh": "QQSsiz summani yozing (so'mda), masalan: <b>10 000 000</b>",
    "qqs_ajrat": "QQS bilan birga summani yozing (so'mda), masalan: <b>11 200 000</b>",
    "jshds": "Hisoblangan ish haqini yozing (so'mda), masalan: <b>5 000 000</b>",
    "aylanma": "Hisobot davridagi daromad (aylanma) summasini yozing (so'mda), masalan: <b>50 000 000</b>",
    "penya": ("Uch sonni probel bilan yozing: <b>qarz summasi, kechiktirilgan kunlar, Markaziy bank qayta "
              "moliyalash stavkasi (%)</b>.\nMasalan: <b>10 000 000 30 14</b>"),
}


@dataclass(frozen=True)
class Result:
    title: str
    lines: list[tuple[str, Decimal]]  # (nomi, summa)
    formula: str
    modda: str
    note: str | None = None


def parse_amount(text: str) -> Decimal | None:
    """"10 000 000", "10,000,000", "1 500 000.50", "10000000 so'm" → Decimal; noto'g'ri — None."""
    cleaned = re.sub(r"(so'?m|sum|сўм|сум)\s*$", "", (text or "").strip().lower()).strip()
    cleaned = cleaned.replace(" ", " ").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", cleaned):
        cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if 0 < value < MAX_AMOUNT else None


def parse_penya_args(text: str) -> tuple[Decimal, int, Decimal] | None:
    """"10 000 000 30 14" — oxirgi ikki son: kunlar va stavka; qolgani — summa."""
    tokens = (text or "").replace("%", " ").split()
    if len(tokens) < 3:
        return None
    amount = parse_amount(" ".join(tokens[:-2]))
    try:
        days = int(tokens[-2])
        rate = Decimal(tokens[-1].replace(",", "."))
    except (ValueError, InvalidOperation):
        return None
    if amount is None or not 0 < days <= 3650 or not 0 < rate < 100:
        return None
    return amount, days, rate


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calculate(kind: str, text: str, aylanma_rate: str = "4") -> Result | None:
    if kind == "penya":
        args = parse_penya_args(text)
        if args is None:
            return None
        amount, days, cb_rate = args
        daily = cb_rate / Decimal(300)
        penya = amount * daily / 100 * days
        return Result("Penya", [("Qarz summasi", amount), ("Penya", _money(penya)),
                                ("Jami (qarz + penya)", _money(amount + penya))],
                      f"qarz × ({cb_rate}% ÷ 300) × {days} kun = qarz × {daily.quantize(Decimal('0.0001'))}% × {days}",
                      PENYA_MODDA, "Markaziy bank qayta moliyalash stavkasini o'zingiz kiritdingiz — "
                                   "kechiktirilgan davrdagi amaldagi stavkani tekshiring.")
    amount = parse_amount(text)
    if amount is None:
        return None
    if kind == "qqs_qosh":
        tax = amount * QQS.percent / 100
        return Result("QQS qo'shish", [("Summa (QQSsiz)", _money(amount)), (f"QQS ({QQS.percent}%)", _money(tax)),
                                       ("Jami (QQS bilan)", _money(amount + tax))],
                      f"QQS = summa × {QQS.percent}%", QQS.modda)
    if kind == "qqs_ajrat":
        tax = amount * QQS.percent / (100 + QQS.percent)
        return Result("QQSni ajratish", [("Summa (QQS bilan)", _money(amount)), (f"shu jumladan QQS ({QQS.percent}%)", _money(tax)),
                                         ("QQSsiz summa", _money(amount - tax))],
                      f"QQS = summa × {QQS.percent} ÷ {100 + QQS.percent}", QQS.modda)
    if kind == "jshds":
        tax = amount * JSHDS.percent / 100
        return Result("JSHDS", [("Hisoblangan ish haqi", _money(amount)), (f"JSHDS ({JSHDS.percent}%)", _money(tax)),
                                ("Qo'lga (JSHDS ushlangandan keyin)", _money(amount - tax))],
                      f"JSHDS = ish haqi × {JSHDS.percent}%", JSHDS.modda,
                      "Rezident jismoniy shaxs uchun. Boshqa ushlanmalar va imtiyozlar hisobga olinmagan.")
    if kind == "aylanma":
        rate = AYLANMA.get(aylanma_rate, AYLANMA["4"])
        tax = amount * rate.percent / 100
        return Result("Aylanma solig'i", [("Daromad (aylanma)", _money(amount)), (f"Soliq ({rate.percent}%)", _money(tax))],
                      f"soliq = daromad × {rate.percent}%", rate.modda,
                      "Stavka faoliyat turi va joylashuvga bog'liq — 467-moddadagi jadvalni tekshiring.")
    return None


def fmt(value: Decimal) -> str:
    """1234567 → "1 234 567"."""
    return f"{value:,.0f}".replace(",", " ")
