"""Admin eslatmalari: bot noto'g'ri manbaga tayansa (masalan, yangi farmonni eski kodeks bilan adashtirsa), admin
Telegram'dan tasdiqlangan eslatma qo'shadi — `skill-bilimlar/loyiha-tasdiqlangan-bilimlar.md` dagi "Eslatma:" kabi.

    /eslatma QQS to'lovchi bo'lish chegarasi | 2026-yil 1-iyundan BHMning 12 000 baravari, kodeksdagi 1 mlrd
             hali o'zgartirilmagan | PF-100 2-band, 461-modda

- Saqlanadi: `bilimlar` (turi='bilim', record_key 'admin:eslatma:N'); mavzu va manbalar savolga moslashda,
  eslatma matni — modelga `<eslatma>` (manba emas, iqtibos qilinmaydi); manbalar (modda, PF/PQ bandi) kontekstga
  qo'shiladi — javob baribir Lex.uz matniga bog'lanadi.
- Kamida bitta manba ishorasi shart ("461-modda", "PF-100 2-band", "PQ-374") — manbasiz eslatma qabul qilinmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from app.retrieval.bilimlar import references

PREFIX = "admin:eslatma:"
USAGE = ("Foydalanish:\n"
         "/eslatma mavzu | eslatma matni | manbalar\n"
         "Masalan: /eslatma QQS to'lovchi bo'lish chegarasi | 2026-yil 1-iyundan BHMning 12 000 baravari; kodeksdagi "
         "1 mlrd hali o'zgartirilmagan | PF-100 2-band, 461-modda\n\n"
         "/eslatmalar — ro'yxat, /eslatma_ochir N — o'chirish")


@dataclass(frozen=True)
class Note:
    topic: str
    text: str
    refs: str


def parse(args: str) -> Note | str:
    """"mavzu | eslatma | manbalar" → Note yoki xato matni."""
    parts = [p.strip() for p in (args or "").split("|")]
    if len(parts) != 3 or not all(parts):
        return USAGE
    topic, text, refs = parts
    if not references(refs):
        return ("Manba ishorasi topilmadi. Kamida bittasini yozing: \"461-modda\", \"PF-100 2-band\" yoki \"PQ-374\".\n\n"
                + USAGE)
    if len(topic) > 200 or len(text) > 600:
        return "Mavzu 200, eslatma 600 belgidan oshmasin."
    return Note(topic, text, refs)


async def add(conn: asyncpg.Connection, note: Note, admin_id: int) -> int:
    n = await conn.fetchval(
        "SELECT coalesce(max(substr(record_key, length($1) + 1)::int), 0) + 1 FROM bilimlar WHERE record_key LIKE $1 || '%'",
        PREFIX)
    await conn.execute(
        """
        INSERT INTO bilimlar (record_key, turi, topic, text, source, expiry_type, lex_check_required)
        VALUES ($1, 'bilim', $2, $3, $4, 'yonaltiruvchi', true)
        """,
        f"{PREFIX}{n}", f"{note.topic} ({note.refs})", f"{note.topic}\nEslatma: {note.text}\nManba: {note.refs}",
        f"admin:{admin_id}",
    )
    return n


async def list_notes(conn: asyncpg.Connection) -> list[tuple[int, str, str]]:
    rows = await conn.fetch(
        "SELECT record_key, topic, text FROM bilimlar WHERE record_key LIKE $1 || '%' "
        "ORDER BY substr(record_key, length($1) + 1)::int", PREFIX)
    out = []
    for r in rows:
        note = next((line.removeprefix("Eslatma:").strip() for line in r["text"].splitlines()
                     if line.startswith("Eslatma:")), "")
        out.append((int(r["record_key"].removeprefix(PREFIX)), r["topic"], note))
    return out


async def remove(conn: asyncpg.Connection, n: int) -> bool:
    return await conn.fetchval("DELETE FROM bilimlar WHERE record_key = $1 RETURNING 1", f"{PREFIX}{n}") is not None
