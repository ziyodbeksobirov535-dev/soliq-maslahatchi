# Soliq maslahatchi bot

O'zbekiston qonunchiligi (soliq, buxgalteriya, mehnat, tadbirkorlik) bo'yicha savollarga
**Lex.uz manbasiga asoslangan** javob beradigan Telegram bot.

    Lex.uz → Collector/Parser → PostgreSQL → Retrieval → Claude API → Citation validation → Telegram

Asosiy prinsip: **manba yo'q → qat'iy huquqiy xulosa yo'q.** To'liq talablar: [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md).
Joriy holat: [`PROGRESS.md`](PROGRESS.md).

## O'rnatish

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # qiymatlarni to'ldiring
python -m pytest
python main.py
```

## Ma'lumotlar bazasi

PostgreSQL 15+ (Supabase ham shu versiyada) kerak — sxemada `UNIQUE NULLS NOT DISTINCT` ishlatilgan.

```bash
# .env da SUPABASE_DB_URL=postgresql://... bo'lishi kerak
python -m app.database.migrate --status   # qaysi migration'lar qo'llangan
python -m app.database.migrate            # kutilayotganlarini qo'llash (qayta ishga tushirish xavfsiz)
```

- Migration'lar: `migrations/NNN_nom.sql`, har biri bitta tranzaksiyada, `schema_migrations` ga checksum bilan yoziladi.
  Qo'llangan faylni o'zgartirmang — yangi fayl yozing.
- Barcha jadvallarda RLS yoqilgan: Supabase public API (anon key) orqali ma'lumot o'qib bo'lmaydi;
  bot to'g'ridan-to'g'ri `SUPABASE_DB_URL` orqali ishlaydi.

Database testlari uchun alohida (production bo'lmagan) PostgreSQL:

```bash
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres python -m pytest
```

Har bir test sessiyasi vaqtinchalik baza yaratadi va oxirida o'chiradi. `TEST_DATABASE_URL` bo'lmasa
database testlari o'tkazib yuboriladi.

## Tuzilma

| Yo'l | Vazifa |
|---|---|
| `lexuz.py` | Lex.uz fetch client (timeout, retry, backoff, delay, cache), parser, holat, versiyalar |
| `app/config.py` | `.env` dan sozlamalar (model ID'lari kodda yo'q) |
| `app/utils/logging.py` | request_id (UUID) bilan logging, secret'larni yashirish |
| `app/database/migrate.py` | migration runner |
| `migrations/` | SQL sxema |
| `app/{bot,collector,retrieval,ai,services,scheduler,security}/` | keyingi bosqichlar |
| `skill-bilimlar/` | ichki bilimlar bazasi (Lex.uz o'rnini bosmaydi) |
| `tests/` | pytest testlari; `tests/fixtures/lexuz/` — real Lex.uz HTML namunalari |

## Lex.uz parser — qisqa misol

```python
from datetime import date
import lexuz

with lexuz.LexUzClient(cache_dir=".cache/lexuz") as client:
    doc = lexuz.load("-4674902", client=client)                    # joriy versiya
    old = lexuz.load("-4674902", date(2025, 1, 15), client=client) # o'sha sana holatiga
    card = lexuz.load_card("-4674902", client=client)
    status = lexuz.resolve_status(card, lexuz.today_tashkent())     # "amalda"

for el in doc.article("461"):
    print(el.kind, el.link, el.text[:80])
```

## Xavfsizlik

- `.env` git'ga tushmaydi; loglarda tokenlar avtomatik `***` bilan almashtiriladi.
- Loglarga savol matni va shaxsiy ma'lumot yozilmaydi — faqat request_id, bosqich, vaqt.
