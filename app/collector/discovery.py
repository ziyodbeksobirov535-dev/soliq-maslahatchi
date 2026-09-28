"""Lex.uz qidiruvi orqali amaldagi eski hujjatlarni topish va bosqichma-bosqich import qilish.

    QIDIRUVLAR → lexuz.search (barcha sahifalar) → topilgan_hujjatlar (UPSERT) → kunlik limit bilan import

RSS faqat yangi e'lon qilingan hujjatlarni beradi. Bu modul hozir amalda bo'lgan eski farmon/qarorlar,
imtiyozlar va faoliyat yuritish tartiblarini (litsenziya, ruxsatnoma, xabardor qilish) topadi.

- Qidiruv: hujjat nomi bo'yicha, faqat amaldagi (`status=Y`), lotin o'zbekcha (`lang=4`).
  Qidiruvlar ro'yxati 2026-09-27 dagi jonli natijalar soni bilan tanlangan (jami ~1 050 noyob hujjat, ~980 relevant).
- Relevantlik (foydalanuvchi qarori 2026-09-28, baza hajmi): faqat Prezident farmoni/qarori va Vazirlar
  Mahkamasi qarori, nomida soliq, buxgalteriya hisobi yoki tadbirkorlikka oid so'z (`MAVZU_SOZLARI`) bo'lsa.
  Idoraviy hujjatlar, qo'shma qarorlar, farmoyishlar va boshqa mavzular (mehnat, litsenziya, ruxsatnoma...) —
  yuklanmaydi. Model ishlatilmaydi.
- Import: kunlik limit (`DISCOVERY_DAILY_LIMIT`, 0 = o'chiq). Avval Prezident va Vazirlar Mahkamasi hujjatlari,
  keyin yangi qabul qilinganlar. Holat kartochkadan (`import_document`). Xato bo'lsa 3 martagacha qayta urinadi.
- Import qilinganlari `jobs.tracked_documents` orqali haftalik yangilashda kuzatiladi.
- Qayta ishga tushirish xavfsiz: lex_id bo'yicha UPSERT, bazada borlari qayta yuklanmaydi.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import asyncpg

import lexuz
from app.collector.importer import import_document
import re

from app.collector.news import text_keyword_hits
from app.retrieval.query import normalize

log = logging.getLogger(__name__)

# Hujjat nomidagi so'zlar (izohda 2026-09-27 dagi natijalar soni) — amaldagi, lotin o'zbekcha.
# Lex.uz to'liq so'z bo'yicha qidiradi: so'z shakli nomdagidek bo'lishi kerak.
QIDIRUVLAR: tuple[str, ...] = (
    "soliq",                        # 245
    "imtiyoz",                      # 73
    "aksiz",                        # 27
    "qo'shilgan qiymat",            # 45
    "buxgalteriya",                 # 107
    "moliyaviy hisobot",            # 52
    "bojxona to'lovlari",           # 8 (qidiruv to'liq so'z bo'yicha: "to'lov" 0 beradi)
    "bojxona boji",                 # 13
    "subsidiya",                    # 28
    "litsenziya",                   # 16
    "ruxsatnoma",                   # 28
    "ruxsat berish",                # 75
    "xabardor qilish",              # 17
    "faoliyatini amalga oshirish",  # 121
    "faoliyat yuritish",            # 24
    "tadbirkorlik",                 # 319
)
# Yuklanadigan hujjat turlari (Lex.uz qidiruv badge'i, normallashtirilgan) — aynan shu turlar.
DOC_TYPES = (
    "ozbekiston respublikasi prezidentining farmoni",
    "ozbekiston respublikasi prezidentining qarori",
    "ozbekiston respublikasi vazirlar mahkamasining qarori",
)
# Mavzu: soliq, buxgalteriya hisobi, tadbirkorlik (so'z boshidan, normallashtirilgan).
MAVZU_SOZLARI = (
    "soliq", "solig", "qqs", "qoshilgan qiymat", "aksiz", "yigim", "davlat boji", "boj",
    "buxgalter", "moliyaviy hisobot", "hisob standart", "bhms", "bhs", "schyotlar rejasi", "audit",
    "inventarizatsiya", "hisobvaraq-faktura", "elektron hisobvaraq", "kassa", "onlayn-nazorat", "ish haqi",
    "tadbirkor", "yakka tartibdagi", "biznes", "imtiyoz", "preferensiya", "subsidiya",
)
_MAVZU_RE = {k: re.compile(r"(?<![0-9a-zа-яёўқғҳ])" + re.escape(k)) for k in MAVZU_SOZLARI}
MAX_PAGES_PER_QUERY = 30  # 20 ta/sahifa → 600 ta; eng kattasi 319
MAX_IMPORT_ATTEMPTS = 3


@dataclass
class DiscoveryStats:
    queries: int = 0
    found: int = 0
    unique: int = 0
    relevant: int = 0
    errors: int = 0


@dataclass
class ImportStats:
    candidates: int = 0
    imported: int = 0
    already: int = 0
    errors: int = 0


def topic_hits(title: str) -> list[str]:
    norm = normalize(f" {title} ")
    return [k for k, rx in _MAVZU_RE.items() if rx.search(norm)]


def is_wanted(doc_type: str | None, title: str, site_status: str | None) -> bool:
    """Bazaga yuklanadimi: Prezident/VM hujjati, mavzusi soliq/buxgalteriya/tadbirkorlik, amaldagi."""
    return (normalize(doc_type or "").strip() in DOC_TYPES and bool(topic_hits(title))
            and site_status in (None, "y"))


async def _upsert(conn: asyncpg.Connection, item: lexuz.SearchItem, queries: list[str]) -> None:
    hits = text_keyword_hits(item.title)
    relevant = is_wanted(item.doc_type, item.title, item.site_status)
    await conn.execute(
        """
        INSERT INTO topilgan_hujjatlar (lex_id, title, doc_type, number, reg_number, adoption_date, url,
                                        site_status, queries, keyword_hits, relevant, last_seen)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
        ON CONFLICT (lex_id) DO UPDATE SET
            title = EXCLUDED.title, doc_type = EXCLUDED.doc_type, number = EXCLUDED.number,
            reg_number = EXCLUDED.reg_number, adoption_date = EXCLUDED.adoption_date,
            site_status = EXCLUDED.site_status, keyword_hits = EXCLUDED.keyword_hits,
            relevant = EXCLUDED.relevant, last_seen = now(),
            queries = ARRAY(SELECT DISTINCT unnest(topilgan_hujjatlar.queries || EXCLUDED.queries))
        """,
        item.lex_id, item.title, item.doc_type, item.number, item.reg_number, item.adoption_date, item.url,
        item.site_status, queries, hits, relevant,
    )


async def discover(pool: asyncpg.Pool, client: lexuz.LexUzClient,
                   queries: tuple[str, ...] = QIDIRUVLAR) -> DiscoveryStats:
    """Barcha qidiruvlarni bajaradi va natijani `topilgan_hujjatlar` ga yozadi. Hujjatlar yuklanmaydi."""
    stats = DiscoveryStats()
    by_id: dict[str, tuple[lexuz.SearchItem, list[str]]] = {}
    for q in queries:
        try:
            items, total = await asyncio.to_thread(
                lexuz.search, lexuz.search_url(title=q), client=client, max_pages=MAX_PAGES_PER_QUERY)
        except Exception as exc:  # bitta qidiruv qolganlarini to'xtatmasin
            stats.errors += 1
            log.error("discovery query failed query=%r type=%s", q, type(exc).__name__, exc_info=True)
            continue
        stats.queries += 1
        stats.found += len(items)
        log.info("discovery query=%r total=%s got=%d", q, total, len(items))
        for it in items:
            by_id.setdefault(it.lex_id, (it, []))[1].append(q)

    stats.unique = len(by_id)
    async with pool.acquire() as conn:
        for item, qs in by_id.values():
            await _upsert(conn, item, qs)
        stats.relevant = await conn.fetchval(
            "SELECT count(*) FROM topilgan_hujjatlar WHERE relevant AND lex_id = ANY($1::text[])", list(by_id))
    log.info("discovery done queries=%d found=%d unique=%d relevant=%d errors=%d",
             stats.queries, stats.found, stats.unique, stats.relevant, stats.errors)
    return stats


async def reclassify(pool: asyncpg.Pool) -> tuple[int, int]:
    """Mavjud ro'yxatni joriy filtr bo'yicha qayta baholaydi (Lex.uz'ga so'rovsiz). (relevant, o'zgargan)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT lex_id, title, doc_type, site_status, relevant FROM topilgan_hujjatlar")
        changes = [(r["lex_id"], want) for r in rows
                   if (want := is_wanted(r["doc_type"], r["title"], r["site_status"])) != r["relevant"]]
        if changes:
            await conn.executemany("UPDATE topilgan_hujjatlar SET relevant = $2 WHERE lex_id = $1", changes)
        total = await conn.fetchval("SELECT count(*) FROM topilgan_hujjatlar WHERE relevant")
    log.info("discovery reclassify relevant=%d changed=%d", total, len(changes))
    return total, len(changes)


async def import_pending(pool: asyncpg.Pool, client: lexuz.LexUzClient, limit: int, today: date) -> ImportStats:
    """Relevant, hali import qilinmagan hujjatlardan `limit` tasini yuklab bazaga yozadi."""
    stats = ImportStats()
    if limit <= 0:
        return stats
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.lex_id, EXISTS (SELECT 1 FROM hujjatlar h WHERE h.lex_id = t.lex_id) AS in_db
            FROM topilgan_hujjatlar t
            WHERE t.relevant AND NOT t.imported AND t.import_attempts < $2
            ORDER BY (t.doc_type ILIKE '%Prezident%' OR t.doc_type ILIKE '%Vazirlar Mahkamasi%') DESC,
                     t.adoption_date DESC NULLS LAST
            LIMIT $1
            """,
            limit, MAX_IMPORT_ATTEMPTS,
        )
    stats.candidates = len(rows)
    for r in rows:
        lex_id = r["lex_id"]
        try:
            if not r["in_db"]:
                doc = await asyncio.to_thread(lexuz.load, lex_id, client=client)
                card = await asyncio.to_thread(lexuz.load_card, lex_id, client=client)
                async with pool.acquire() as conn:
                    await import_document(conn, doc, card, today)
                stats.imported += 1
            else:
                stats.already += 1
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE topilgan_hujjatlar SET imported = true, last_error = NULL WHERE lex_id = $1", lex_id)
        except Exception as exc:  # bitta hujjat qolganlarini to'xtatmasin
            stats.errors += 1
            log.error("discovery import failed lex_id=%s type=%s", lex_id, type(exc).__name__, exc_info=True)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE topilgan_hujjatlar SET import_attempts = import_attempts + 1, last_error = $2 "
                    "WHERE lex_id = $1", lex_id, type(exc).__name__)
    log.info("discovery import candidates=%d imported=%d already=%d errors=%d",
             stats.candidates, stats.imported, stats.already, stats.errors)
    return stats
