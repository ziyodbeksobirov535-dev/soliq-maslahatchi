"""Parse qilingan Lex.uz hujjatini bazaga yozish (idempotent).

Mantiq bazadagi `finish_import` funksiyasida (migrations/003_import_rpc.sql): hujjat UPSERT,
farqni aniqlash, `ozgarishlar` jurnali, elementlar UPSERT/o'chirish, versiya — bitta tranzaksiyada.
Python tomoni faqat payload tayyorlaydi va uni ikki yo'ldan biri bilan yuboradi:

- `import_document(conn, ...)` — to'g'ridan-to'g'ri Postgres ulanishi (server, testlar);
- `import_document_rest(...)` — Supabase REST (HTTPS, service_role kaliti) — raw TCP
  yopiq muhitlar uchun.

Holat (`status`) faqat kartochka + `lexuz.resolve_status` dan; kartochka bo'lmasa `noma'lum`.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date

import asyncpg
import httpx

import lexuz

log = logging.getLogger(__name__)

# Bitta REST so'rovidagi elementlar soni (~350 KB): katta hujjat bo'laklab yuboriladi.
REST_CHUNK_SIZE = 500


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

    @classmethod
    def from_json(cls, data: dict) -> ImportResult:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def document_payload(doc: lexuz.Document, card: lexuz.ActCard | None, today: date) -> dict:
    if card is not None and card.doc_id != doc.doc_id:
        raise ValueError(f"Kartochka boshqa hujjatniki: {card.doc_id} != {doc.doc_id}")
    version_date = lexuz.version_date(doc.version) if doc.version else None
    return {
        "lex_id": doc.doc_id,
        "name": card.name if card and card.name else doc.name,
        "type": card.form if card and card.form else doc.header_label,
        "number": card.number if card and card.number else doc.number,
        "adoption_date": _iso(card.adoption_date if card and card.adoption_date else doc.adoption_date),
        "effective_date": _iso(card.effective_date if card and card.effective_date else doc.effective_date),
        "status": lexuz.resolve_status(card, today) if card is not None else lexuz.STATUS_NOMALUM,
        "status_raw": card.status_raw if card else None,
        "current_version": doc.version,
        "version_date": _iso(version_date),
        "url": doc.url,
        "source_url": lexuz.doc_url(doc.doc_id, doc.version) if doc.version else doc.url,
        "content_hash": doc.content_hash,
        "text_available": doc.text_available,
        "repeal_date": _iso(card.repeal_date if card else None),
    }


def element_payload(e: lexuz.Element) -> dict:
    return {
        "element_id": e.element_id,
        "parent_element_id": e.parent_element_id,
        "order_no": e.order_no,
        "type": e.type,
        "kind": e.kind,
        "bob": e.bob,
        "modda": e.modda,
        "modda_raqami": e.modda_raqami,
        "text": e.text,
        "text_hash": e.text_hash,
        "amendment_note": e.amendment_note,
        "future_version": e.future_version,
        "link": e.link,
        "element_path": e.element_path,
    }


def _log_result(result: ImportResult) -> ImportResult:
    log.info(
        "document imported lex_id=%s status=%s first=%s total=%d added=%d changed=%d removed=%d",
        result.lex_id, result.status, result.first_import, result.total,
        result.added, result.changed, result.removed,
    )
    return result


async def import_document(
    conn: asyncpg.Connection,
    doc: lexuz.Document,
    card: lexuz.ActCard | None,
    today: date,
) -> ImportResult:
    """To'g'ridan-to'g'ri Postgres ulanishi orqali import (staging + finish_import, bitta tranzaksiya)."""
    payload = document_payload(doc, card, today)
    import_id = uuid.uuid4()
    rows = [(import_id, i, json.dumps(element_payload(e), ensure_ascii=False)) for i, e in enumerate(doc.elements, 1)]
    async with conn.transaction():
        await conn.executemany(
            "INSERT INTO import_staging (import_id, seq, element) VALUES ($1, $2, $3::jsonb)", rows
        )
        raw = await conn.fetchval(
            "SELECT finish_import($1, $2::jsonb, $3)", import_id, json.dumps(payload, ensure_ascii=False), today
        )
    return _log_result(ImportResult.from_json(json.loads(raw)))


async def import_document_rest(
    supabase_url: str,
    service_role_key: str,
    doc: lexuz.Document,
    card: lexuz.ActCard | None,
    today: date,
    *,
    http_client: httpx.AsyncClient | None = None,
    chunk_size: int = REST_CHUNK_SIZE,
) -> ImportResult:
    """Supabase REST (PostgREST) orqali import: staging bo'laklari, so'ng `rpc/finish_import`.

    Bo'laklar yozilgach xato bo'lsa, staging qatorlari o'chiriladi; `finish_import` o'zi atomar.
    """
    payload = document_payload(doc, card, today)
    import_id = str(uuid.uuid4())
    base = supabase_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    try:
        try:
            elements = [element_payload(e) for e in doc.elements]
            for start in range(0, len(elements), chunk_size):
                chunk = [
                    {"import_id": import_id, "seq": start + i + 1, "element": el}
                    for i, el in enumerate(elements[start : start + chunk_size])
                ]
                resp = await client.post(f"{base}/import_staging", headers=headers, json=chunk)
                resp.raise_for_status()
            resp = await client.post(
                f"{base}/rpc/finish_import",
                headers=headers,
                json={"p_import_id": import_id, "p_doc": payload, "p_today": today.isoformat()},
            )
            resp.raise_for_status()
        except Exception:
            await client.delete(
                f"{base}/import_staging", headers=headers, params={"import_id": f"eq.{import_id}"}
            )
            raise
        return _log_result(ImportResult.from_json(resp.json()))
    finally:
        if owns_client:
            await client.aclose()
