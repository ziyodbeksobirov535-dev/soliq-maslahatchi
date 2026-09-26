# soliq-maslahatchi — Claude Code uchun yo'riqnoma

- Asosiy talablar: `docs/MASTER_SPEC.md` (v3). Har bir bosqichdan oldin o'qing.
- Joriy holat va keyingi qadamlar: `PROGRESS.md` (har bosqich oxirida yangilang).
- `lexuz.py` — loyihaning Lex.uz moduli. Ishlaydigan qismini buzadigan refactor qilmang; boshqa modullar undan import qiladi.
- Lex.uz HTML tuzilmasini taxmin qilib parser yozmang — faqat `tests/fixtures/lexuz/` dagi real namunalar asosida.
- Model ID'lari, tokenlar va boshqa sozlamalar faqat `.env` orqali.
- Testlar: `python -m pytest`. Har bir PHASE tugagach STOP — foydalanuvchi tasdig'ini kuting.
