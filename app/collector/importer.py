"""Parse qilingan Lex.uz hujjatini bazaga yozish (idempotent).

- `hujjatlar` — lex_id bo'yicha UPSERT; holat faqat kartochka + `lexuz.resolve_status` dan.
- `elementlar` — (element_id, document_id) bo'yicha UPSERT; matni o'zgarmagan qator qayta yozilmaydi;
  hujjatdan yo'qolgan elementlar o'chiriladi.
- `ozgarishlar` — ikkinchi va keyingi importlarda qo'shilgan/o'zgargan/o'chirilgan elementlar
  (birinchi importda 8 000 ta "qo'shilgan" yozuv shovqin bo'lardi, shuning uchun yozilmaydi).
- `hujjat_versiyalari` — yuklangan versiya tokeni va content hash.
Hammasi bitta tranzaksiyada: yarim yozilgan hujjat qolmaydi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import asyncpg

import lexuz

log = logging.getLogger(__name__)

_UPSERT_DOCUMENT = """
INSERT INTO hujjatlar (lex_id, name, type, number, adoption_date, effective_date, status, status_raw,
                       status_checked_at, current_version, url, source_url, last_loaded,
                       last_successful_load, content_hash, text_available, repeal_date)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CASE WHEN $8::text IS NULL THEN NULL ELSE now() END,
        $9, $10, $11, now(), now(), $12, $13, $14)
ON CONFLICT (lex_id) DO UPDATE SET
    name = EXCLUDED.name, type = EXCLUDED.type, number = EXCLUDED.number,
    adoption_date = EXCLUDED.adoption_date, effective_date = EXCLUDED.effective_date,
    status = EXCLUDED.status, status_raw = EXCLUDED.status_raw,
    status_checked_at = EXCLUDED.status_checked_at, current_version = EXCLUDED.current_version,
    url = EXCLUDED.url, source_url = EXCLUDED.source_url, last_loaded = EXCLUDED.last_loaded,
    last_successful_load = EXCLUDED.last_successful_load, content_hash = EXCLUDED.content_hash,
    text_available = EXCLUDED.text_available, repeal_date = EXCLUDED.repeal_date
RETURNING id, (xmax = 0) AS inserted
"""

_UPSERT_ELEMENT = """
INSERT INTO elementlar (element_id, document_id, parent_element_id, order_no, type, kind, bob,
                        modda, modda_raqami, text, text_hash, amendment_note, future_version,
                        link, element_path)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
ON CONFLICT (element_id, document_id) DO UPDATE SET
    parent_element_id = EXCLUDED.parent_element_id, order_no = EXCLUDED.order_no,
    type = EXCLUDED.type, kind = EXCLUDED.kind, bob = EXCLUDED.bob, modda = EXCLUDED.modda,
    modda_raqami = EXCLUDED.modda_raqami, text = EXCLUDED.text, text_hash = EXCLUDED.text_hash,
    amendment_note = EXCLUDED.amendment_note, future_version = EXCLUDED.future_version,
    link = EXCLUDED.link, element_path = EXCLUDED.element_path
WHERE (elementlar.text_hash, elementlar.order_no, elementlar.parent_element_id,
       elementlar.amendment_note, elementlar.future_version, elementlar.element_path, elementlar.kind)
      IS DISTINCT FROM
      (EXCLUDED.text_hash, EXCLUDED.order_no, EXCLUDED.parent_element_id,
       EXCLUDED.amendment_note, EXCLUDED.future_version, EXCLUDED.element_path, EXCLUDED.kind)
"""

_INSERT_CHANGE = """
INSERT INTO ozgarishlar (document_id, element_id, old_hash, new_hash, old_text, new_text, change_type)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT DO NOTHING
"""

_UPSERT_VERSION = """
INSERT INTO hujjat_versiyalari (document_id, version_token, on_date, text_hash, loaded_at, source_url)
VALUES ($1, $2, $3, $4, now(), $5)
ON CONFLICT (document_id, version_token) DO UPDATE SET
    text_hash = EXCLUDED.text_hash, loaded_at = EXCLUDED.loaded_at, source_url = EXCLUDED.source_url
