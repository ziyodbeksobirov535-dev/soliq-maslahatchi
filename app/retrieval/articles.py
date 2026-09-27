"""Modda bo'yicha to'g'ridan-to'g'ri qidiruv (`/modda 461`, spec 6 va 20-bo'lim).

Faqat bazadagi elementlar qaytariladi; havolalar ham bazadan (parser Lex.uz ID'sidan qurgan).
Modda topilmasa — None (bot "topilmadi" deydi, taxmin qilmaydi).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import asyncpg

SOLIQ_KODEKSI_LEX_ID = "-4674902"

_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
# "461", "121-1", "121¹", "121 1", "461-modda", "modda 461"
_NUMBER_RE = re.compile(r"^\s*(?:modda\s+)?(\d{1,4})(?:\s*[-.\s]\s*(\d{1,2})|([⁰¹²³⁴⁵⁶⁷⁸⁹]+))?\s*(?:-?\s*modda)?\s*$", re.I)

# Modda matni sifatida ko'rsatiladigan turlar (izohlar alohida qaytariladi).
_BODY_KINDS = ("article", "text", "table", "footnote")
_NOTE_KINDS = ("amendment", "edition_note", "lexuz_comment")


@dataclass(frozen=True)
class ArticleElement:
    id: int
    element_id: str
    kind: str
    text: str
    link: str
    parent_element_id: str | None
    amendment_note: str | None
    future_version: str | None


@dataclass(frozen=True)
class Article:
    document_lex_id: str
    document_name: str
    document_status: str
    current_version: str | None
    number: str
    heading: ArticleElement
    body: list[ArticleElement]  # sarlavhadan keyingi matn, tartib bo'yicha
    notes: list[ArticleElement]  # o'zgartirish manbalari, tahrir havolalari, LexUZ sharhlari

    @property
    def link(self) -> str:
        return self.heading.link

    @property
    def has_future_changes(self) -> bool:
        return any(e.future_version for e in (self.heading, *self.body))


def normalize_article_number(value: str) -> str | None:
    """Foydalanuvchi yozgan modda raqamini bazadagi shaklga keltiradi ("121¹" → "121-1")."""
    m = _NUMBER_RE.match(value or "")
    if not m:
        return None
    main, sub, sup = m.groups()
    if sup:
        sub = sup.translate(_SUPERSCRIPT_DIGITS)
    return f"{int(main)}-{int(sub)}" if sub else str(int(main))


async def get_article(
    conn: asyncpg.Connection, number: str, lex_id: str = SOLIQ_KODEKSI_LEX_ID
) -> Article | None:
    normalized = normalize_article_number(number)
    if normalized is None:
        return None
    doc = await conn.fetchrow(
        "SELECT id, name, status, current_version FROM hujjatlar WHERE lex_id = $1", lex_id
    )
    if doc is None:
        return None
    rows = await conn.fetch(
        """
        SELECT id, element_id, kind, text, link, parent_element_id, amendment_note, future_version
        FROM elementlar
        WHERE document_id = $1 AND modda_raqami = $2
        ORDER BY order_no
        """,
        doc["id"],
        normalized,
    )
    elements = [ArticleElement(**dict(r)) for r in rows]
    heading = next((e for e in elements if e.kind == "article"), None)
    if heading is None:
        return None
    return Article(
        document_lex_id=lex_id,
        document_name=doc["name"],
        document_status=doc["status"],
        current_version=doc["current_version"],
        number=normalized,
        heading=heading,
        body=[e for e in elements if e.kind in _BODY_KINDS and e is not heading],
        notes=[e for e in elements if e.kind in _NOTE_KINDS],
    )
