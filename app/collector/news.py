"""Kunlik RSS pipeline (spec 17):

    RSS → SOLIQ_SOZLARI filtri → (fast model bilan) relevantlik → to'liq yuklash → parse → upsert → o'zgarishlar

- RSS barcha yangi hujjatlarni beradi: Prezident farmon/qarorlari, Vazirlar Mahkamasi qarorlari, qonunlar,
  idoraviy hujjatlar. Kalit so'z filtri har doim ishlaydi. Fast model (ANTHROPIC) bo'lsa — kuchli yoki soha
  so'zi bor hujjatlar uchun relevantlik va qisqa faktik xulosa; bo'lmasa — faqat kuchli so'z bor hujjatlar
  relevant (`relevance_method = 'keyword'`, summary bo'sh).
- Import qilingan hujjatlar keyin haftalik yangilashda kuzatiladi (`jobs.weekly_refresh_job`).
- Relevant hujjat to'liq yuklanadi va `import_document` bilan bazaga yoziladi (idempotent, holat kartochkadan).
- Qayta ishga tushirish xavfsiz: `yangiliklar` lex_id bo'yicha UPSERT, allaqachon import qilinganlari qayta
  yuklanmaydi (haftalik/kelajakdagi qayta tekshiruv alohida job'larda).
- Bitta hujjatdagi xato butun jarayonni to'xtatmaydi.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date

import asyncpg

import lexuz
from app.ai.client import LLMError, Usage
from app.collector.importer import import_document
from app.retrieval.query import normalize

log = logging.getLogger(__name__)

# Normallashtirilgan (kichik harf, tutuq belgisiz) so'z boshi prefikslari: faqat so'z boshidan mos keladi
# ("olish haqida" → "ish haqi" emas, "tartibga solish" → "soliq" emas, "akkreditatsiya" → "kredit" emas).
# Ro'yxat 2026-09-27 dagi jonli RSS (131 hujjat) tahlili asosida.
#
# KUCHLI so'zlar — soliq/buxgalteriya/tadbirkorlik tartibiga bevosita aloqador; model bo'lmasa ham relevant.
KUCHLI_SOZLAR = (
    # soliqlar va to'lovlar
    "soliq", "solig", "qqs", "qoshilgan qiymat", "aksiz", "bojxona", "boj", "jarima", "penya", "yigim",
    "davlat boji", "majburiy tolov", "hisobvaraq-faktura", "elektron hisobvaraq", "kassa", "onlayn-nazorat",
    # buxgalteriya va hisobot
    "buxgalter", "moliyaviy hisobot", "hisob standart", "bhms", "bhs", "schyotlar rejasi", "audit", "inventarizatsiya",
    # mehnat va ijtimoiy to'lovlar
    "mehnat", "ish haqi", "pensiya", "ijtimoiy soliq", "ijtimoiy sugurta", "badal",
    # tadbirkorlik va imtiyozlar
    "tadbirkor", "yakka tartibdagi", "korxona", "biznes", "imtiyoz", "preferensiya", "subsidiya", "kompensatsiya",
    "investitsiya", "eksport", "import", "valyuta", "davlat xarid", "xususiylashtir", "davlat aktiv",
    "erkin iqtisodiy zona", "maxsus iqtisodiy zona", "kichik sanoat zona", "it-park", "it park", "elektron tijorat",
    "mol-mulk", "yer uchastka", "ijara", "debitor", "kreditorlik",
    # faoliyat yuritish tartiblari (litsenziya, ruxsat, xabardor qilish, davlat xizmati reglamenti)
    "litsenziya", "ruxsatnoma", "ruxsat berish", "ruxsat etish", "xabardor qilish", "tartib-taomil",
    "faoliyatini amalga oshirish", "faoliyat yuritish", "faoliyatni amalga oshirish", "mamuriy reglament",
    "davlat royxatidan otkaz", "sertifikat",
)
# SOHA so'zlari — ko'p hujjatda uchraydi, soliqqa aloqasi har doim ham yo'q; faqat model bo'lsa tekshiriladi.
SOHA_SOZLARI = (
    "qishloq xojalig", "fermer", "dehqon", "chorva", "parranda", "baliqchilik", "asalarichilik", "paxta", "galla",
    "qurilish", "kochmas mulk", "uy-joy", "turizm", "mehmonxona", "farmatsevtik", "dori", "tibbiy", "klinika",
    "talim xizmat", "nodavlat", "transport", "yuk tashish", "energiya", "elektr energiya", "gaz", "neft", "yoqilgi",
    "raqamli", "dasturiy", "kripto", "sugurta", "bank", "kredit", "moliya", "qimmatli qogoz", "birja", "savdo",
    "bozor", "narx", "tarif", "tolov", "ijtimoiy", "xodim", "kasanachi", "hunarmand", "oziq-ovqat", "alkogol",
    "tamaki", "sanoat", "ishlab chiqarish", "xizmat korsat", "tovar", "budjet", "byudjet",
)
SOLIQ_SOZLARI = KUCHLI_SOZLAR + SOHA_SOZLARI
_KALIT_RE = {k: re.compile(r"(?<![0-9a-zа-яёўқғҳ])" + re.escape(k)) for k in SOLIQ_SOZLARI}
MAX_IMPORTS_PER_RUN = 20
EXCERPT_CHARS = 3000


@dataclass
class RssRunStats:
    items: int = 0
    new: int = 0
    keyword_hits: int = 0
    relevant: int = 0
    imported: int = 0
    errors: int = 0
    usage: Usage = field(default_factory=Usage)


def text_keyword_hits(text: str) -> list[str]:
    norm = normalize(f" {text} ")
    return [k for k, rx in _KALIT_RE.items() if rx.search(norm)]


def keyword_hits(item: lexuz.RssItem) -> list[str]:
    return text_keyword_hits(f"{item.title} {item.description}")


def has_strong_hit(hits: list[str]) -> bool:
    return any(h in KUCHLI_SOZLAR for h in hits)


def _meta(item: lexuz.RssItem) -> str:
    parts = [item.doc_type or "", f"№{item.number}" if item.number else "",
             f"qabul qilingan {item.adoption_date}" if item.adoption_date else "",
             f"kuchga kirish {item.effective_date}" if item.effective_date else ""]
    return ", ".join(p for p in parts if p)


def _excerpt(doc: lexuz.Document | None) -> str:
    if doc is None:
        return ""
    out, used = [], 0
    for e in doc.elements:
        if e.kind in ("title", "header", "article", "text", "table"):
            out.append(e.text)
            used += len(e.text)
            if used >= EXCERPT_CHARS:
                break
    return "\n".join(out)[:EXCERPT_CHARS]


async def _existing(conn: asyncpg.Connection, lex_ids: list[str]) -> dict[str, bool]:
    rows = await conn.fetch("SELECT lex_id, imported FROM yangiliklar WHERE lex_id = ANY($1::text[])", lex_ids)
    return {r["lex_id"]: r["imported"] for r in rows}


async def _save(conn: asyncpg.Connection, item: lexuz.RssItem, hits: list[str], relevant: bool, method: str,
                topics: list[str], summary: str | None, imported: bool) -> None:
    await conn.execute(
        """
        INSERT INTO yangiliklar (lex_id, title, doc_type, number, adoption_date, effective_date, url, pub_date,
                                 keyword_hits, relevant, relevance_method, topics, summary, imported)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (lex_id) DO UPDATE SET
            title = EXCLUDED.title, doc_type = EXCLUDED.doc_type, number = EXCLUDED.number,
            adoption_date = EXCLUDED.adoption_date, effective_date = EXCLUDED.effective_date,
            pub_date = EXCLUDED.pub_date, keyword_hits = EXCLUDED.keyword_hits, relevant = EXCLUDED.relevant,
            relevance_method = EXCLUDED.relevance_method, topics = EXCLUDED.topics,
            summary = coalesce(EXCLUDED.summary, yangiliklar.summary),
            imported = yangiliklar.imported OR EXCLUDED.imported
        """,
        item.lex_id, item.title, item.doc_type, item.number, item.adoption_date, item.effective_date, item.url,
        item.pub_date, hits, relevant, method, topics, summary, imported,
    )


async def process_rss(pool: asyncpg.Pool, client: lexuz.LexUzClient, llm, today: date) -> RssRunStats:
    """Bir marta RSS'ni qayta ishlaydi. `llm` — ClaudeLLM yoki None (faqat keyword)."""
    stats = RssRunStats()
    xml = await asyncio.to_thread(client.fetch, lexuz.RSS_URL, use_cache=False)
    items = lexuz.parse_rss(xml)
    stats.items = len(items)
    async with pool.acquire() as conn:
        known = await _existing(conn, [i.lex_id for i in items])

    for item in items:
        if item.lex_id in known and known[item.lex_id]:
            continue  # allaqachon import qilingan
        stats.new += item.lex_id not in known
        hits = keyword_hits(item)
        try:
            # Model bo'lmasa faqat kuchli so'z relevant; soha so'zlarini model tekshiradi.
            if not hits or (llm is None and not has_strong_hit(hits)):
                async with pool.acquire() as conn:
                    await _save(conn, item, hits, False, "keyword", [], None, False)
                continue
            stats.keyword_hits += 1
            doc = card = None
            if stats.imported < MAX_IMPORTS_PER_RUN:
                doc = await asyncio.to_thread(lexuz.load, item.lex_id, client=client)
                card = await asyncio.to_thread(lexuz.load_card, item.lex_id, client=client)

            relevant, method, topics, summary = True, "keyword", [], None
            if llm is not None:
                try:
                    c = await asyncio.to_thread(llm.classify_news, item.title, _meta(item), _excerpt(doc), stats.usage)
                    relevant, method, topics, summary = c.relevant, "llm", c.topics[:3], c.summary.strip() or None
                except LLMError as exc:
                    log.warning("news classify failed lex_id=%s error=%s — keyword natijasi saqlanadi", item.lex_id, exc)

            imported = False
            if relevant and doc is not None:
                async with pool.acquire() as conn:
                    await import_document(conn, doc, card, today)
                imported = True
                stats.imported += 1
            stats.relevant += relevant
            async with pool.acquire() as conn:
                await _save(conn, item, hits, relevant, method, topics, summary, imported)
        except Exception as exc:  # bitta hujjat butun jarayonni to'xtatmasin
            stats.errors += 1
            log.error("news item failed lex_id=%s type=%s", item.lex_id, type(exc).__name__, exc_info=True)

    log.info("rss done items=%d new=%d keyword=%d relevant=%d imported=%d errors=%d",
             stats.items, stats.new, stats.keyword_hits, stats.relevant, stats.imported, stats.errors)
    return stats


@dataclass(frozen=True)
class NewsEntry:
    lex_id: str
    title: str
    doc_type: str | None
    number: str | None
    adoption_date: date | None
    effective_date: date | None
    url: str
    summary: str | None
    status: str | None


async def recent_news(conn: asyncpg.Connection, today: date, days: int = 7, limit: int = 15) -> list[NewsEntry]:
    rows = await conn.fetch(
        """
        SELECT y.lex_id, y.title, y.doc_type, y.number, y.adoption_date, y.effective_date, y.url, y.summary, h.status
        FROM yangiliklar y LEFT JOIN hujjatlar h ON h.lex_id = y.lex_id
        WHERE y.relevant AND coalesce(y.pub_date::date, y.adoption_date, y.created_at::date) >= $1::date - $2::int
        ORDER BY coalesce(y.pub_date, y.created_at) DESC
        LIMIT $3
        """,
        today, days, limit,
    )
    return [NewsEntry(**dict(r)) for r in rows]
