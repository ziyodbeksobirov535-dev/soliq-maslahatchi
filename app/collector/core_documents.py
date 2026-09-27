"""Asosiy hujjatlar reyestri (spec 17: initial load).

Har bir ID Lex.uz kartochkasi (`/actinfo/card1/<id>`) orqali tekshirilgan — taxmin qilinmagan.
`approved=True` — foydalanuvchi importga ruxsat bergan; qolganlari faqat ro'yxatda.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoreDocument:
    lex_id: str
    name: str
    verified_on: str  # kartochka tekshirilgan sana
    card_status: str  # kartochkadagi holat (tekshirilgan paytda)
    approved: bool
    note: str = ""


CORE_DOCUMENTS: tuple[CoreDocument, ...] = (
    CoreDocument(
        "-4674902", "Oʻzbekiston Respublikasining Soliq kodeksi", "2026-09-27", "Действующий", approved=True
    ),
    CoreDocument(
        "-6257288", "Oʻzbekiston Respublikasining Mehnat kodeksi (2022)", "2026-09-27", "Действующий",
        approved=True, note="1995-yilgi Mehnat kodeksi (-142859) 30.04.2023 dan kuchini yo'qotgan",
    ),
    CoreDocument(
        "-111189", "Oʻzbekiston Respublikasining Fuqarolik kodeksi (birinchi qism)", "2026-09-27", "Действующий",
        approved=True,
    ),
    CoreDocument(
        "-180552", "Oʻzbekiston Respublikasining Fuqarolik kodeksi (ikkinchi qism)", "2026-09-27", "Действующий",
        approved=True,
    ),
    CoreDocument(
        "-2876354", "Oʻzbekiston Respublikasining Bojxona kodeksi", "2026-09-27", "Действующий", approved=True
    ),
    CoreDocument(
        "-2931253", "“Buxgalteriya hisobi toʻgʻrisida”gi Qonun (O‘RQ-404, yangi tahrir)", "2026-09-27",
        "Действующий", approved=True,
        note=(
            "1996-yilgi 279-I-son qonun (-90762) kartochkada 'Не действующий', oxirgi versiyasi 14.04.2016. "
            "Amaldagi matn (1–32-moddalar) O'RQ-404 hujjati ichida yangi tahrir sifatida; importga ruxsat 2026-09-27."
        ),
    ),
)


def approved_documents() -> list[CoreDocument]:
    return [d for d in CORE_DOCUMENTS if d.approved]
