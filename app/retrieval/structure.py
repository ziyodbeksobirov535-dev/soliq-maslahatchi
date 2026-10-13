"""Soliq kodeksi tuzilmasi bo'yicha yo'naltirish: savolda soliq turi va jihat bo'lsa — o'sha soliq bo'limidagi mos modda.

    "Aylanma solig'ini kimlar to'laydi?" → soliq: aylanma (XX bo'lim), jihat: to'lovchilar
                                         → XX bo'limdagi "Soliq to'lovchilar" sarlavhali modda → 461-modda

Har bir soliq bo'limi bir xil qolipda: to'lovchilar, obyekt, baza, imtiyozlar, stavkalar, davr, hisobot va to'lash
tartibi. Leksik qidiruv "kim to'laydi" ma'nosini topa olmaydi (2026-10-13 sinov: "aylanma" so'zi 243/268-moddalarda
oborot ma'nosida ko'p uchrab, 461 top-6 ga kirmasdi). Modda raqami o'ylab topilmaydi: bo'lim sarlavhasi va modda
sarlavhasi bazadagi Lex.uz matnidan (bo'lim chegarasi — "X BO'LIM. ..." sarlavhalari) olinadi.

- Bo'limda bir xil sarlavhali moddalar bir nechta bo'lsa (mol-mulk solig'i: yuridik 410, jismoniy 418) — savol
  so'zlari bob nomi va modda sarlavhasiga ko'proq mos kelgani; teng bo'lsa — birinchisi. "Uy", "fuqaro" kabi
  so'zlar "jismoniy", "korxona", "firma" — "yuridik" deb hisoblanadi.
- Jihat bo'yicha ko'pi bilan 1 modda (imtiyozlar — 2), jami ko'pi bilan MAX_ARTICLES.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import asyncpg

from app.retrieval.query import QueryPlan, normalize

SK = "-4674902"
MAX_ARTICLES = 3
CACHE_SECONDS = 3600

# Soliq turi: (kalit, savoldagi belgi, bo'lim sarlavhasi). Savol matni normallashtirilgan, to'liq nomlar
# qisqartmaga keltirilgan ("qo'shilgan qiymat solig'i" → "qqs").
TAXES: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    ("qqs", re.compile(r"\bqqs"), re.compile(r"bolim\. qoshilgan qiymat soligi")),
    ("aksiz", re.compile(r"\baksiz"), re.compile(r"bolim\. aksiz soligi")),
    ("foyda", re.compile(r"\bfoyda\w*\s+(olinadigan\s+)?soli"), re.compile(r"bolim\. foyda soligi")),
    ("jshds", re.compile(r"\bjshds|\bdaromad soli"), re.compile(r"bolim\. jismoniy shaxslardan olinadigan daromad")),
    ("ijtimoiy", re.compile(r"\bijtimoiy soli"), re.compile(r"bolim\. ijtimoiy soliq")),
    ("mol-mulk", re.compile(r"\bmol\W*mulk\w*\s+soli|\bmulk soli"), re.compile(r"bolim\. mol\W*mulk soligi")),
    ("yer qa'ri", re.compile(r"\byer qari"), re.compile(r"bolim\. yer qaridan")),
    ("yer", re.compile(r"\byer\w*\s+soli"), re.compile(r"bolim\. yer soligi")),
    ("suv", re.compile(r"\bsuv\s+resurs|\bsuv\w*\s+soli"), re.compile(r"bolim\. suv resurslaridan")),
    ("renta", re.compile(r"\brenta\b"), re.compile(r"bolim\. foydali qazilmalarni")),
    ("aylanma", re.compile(r"\baylanma\w*\s+(olinadigan\s+)?soli|\baylanmadan\b"),
     re.compile(r"bolim\. aylanmadan olinadigan soliq")),
)


def _is_payer(n: str) -> bool:
    return bool(re.search(r"\btolovchi", n) or (re.search(r"\bkim(lar|ga)?\b", n) and re.search(r"\btol[ao]", n)))


# Jihat: (kalit, savoldagi belgi, modda sarlavhasi, ko'pi bilan nechta modda).
ASPECTS: tuple[tuple[str, object, re.Pattern[str], int], ...] = (
    ("tolovchi", _is_payer, re.compile(r"modda\. soliq tolovchilar$"), 1),
    ("stavka", re.compile(r"\bstav|\bnecha foiz|\bqancha foiz|\bfoizi\b|\bqancha soliq|\bnecha pul soliq"),
     re.compile(r"soliq stavka"), 1),
    ("obyekt", re.compile(r"\bobyekt|\bnima(lar)?ga soli|\bnima(lar)? soliqqa tortil"),
     re.compile(r"soliq solish obyekti"), 1),
    ("baza", re.compile(r"\bbaza"), re.compile(r"modda\. soliq bazasi"), 1),
    ("davr", re.compile(r"\bdavri\b"), re.compile(r"soliq davri|hisobot davri"), 1),
    ("imtiyoz", re.compile(r"\bimtiyoz|\bozod|\bpreferens|\bsolinmay|\btortilmay|\bolinmay"),
     re.compile(r"imtiyoz|ozod|solinmaydigan|hisobga olinmaydigan"), 2),
    ("tolash", re.compile(r"\bqachon\b.*\b(tola|topshir|taqdim)|\b(tola|topshir)\w* muddat|\btolash tartib"
                          r"|\bqanday tola|\bhisobot\w* (qachon|qanday|muddat)|\bdeklaratsiya\w* (qachon|muddat)"
                          r"|\bmuddat\w* (hisobot|tola|topshir)"),
     re.compile(r"tolash tartibi|tolash muddat|hisobotini taqdim|hisobotlarini taqdim|deklaratsiya"), 1),
    ("hisoblash", re.compile(r"\bqanday hisobla|\bhisoblab chiqar|\bhisoblash tartib"),
     re.compile(r"hisoblab chiqarish"), 1),
    ("qaytarish", re.compile(r"\bqaytar"), re.compile(r"ornini qoplash|qaytarish"), 1),
    ("import", re.compile(r"\bimport|\bolib kir"), re.compile(r"olib kir"), 2),
)
# Jihatsiz, faqat soliq nomi (va shaxs turi) bo'lgan savol — kirish moddalari: to'lovchilar va stavkalar.
DEFAULT_ASPECTS = ("tolovchi", "stavka")
# Bob tanlash uchun savoldagi shaxs turi: "uyim", "fuqaro" — jismoniy shaxs; "korxona", "firma" — yuridik.
# Faqat yuridik/jismoniy shaxslar uchun alohida boblari bor soliqlarda ("firma" QQS savolida 278-moddani — chet el
# yuridik shaxslari bobini — tanlatib qo'ygan edi).
PERSON_SPLIT = frozenset({"mol-mulk", "yer"})
PERSON_HINTS = ((re.compile(r"\buy\w*|\bxonadon|\bkvartira|\bfuqaro|\bhovli|\bdehqon|\bjismoniy"), "jismoniy"),
                (re.compile(r"\bkorxona|\bfirma|\btashkilot|\bmchj|\byuridik|\bkompaniya"), "yuridik"))


@dataclass(frozen=True)
class CodeArticle:
    order_no: int
    number: str
    heading: str  # normallashtirilgan
    bob: str  # normallashtirilgan
    section: str  # bo'lim sarlavhasi, normallashtirilgan


_cache: dict[str, tuple[float, list[CodeArticle]]] = {}


async def code_articles(conn: asyncpg.Connection, lex_id: str = SK) -> list[CodeArticle]:
    """Kodeks moddalari bo'lim bilan (bo'lim — undan oldingi oxirgi "... BO'LIM." sarlavhasi). Bir soat keshlanadi."""
    cached = _cache.get(lex_id)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    rows = await conn.fetch(
        """
        SELECT e.order_no, e.kind, e.text, e.modda_raqami, e.bob
        FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id
        WHERE h.lex_id = $1 AND h.status = 'amalda'
          AND (e.kind = 'article' OR (e.kind = 'header' AND e.text ~* 'BO.LIM\\.'))
        ORDER BY e.order_no
        """,
        lex_id,
    )
    out: list[CodeArticle] = []
    section = ""
    for r in rows:
        if r["kind"] == "header":
            section = normalize(r["text"])
        elif r["modda_raqami"]:
            out.append(CodeArticle(r["order_no"], r["modda_raqami"], normalize(r["text"]), normalize(r["bob"] or ""),
                                   section))
    _cache[lex_id] = (time.monotonic(), out)
    return out


def detect(plan: QueryPlan) -> tuple[list[str], list[str]]:
    """Savoldagi soliq turlari va jihatlar (kalitlar)."""
    n = plan.normalized
    taxes = [key for key, mark, _ in TAXES if mark.search(n)]
    if "yer qa'ri" in taxes and "yer" in taxes:
        taxes.remove("yer")
    aspects = [key for key, mark, _, _ in ASPECTS if (mark(n) if callable(mark) else mark.search(n))]
    return taxes[:2], aspects[:2]


def _overlap(plan: QueryPlan, text: str, hints: list[str]) -> int:
    words = text.split()
    stems = [[t, *plan.variants.get(t, [])] for t in plan.terms if t != "soli"] + [[h] for h in hints]
    return sum(any(w.startswith(f) for f in forms for w in words) for forms in stems)


# Soliq nomlari va shaxs turini tashkil qiluvchi o'zaklar (jihatsiz savolni aniqlash uchun).
TAX_NAME_STEMS = frozenset({"soli", "qqs", "jshds", "aksiz", "foyda", "daromad", "ijtimoiy", "mol", "mulk", "yer",
                            "qari", "foydalan", "suv", "resurs", "renta", "aylanma", "olin", "jismoniy", "yuridi",
                            "shaxs", "haqida", "malumot"})


def _only_tax_words(plan: QueryPlan) -> bool:
    """Savolda soliq nomi va shaxs turidan boshqa mazmunli so'z yo'q ("Jismoniy shaxslar mol-mulk solig'i")."""
    return all(t in TAX_NAME_STEMS for t in plan.terms)


def route(plan: QueryPlan, articles: list[CodeArticle]) -> list[str]:
    """Mos moddalar raqamlari (ustuvorlik tartibida)."""
    taxes, aspects = detect(plan)
    if len(taxes) == 1 and not aspects and _only_tax_words(plan):
        aspects = list(DEFAULT_ASPECTS)
    if not taxes or not aspects:
        return []
    person = [h for pattern, h in PERSON_HINTS if pattern.search(plan.normalized)]
    out: list[str] = []
    # To'lash va hisobot — alohida moddalar ("Soliqni to'lash tartibi" / "Soliq hisobotini taqdim etish tartibi"):
    # savolda qaysi biri so'ralgani ("to'lanadi" yoki "topshiriladi") bo'yicha.
    pay = (["tolash"] if re.search(r"\btola|\btolov", plan.normalized) else []) + \
          (["hisobot"] if re.search(r"\bhisobot|\btopshir|\btaqdim|\bdeklarats", plan.normalized) else [])
    for tax in taxes:
        hints = person if tax in PERSON_SPLIT else []
        section_re = next(s for key, _, s in TAXES if key == tax)
        in_section = [a for a in articles if section_re.search(a.section)]
        for aspect in aspects:
            _, _, heading_re, limit = next(x for x in ASPECTS if x[0] == aspect)
            found = [a for a in in_section if heading_re.search(a.heading)]
            heading_hints = pay if aspect == "tolash" else []  # bob nomida ikkalasi ham bo'lishi mumkin
            found.sort(key=lambda a: (-_overlap(plan, f"{a.bob} {a.heading}", hints),
                                      -sum(h in a.heading for h in heading_hints), a.order_no))
            out += [a.number for a in found[:limit] if a.number not in out]
    return out[:MAX_ARTICLES]


async def structural_articles(conn: asyncpg.Connection, plan: QueryPlan) -> list[str]:
    taxes, _ = detect(plan)
    if not taxes:
        return []
    return route(plan, await code_articles(conn))
