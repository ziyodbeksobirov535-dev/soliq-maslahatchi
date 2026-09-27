"""Hujjatni Lex.uz'dan yuklab bazaga import qilish (spec 17: initial load).

    python -m app.collector.initial_load -4674902          # faqat ko'rsatadi (bazaga yozmaydi)
    python -m app.collector.initial_load -4674902 --yes    # tasdiqlangan import

Sukut bo'yicha "quruq" rejim: hujjat va kartochka yuklanadi, metadata va statistika
ko'rsatiladi. Bazaga faqat `--yes` bilan yoziladi — spec talabi: importdan oldin tasdiq.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter
from dataclasses import dataclass

import lexuz
from app.collector.importer import ImportResult, import_document
from app.config import Settings, get_settings
from app.database.connection import connect
from app.utils.logging import request_context, setup_logging

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preview:
    doc: lexuz.Document
    card: lexuz.ActCard
    status: str

    def lines(self) -> list[str]:
        kinds = Counter(e.kind for e in self.doc.elements)
        return [
            f"Lex.uz ID:        {self.doc.doc_id}",
            f"Nomi:             {self.card.name or self.doc.name}",
            f"Shakli:           {self.card.form}",
            f"Raqami:           {self.card.number or self.doc.number or '—'}",
            f"Qabul qilingan:   {self.card.adoption_date or self.doc.adoption_date}",
            f"Kuchga kirgan:    {self.card.effective_date or self.doc.effective_date}",
            f"Kartochka holati: {self.card.status_raw}",
            f"Holat (bazaga):   {self.status}",
            f"Versiya:          {self.doc.version} (jami {len(self.doc.versions)} ta versiya)",
            f"Matn mavjud:      {'ha' if self.doc.text_available else 'yoq'}",
            f"Elementlar:       {len(self.doc.elements)} "
            + ", ".join(f"{k}={v}" for k, v in kinds.most_common()),
            f"Moddalar:         {len(self.doc.articles())}",
            f"Havola:           {self.doc.url}",
        ]


def make_client(settings: Settings) -> lexuz.LexUzClient:
    return lexuz.LexUzClient(
        delay_seconds=settings.lexuz_delay_seconds,
        max_retries=settings.lexuz_max_retries,
        timeout_seconds=settings.lexuz_timeout_seconds,
        cache_dir=settings.lexuz_cache_dir or None,
        cache_ttl_seconds=settings.lexuz_cache_ttl_hours * 3600,
    )


def fetch_preview(lex_id: str, client: lexuz.LexUzClient) -> Preview:
    doc = lexuz.load(lex_id, client=client)
    card = lexuz.load_card(lex_id, client=client)
    return Preview(doc=doc, card=card, status=lexuz.resolve_status(card, lexuz.today_tashkent()))


async def run_import(dsn: str, preview: Preview) -> ImportResult:
    conn = await connect(dsn)
    try:
        return await import_document(conn, preview.doc, preview.card, lexuz.today_tashkent())
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lex.uz hujjatini bazaga import qilish")
    parser.add_argument("lex_id", help="Lex.uz hujjat ID, masalan -4674902")
    parser.add_argument("--yes", action="store_true", help="tasdiqlash: bazaga yozish")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    with request_context(), make_client(settings) as client:
        preview = fetch_preview(args.lex_id, client)
        print("\n".join(preview.lines()))
        if not args.yes:
            print("\nQuruq rejim: bazaga yozilmadi. Import uchun --yes qo'shing.")
            return
        settings.require("supabase_db_url")
        result = asyncio.run(run_import(settings.supabase_db_url.get_secret_value(), preview))
        print(
            f"\nImport: document_id={result.document_id} birinchi={result.first_import} "
            f"jami={result.total} qo'shilgan={result.added} o'zgargan={result.changed} "
            f"o'chirilgan={result.removed} o'zgarmagan={result.unchanged}"
        )


if __name__ == "__main__":
    main()
