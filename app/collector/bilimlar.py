"""Bilimlar bazasi importi (spec 19): rasmiy soliq imtiyozlari ro'yxati → `bilimlar` (turi = 'imtiyoz').

    python -m app.collector.bilimlar imtiyozlar          # quruq rejim: nechta yozuv, namunalar
    python -m app.collector.bilimlar imtiyozlar --yes    # bazaga yozish (record_key bo'yicha upsert)
    python -m app.collector.bilimlar bilimlar [--yes]    # skill bilimlari (bo'limlar bo'yicha), turi = 'bilim'

Manba: skill-bilimlar/kodeks-toliq/soliq-imtiyozlari-FAOL.csv — byudjet ochiqligi nizomiga 9-ilova, 2024-yil 9 oylik
holati, amaldagi 507 band (kirill). Har band: soliq turi, imtiyoz matni ("(СК 379-м.) 2 банд. ..."), hujjat turi,
sanasi, raqami, amal qilish muddati. Yozuv yo'naltiruvchi: javobda manba — tegishli moddaning Lex.uz matni.

Skill bilimlari (spec 19): skill-bilimlar/*.md fayllari "##"/"###" bo'limlari bo'yicha; har bo'lim — mavzu yo'li va
matn. Javobda bo'lim matni ishlatilmaydi: undagi "N-modda", "PF-N", "PQ-N" ishoralari bo'yicha Lex.uz matni olinadi.
`mijozlar-sohalari.md` (mijozlar haqidagi shaxsiy ma'lumot) va `yangiliklar-manbalari.md` (saytlar ro'yxati) olinmaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
IMTIYOZ_CSV = ROOT / "skill-bilimlar" / "kodeks-toliq" / "soliq-imtiyozlari-FAOL.csv"
IMTIYOZ_SOURCE = "Soliq imtiyozlari ro'yxati (byudjet ochiqligi nizomiga 9-ilova), 2024-yil 9 oylik holati"
IMTIYOZ_CHECKED = date(2024, 9, 30)
SK = "-4674902"

_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ", "ь": "", "ы": "i",
    "э": "e", "ю": "yu", "я": "ya", "ў": "oʻ", "қ": "q", "ғ": "gʻ", "ҳ": "h",
}
_YE_RE = re.compile(r"(?<![а-яёўқғҳА-ЯЁЎҚҒҲ])[еЕ]|(?<=[аеёиоуўэюяАЕЁИОУЎЭЮЯ])[еЕ]")
_SK_NUMBER_RE = re.compile(r"^СК-(\d{1,3}(?:-\d)?)$")
_SK_REF_RE = re.compile(r"\(\s*СК\s*(\d{1,3})\s*(?:[-–]\s*(\d))?\s*-?\s*м\.?\s*\)")


def latin(text: str) -> str:
    """O'zbek kirill → lotin (o'qish uchun: bosh harflar va tutuq belgisi saqlanadi)."""
    text = _YE_RE.sub(lambda m: "Ye" if m.group(0).isupper() else "ye", text or "")
    out = []
    for ch in text:
        low = ch.lower()
        if low in _LAT:
            rep = _LAT[low]
            out.append(rep[:1].upper() + rep[1:] if ch != low and rep else rep)
        else:
            out.append(ch)
    return "".join(out)


@dataclass(frozen=True)
class Record:
    record_key: str
    topic: str
    text: str
    asl_matn: str
    hujjat: str | None
    lex_id: str | None
    modda_raqami: str | None
    amal_muddati: date | None


def _date(value: str) -> date | None:
    try:
        return datetime.strptime((value or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_imtiyozlar(path: Path = IMTIYOZ_CSV) -> list[Record]:
    records = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            matn = " ".join((row["Imtiyoz_nomi"] or "").replace('"""', '"').split())
            m = _SK_REF_RE.search(matn)
            modda = (f"{m.group(1)}-{m.group(2)}" if m.group(2) else m.group(1)) if m else None
            if modda is None:  # matnda boshqa shakl ("(СК-337-м.)", "382-модда") — hujjat raqamidan ("СК-337")
                h = _SK_NUMBER_RE.match((row["Hujjat_raqami"] or "").strip())
                modda = h.group(1) if h else None
            records.append(Record(
                record_key=f"imtiyoz:{row['Tartib_raqami'].strip()}",
                topic=f"{latin(row['Soliq_turi'].strip())} imtiyozi",
                text=latin(matn),
                asl_matn=matn,
                hujjat=latin((row["Hujjat_raqami"] or "").strip()) or None,
                lex_id=SK if modda else None,
                modda_raqami=modda,
                amal_muddati=_date(row["Amal_qilish_muddati"]),
            ))
    return records