"""

ADDED, CHANGED, REMOVED = "qo'shilgan", "o'zgargan", "o'chirilgan"


@dataclass(frozen=True)
class ImportResult:
    document_id: int
    lex_id: str
    status: str
    first_import: bool
    total: int
    added: int
    changed: int
    removed: int

    @property
    def unchanged(self) -> int:
        return self.total - self.added - self.changed


def _element_row(e: lexuz.Element, document_id: int) -> tuple:
    return (
        e.element_id, document_id, e.parent_element_id, e.order_no, e.type, e.kind, e.bob,
        e.modda, e.modda_raqami, e.text, e.text_hash, e.amendment_note, e.future_version,
        e.link, e.element_path,
    )


async def import_document(
    conn: asyncpg.Connection,
    doc: lexuz.Document,
    card: lexuz.ActCard | None,
    today: date,
) -> ImportResult:
    """Hujjat va elementlarini yozadi. `card` bo'lmasa holat `noma'lum` bo'ladi."""
    if card is not None and card.doc_id != doc.doc_id:
        raise ValueError(f"Kartochka boshqa hujjatniki: {card.doc_id} != {doc.doc_id}")
    status = lexuz.resolve_status(card, today) if card is not None else lexuz.STATUS_NOMALUM

    async with conn.transaction():
        row = await conn.fetchrow(
            _UPSERT_DOCUMENT,
            doc.doc_id,
            (card.name if card and card.name else doc.name),
            (card.form if card and card.form else doc.header_label),
            (card.number if card and card.number else doc.number),
            (card.adoption_date if card and card.adoption_date else doc.adoption_date),
            (card.effective_date if card and card.effective_date else doc.effective_date),
            status,
            card.status_raw if card else None,
            doc.version,
            doc.url,
            lexuz.doc_url(doc.doc_id, doc.version) if doc.version else doc.url,
            doc.content_hash,
            doc.text_available,
            card.repeal_date if card else None,
        )
        document_id: int = row["id"]
        first_import: bool = row["inserted"]

        old = {
            r["element_id"]: (r["text_hash"], r["text"])
            for r in await conn.fetch(
                "SELECT element_id, text_hash, text FROM elementlar WHERE document_id = $1", document_id
            )
        }
        new = {e.element_id: e for e in doc.elements}
        added = [e for eid, e in new.items() if eid not in old]
        changed = [e for eid, e in new.items() if eid in old and old[eid][0] != e.text_hash]
        removed = [eid for eid in old if eid not in new]

        await conn.executemany(_UPSERT_ELEMENT, [_element_row(e, document_id) for e in doc.elements])
        if removed:
            await conn.execute(
                "DELETE FROM elementlar WHERE document_id = $1 AND element_id = ANY($2::text[])",
                document_id,
                removed,
            )

        if not first_import and old:
            changes = (
                [(document_id, e.element_id, None, e.text_hash, None, e.text, ADDED) for e in added]
                + [
                    (document_id, e.element_id, old[e.element_id][0], e.text_hash, old[e.element_id][1], e.text, CHANGED)
                    for e in changed
                ]
                + [(document_id, eid, old[eid][0], None, old[eid][1], None, REMOVED) for eid in removed]
            )
            if changes:
                await conn.executemany(_INSERT_CHANGE, changes)

        on_date = lexuz.version_date(doc.version) if doc.version else None
        if on_date is not None:
            await conn.execute(
                _UPSERT_VERSION, document_id, doc.version, on_date, doc.content_hash,
                lexuz.doc_url(doc.doc_id, doc.version),
            )

    result = ImportResult(
        document_id=document_id,
        lex_id=doc.doc_id,
        status=status,
        first_import=first_import,
        total=len(doc.elements),
        added=len(added),
        changed=len(changed),
        removed=len(removed),
    )
    log.info(
        "document imported lex_id=%s status=%s first=%s total=%d added=%d changed=%d removed=%d",
        result.lex_id, result.status, result.first_import, result.total,
        result.added, result.changed, result.removed,
    )
    return result
