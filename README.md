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

## Tuzilma

| Yo'l | Vazifa |
|---|---|
| `lexuz.py` | Lex.uz fetch client (timeout, retry, backoff, delay, cache) va havolalar |
| `app/config.py` | `.env` dan sozlamalar (model ID'lari kodda yo'q) |
| `app/utils/logging.py` | request_id (UUID) bilan logging, secret'larni yashirish |
| `app/{bot,collector,retrieval,ai,database,services,scheduler,security}/` | keyingi bosqichlar |
| `skill-bilimlar/` | ichki bilimlar bazasi (Lex.uz o'rnini bosmaydi) |
| `tests/` | pytest testlari; `tests/fixtures/lexuz/` — real Lex.uz HTML namunalari |

## Xavfsizlik

- `.env` git'ga tushmaydi; loglarda tokenlar avtomatik `***` bilan almashtiriladi.
- Loglarga savol matni va shaxsiy ma'lumot yozilmaydi — faqat request_id, bosqich, vaqt.
