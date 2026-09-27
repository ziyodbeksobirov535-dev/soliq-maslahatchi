"""Inline tugmalar va ularning callback ma'lumotlari (Telegram: callback_data ≤ 64 bayt).

- `v:<m|b>:<lex_id>:<modda|birlik>` — manbaning to'liq matnini ko'rsatish;
- `r:<request_id>:<1|-1>` — javobga baho (suhbatlar.rating);
- `p:<maydon>` — profil maydoni variantlari; `p:<maydon>:<n>` — n-variantni tanlash;
  `p:<maydon>:o` — o'z qiymatini yozish; `p:<maydon>:x` — tozalash; `p:-` — profilga qaytish.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.answer import FinalAnswer

MAX_SOURCE_BUTTONS = 3
RATED_STATUSES = ("answered", "sources_only", "insufficient")

# Profil variantlari (tanlash tugmalari). Ro'yxatda bo'lmasa — "Boshqa" orqali o'zi yozadi.
PROFILE_OPTIONS: dict[str, list[str]] = {
    "soha": ["Savdo", "Ishlab chiqarish", "Qurilish", "Xizmatlar", "IT", "Qishloq xo'jaligi", "Transport",
             "Umumiy ovqatlanish"],
    "rejim": ["Aylanma solig'i", "Umumbelgilangan (QQS, foyda solig'i)", "Qat'iy belgilangan soliq (YaTT)",
              "Soliqdan ozod"],
    "shakl": ["MChJ", "YaTT", "Xususiy korxona", "AJ", "Fermer xo'jaligi", "Oilaviy korxona"],
}
PROFILE_BUTTON_TITLES = {"soha": "Faoliyat sohasi", "rejim": "Soliq rejimi", "shakl": "Tashkiliy shakl"}


def _unit_label(kind: str, unit_id: str, title: str) -> str:
    if kind == "m":
        return f"📖 {unit_id}-modda"
    short = title if len(title) <= 24 else title[:23] + "…"
    return f"📖 {short}"


def answer_units(fa: FinalAnswer) -> list[tuple[str, str, str, str]]:
    """Javobdagi manbalar: (tur, lex_id, birlik, sarlavha), takrorsiz, ko'pi bilan MAX_SOURCE_BUTTONS."""
    units: list[tuple[str, str, str, str]] = []
    if fa.status == "answered":
        for c in fa.citations:
            a = c.article
            kind, unit_id = a.key[1], a.key[2]
            units.append((kind, a.lex_id, unit_id, a.title))
    elif fa.status == "sources_only":
        units = [(h.unit[0], h.lex_id, h.unit[1], h.title) for h in fa.hints]
    seen, out = set(), []
    for u in units:
        if u[:3] not in seen and u[2]:
            seen.add(u[:3])
            out.append(u)
    return out[:MAX_SOURCE_BUTTONS]


def answer_keyboard(fa: FinalAnswer, *, rated: bool = False) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(text=_unit_label(kind, unit_id, title), callback_data=f"v:{kind}:{lex}:{unit_id}")]
            for kind, lex, unit_id, title in answer_units(fa)]
    if fa.status in RATED_STATUSES and not rated:
        rows.append([
            InlineKeyboardButton(text="👍 Foydali", callback_data=f"r:{fa.request_id}:1"),
            InlineKeyboardButton(text="👎 Foydasiz", callback_data=f"r:{fa.request_id}:-1"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def without_rating(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Baho berilgach: baho tugmalarini olib tashlaydi, manba tugmalari qoladi."""
    if markup is None:
        return None
    rows = [row for row in markup.inline_keyboard if not any((b.callback_data or "").startswith("r:") for b in row)]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✏️ {title}", callback_data=f"p:{key}")]
        for key, title in PROFILE_BUTTON_TITLES.items()
    ])


def profile_options_keyboard(field: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=opt, callback_data=f"p:{field}:{i}")]
            for i, opt in enumerate(PROFILE_OPTIONS[field])]
    rows.append([InlineKeyboardButton(text="✍️ Boshqa (o'zim yozaman)", callback_data=f"p:{field}:o")])
    rows.append([InlineKeyboardButton(text="🗑 Tozalash", callback_data=f"p:{field}:x"),
                 InlineKeyboardButton(text="⬅️ Orqaga", callback_data="p:-")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
