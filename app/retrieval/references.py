"""Modda havolalari zanjiri: kontekstdagi moddada boshqa moddaga ishora bo'lsa, o'sha modda ham kontekstga qo'shiladi.

    337-modda: "...ushbu Kodeksning 57-moddasida nazarda tutilgan mezonlarga javob beruvchi..." → 57-modda

Shakllar real Soliq kodeksi matnidan (2026-10-13): "ushbu Kodeksning 57-moddasida" (337 marta), "ushbu Kodeks
461-moddasi" (145), "mazkur Kodeksning ...", ro'yxat "104 va 105-moddalarida", "121¹-moddasida". Qarorlarda —
"Soliq kodeksining 461-moddasi" (boshqa hujjatga havola). Faqat aniq hujjatga bog'langan havolalar olinadi
("ushbu/mazkur Kodeks/Qonun" — o'sha hujjat; "Soliq/Mehnat/Bojxona kodeksining" — o'sha kodeks); "36-bobida",
"ushbu moddaning" kabilar olinmaydi. Havolalar avval savolga mos elementlardan, keyin moddaning qolganidan.
"""

from __future__ import annotations

import re

import asyncpg

from app.retrieval.articles import Article, get_article, normalize_article_number
from app.retrieval.query import normalize

MAX_REFERENCED = 2
_NUM = r"\d{1,3}[¹²³⁴⁵⁶⁷⁸⁹]?"
_LIST = rf"((?:{_NUM}(?:\s*,\s*|\s+va\s+|\s+hamda\s+))*{_NUM})-modda"
_SAME_DOC_RE = re.compile(rf"(?:ushbu|mazkur)\s+(?:kodeks|qonun)(?:ning)?\s+{_LIST}")
_OTHER_DOC_RE = re.compile(rf"(soliq|mehnat|bojxona)\s+kodeksining\s+{_LIST}")
CODE_LEX_IDS = {"soliq": "-4674902", "mehnat": "-6257288", "bojxona": "-2876354"}


def find_references(text: str, own_lex_id: str) -> list[tuple[str, str]]:
    """Matndagi modda havolalari: [(lex_id, modda_raqami)], tartib bo'yicha, takrorsiz."""
    norm = normalize(text)
    found: list[tuple[int, str, str]] = []
    for m in _SAME_DOC_RE.finditer(norm):
        found += [(m.start(), own_lex_id, n) for n in re.findall(_NUM, m.group(1))]
    for m in _OTHER_DOC_RE.finditer(norm):
        found += [(m.start(), CODE_LEX_IDS[m.group(1)], n) for n in re.findall(_NUM, m.group(2))]
    out: list[tuple[str, str]] = []
    for _, lex_id, raw in sorted(found):
        number = normalize_article_number(raw)
        if number and (lex_id, number) not in out:
            out.append((lex_id, number))
    return out


async def referenced_articles(conn: asyncpg.Connection, sources: list[tuple[str, str | None, list[str]]],
                              limit: int = MAX_REFERENCED) -> list[Article]:
    """sources: [(lex_id, modda yoki None, [matnlar — avval savolga mos elementlar])]. Kontekstda yo'q,
    bazada bor moddalar (ko'pi bilan `limit`)."""
    present = {(lex_id, number) for lex_id, number, _ in sources if number}
    out: list[Article] = []
    for lex_id, _, texts in sources:
        for text in texts:
            for ref in find_references(text, lex_id):
                if ref in present or len(out) >= limit:
                    continue
                present.add(ref)
                article = await get_article(conn, ref[1], ref[0])
                if article is not None:
                    out.append(article)
    return out