async def import_records(conn: asyncpg.Connection, records: list[Record]) -> int:
    await conn.executemany(
        """
        INSERT INTO bilimlar (record_key, turi, topic, text, asl_matn, source, checked_date, expiry_type,
                              lex_check_required, lex_id, modda_raqami, hujjat, amal_muddati)
        VALUES ($1, 'imtiyoz', $2, $3, $4, $5, $6, 'muddatli', true, $7, $8, $9, $10)
        ON CONFLICT (record_key) DO UPDATE SET
            topic = EXCLUDED.topic, text = EXCLUDED.text, asl_matn = EXCLUDED.asl_matn, source = EXCLUDED.source,
            checked_date = EXCLUDED.checked_date, lex_id = EXCLUDED.lex_id, modda_raqami = EXCLUDED.modda_raqami,
            hujjat = EXCLUDED.hujjat, amal_muddati = EXCLUDED.amal_muddati
        """,
        [(r.record_key, r.topic, r.text, r.asl_matn, IMTIYOZ_SOURCE, IMTIYOZ_CHECKED, r.lex_id, r.modda_raqami,
          r.hujjat, r.amal_muddati) for r in records],
    )
    return len(records)


SKILL_DIR = ROOT / "skill-bilimlar"
SKILL_FILES = ("bilimlar-bazasi.md", "maxsus-qism-indeksi.md", "kodeks-tuzilishi.md", "hisobot-muddatlari-kalendari.md",
               "jarima-malumotnomasi.md", "norezident-tolov-algoritmi.md", "imtiyoz-sorovnomasi.md",
               "bitim-tarkibi-solishtirish.md", "loyiha-tasdiqlangan-bilimlar.md")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


@dataclass(frozen=True)
class KnowledgeRecord:
    record_key: str
    topic: str
    text: str
    source: str


def parse_skill_knowledge(directory: Path = SKILL_DIR) -> list[KnowledgeRecord]:
    """Har fayl → bo'limlar ("##"/"###"); mavzu = fayl sarlavhasi > bo'lim > kichik bo'lim, matn — bo'lim tanasi."""
    out: list[KnowledgeRecord] = []
    for name in SKILL_FILES:
        path = directory / name
        lines = path.read_text(encoding="utf-8").splitlines()
        heads: dict[int, str] = {}
        body: list[str] = []
        n = 0

        def flush() -> None:
            nonlocal n, body
            text = "\n".join(body).strip()
            if text and len(heads) > 1:  # fayl sarlavhasining o'zi (kirish) emas — mazmunli bo'lim
                n += 1
                topic = " > ".join(heads[k] for k in sorted(heads) if k > 1)  # fayl sarlavhasisiz
                out.append(KnowledgeRecord(f"skill:{name}#{n}", topic[:300], text, f"skill-bilimlar/{name}"))
            body = []

        for line in lines:
            m = _HEADING_RE.match(line)
            if m:
                flush()
                level = len(m.group(1))
                heads = {k: v for k, v in heads.items() if k < level}
                heads[level] = m.group(2).replace("*", "").strip()
            else:
                body.append(line)
        flush()
    return out


async def import_knowledge(conn: asyncpg.Connection, records: list[KnowledgeRecord]) -> int:
    await conn.executemany(
        """
        INSERT INTO bilimlar (record_key, turi, topic, text, source, expiry_type, lex_check_required)
        VALUES ($1, 'bilim', $2, $3, $4, 'yonaltiruvchi', true)
        ON CONFLICT (record_key) DO UPDATE SET topic = EXCLUDED.topic, text = EXCLUDED.text, source = EXCLUDED.source
        """,
        [(r.record_key, r.topic, r.text, r.source) for r in records],
    )
    # Fayl qisqarsa — ortiqcha eski bo'limlar o'chiriladi (record_key raqamlari bo'yicha)
    await conn.execute("DELETE FROM bilimlar WHERE turi = 'bilim' AND record_key <> ALL($1::text[])",
                       [r.record_key for r in records])
    return len(records)


def main() -> None:
    from app.config import get_settings
    from app.database.connection import connect

    parser = argparse.ArgumentParser(description="Bilimlar bazasi importi")
    parser.add_argument("what", choices=["imtiyozlar", "bilimlar"])
    parser.add_argument("--yes", action="store_true", help="bazaga yozish")
    args = parser.parse_args()
    if args.what == "bilimlar":
        records = parse_skill_knowledge()
        print(f"{len(records)} ta bo'lim; fayllar: {len(SKILL_FILES)}")
        for r in records[:4]:
            print(f"  {r.record_key} | {r.topic[:90]}")
        writer = import_knowledge
    else:
        records = parse_imtiyozlar()
        with_article = sum(1 for r in records if r.modda_raqami)
        print(f"{len(records)} ta imtiyoz; Soliq kodeksi moddasi bilan: {with_article}")
        for r in records[:3]:
            print(f"  {r.record_key} | {r.topic} | {r.modda_raqami} | {r.amal_muddati} | {r.text[:100]}")
        writer = import_records
    if not args.yes:
        print("Quruq rejim: bazaga yozilmadi. Yozish uchun --yes qo'shing.")
        return

    async def run() -> None:
        conn = await connect(get_settings().supabase_db_url.get_secret_value())
        try:
            print("yozildi:", await writer(conn, records))
        finally:
            await conn.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
