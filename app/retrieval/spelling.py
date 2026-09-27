"""Imlo xatolarini tuzatish: savoldagi bazada uchramaydigan so'z → lug'atdagi eng yaqin so'z.

    "Qqs satvkasi qancha" → "satvkasi" bazada yo'q → nomzodlar (trigram) → "stavkasi" (1 ta almashtirish)

- Lug'at — `sozlar` jadvali (migrations/010_sozlar.sql): bazadagi matn so'zlari va ular uchragan elementlar soni.
- So'z "noma'lum" — uning o'zagi bilan boshlanadigan so'z lug'atda yo'q (prefiks qidiruvi hech narsa topmaydi).
- Nomzod tahrir masofasi (Damerau–Levenshtein: harf qo'shish/o'chirish/almashtirish/o'rnini almashtirish)
  bilan tekshiriladi: 5–7 harfli so'zda 1, 8+ harfda 2. Teng bo'lsa — ko'p uchraydigani.
- Qisqa so'zlar (< 5 harf) va qisqartmalar (QQS, JSHDS) tuzatilmaydi — xato tuzatish xavfi katta.
"""

from __future__ import annotations

import logging
import re

import asyncpg

log = logging.getLogger(__name__)

MIN_WORD = 5
CANDIDATES = 30


def edit_distance(a: str, b: str) -> int:
    """Damerau–Levenshtein (optimal string alignment): qo'shni harflar o'rni almashishi — 1 ta xato."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[len(b)]


def max_distance(word: str) -> int:
    return 1 if len(word) < 8 else 2


def best_candidate(word: str, candidates: list[tuple[str, int]]) -> str | None:
    """candidates: (so'z, ndoc). Ruxsat etilgan masofadagi eng yaqin, teng bo'lsa eng ko'p uchraydigan."""
    limit = max_distance(word)
    scored = [(edit_distance(word, w), -n, w) for w, n in candidates if w != word]
    scored = [s for s in scored if s[0] <= limit]
    return min(scored)[2] if scored else None


async def unknown_words(conn: asyncpg.Connection, words: dict[str, str]) -> list[str]:
    """words: o'zak → so'z. O'zagi bilan boshlanadigan so'z lug'atda yo'q bo'lgan so'zlar."""
    items = [(s, w) for s, w in words.items() if len(w) >= MIN_WORD and w.isalpha()]
    if not items:
        return []
    rows = await conn.fetch(
        """
        SELECT u.word FROM unnest($1::text[], $2::text[]) AS u(stem, word)
        WHERE NOT EXISTS (SELECT 1 FROM sozlar s WHERE s.soz LIKE u.stem || '%')
        """,
        [s for s, _ in items], [w for _, w in items],
    )
    return [r["word"] for r in rows]


async def suggest(conn: asyncpg.Connection, words: dict[str, str]) -> dict[str, str]:
    """Noma'lum so'zlar uchun tuzatishlar: {asl so'z: tuzatilgan so'z}. Lug'at bo'lmasa — tuzatishsiz."""
    fixes: dict[str, str] = {}
    try:
        unknown = await unknown_words(conn, words)
    except asyncpg.UndefinedTableError:
        log.warning("spelling: sozlar jadvali yo'q (010 migratsiyasi qo'llanmagan) — tuzatishsiz")
        return fixes
    for word in unknown:
        rows = await conn.fetch(
            "SELECT soz, ndoc FROM sozlar WHERE soz % $1 ORDER BY similarity(soz, $1) DESC LIMIT $2",
            word, CANDIDATES,
        )
        fixed = best_candidate(word, [(r["soz"], r["ndoc"]) for r in rows])
        if fixed:
            fixes[word] = fixed
    return fixes


def apply_fixes(text: str, fixes: dict[str, str]) -> str:
    """Normallashtirilgan savol matnida so'zlarni almashtiradi (butun so'z bo'yicha)."""
    for old, new in fixes.items():
        text = re.sub(rf"(?<![a-z0-9]){re.escape(old)}(?![a-z0-9])", new, text)
    return text
