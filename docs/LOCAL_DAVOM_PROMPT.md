# Loyihani MacBook'da davom ettirish — Claude Code uchun prompt

Quyidagi matnni MacBook'dagi Claude Code'ga (Terminal'da `claude`) to'liq nusxalab yuboring.

---

Men soliq-maslahatchi loyihasini (O'zbekiston soliq/buxgalteriya bo'yicha Telegram bot) cloud sessiyadan
MacBook'ga ko'chirib, shu yerda davom ettirmoqchiman. Quyidagilarni ketma-ket bajar va har bosqich
natijasini qisqa ayt. Tushunarsiz joy bo'lsa — taxmin qilma, mendan so'ra.

## 1. Papka va kod

1. Uy papkamda (`~`) loyihalar papkasini top: `ls ~` — nomi `project`, `projects` yoki `Projects` bo'lishi
   mumkin. Bir nechta o'xshash papka bo'lsa yoki topilmasa — mendan so'ra.
2. Uning ichida `soliq-experti` papkasini och (bo'sh joysiz — Python venv va shell buyruqlari bo'sh joyli
   yo'llarda buziladi).
3. Repozitoriyni shu papkaga klonla va eng oxirgi ish branch'iga o't:
   ```bash
   git clone https://github.com/ziyodbeksobirov535-dev/soliq-maslahatchi.git <loyihalar-papkasi>/soliq-experti
   cd <loyihalar-papkasi>/soliq-experti
   git checkout claude/charming-cori-jsmqbv
   ```
   Repo private bo'lsa va klon so'rov bersa — `gh auth login` qilishimni so'ra.
4. Avval o'qib chiq: `CLAUDE.md` (qoidalar), `PROGRESS.md` (hozirgi holat va ochiq ishlar),
   `docs/MASTER_SPEC.md`, `docs/DEPLOYMENT.md`.

## 2. Mac'da muhit

1. Homebrew bormi tekshir (`brew --version`); yo'q bo'lsa — o'rnatishni mendan so'ra.
2. `brew install python@3.12 postgresql@16` (Python 3.11+ kerak).
3. Loyiha ichida venv:
   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements-dev.txt
   ```

## 3. Lokal PostgreSQL (Supabase nusxasi)

`scripts/dev_replica.sh` faqat Linux uchun (`su postgres`, `/usr/lib/postgresql`) — Mac'da ishlatma.
Uning o'rniga xuddi shu ishni qo'lda qil:

```bash
PG=$(brew --prefix postgresql@16)/bin
$PG/initdb -D .pgdata -A trust -U postgres          # bir marta
$PG/pg_ctl -D .pgdata -o "-p 5433 -k /tmp" -l .pgdata/log start
$PG/createdb -h 127.0.0.1 -p 5433 -U postgres soliq_replica
export SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:5433/soliq_replica
.venv/bin/python -m app.database.migrate            # 001–009 qo'llanishi kerak
for id in $(.venv/bin/python -c "from app.collector.core_documents import approved_documents as a; print(' '.join(d.lex_id for d in a()))"); do
  LOG_LEVEL=WARNING .venv/bin/python -m app.collector.initial_load --yes -- "$id"
done
.venv/bin/python -m app.collector.jobs rss          # RSS yangiliklari
.venv/bin/python -m app.collector.jobs discover     # Lex.uz qidiruvi: ~1 050 ta amaldagi eski hujjat ro'yxati
.venv/bin/python -m app.collector.jobs import-found --limit 50
```
`.pgdata/` ni `.gitignore` ga qo'sh (commit qilinmasin). Kompyuter qayta yoqilgach Postgres'ni yana
`pg_ctl ... start` bilan ishga tushirish kerak.

## 4. `.env`

`cp .env.example .env`, keyin to'ldir:
- `SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:5433/soliq_replica`
- `ADMIN_TELEGRAM_IDS=5199518706`
- `DISCOVERY_DAILY_LIMIT=50`
- `ANTHROPIC_API_KEY` — hozircha bo'sh (kredit yo'q; bot `/modda`, `/yangiliklar` bilan ishlaydi)
- `TELEGRAM_BOT_TOKEN` — tokenni men o'zim `.env` ga yozaman (@BotFather'dan). Tokenni chatga yozishimni
  so'rama, faylga qo'yganimni ayt.

`.env` hech qachon commit qilinmasin (`git check-ignore .env` bilan tekshir).

## 5. Botni ishga tushirish

```bash
.venv/bin/python main.py --check
.venv/bin/python main.py
```
Mac'da maxsus proksi yo'q, shuning uchun oddiy `main.py` yetadi. Bitta token bilan faqat bitta bot jarayoni
ishlay oladi: `TelegramConflictError` chiqsa — bot boshqa joyda (cloud sessiyada) hali ishlayapti.
Telegram'da `@soliqexpertibot` ga `/start` yozib tekshiraman.

## 6. Hozirgi holat (PROGRESS.md dan qisqacha)

- PHASE 0–7 kodi tayyor. Oxirgi ishlar: RSS filtri (so'z boshidan moslik, kuchli/soha so'zlari),
  Lex.uz qidiruv parseri (`lexuz.search`, real fixture'lar asosida), eski hujjatlarni topish
  (`app/collector/discovery.py`, kuniga 50 ta import), moddasiz hujjatlar (farmon/qaror) bo'limlar bo'yicha
  qidiruvda (migration 009).
- Supabase: 001–008 qo'llangan, **009 qo'llanmagan** — serverda `python -m app.database.migrate` qo'llaydi.
  Supabase'ga o'zing qo'llamoqchi bo'lsang, avval mendan so'ra.
- Testlar oxirgi bosqichlarda ishga tushirilmagan: PHASE 6–7 va yangi modullar uchun testlar yozilishi kerak
  (ro'yxat PROGRESS.md "Test qilinishi kerak" bo'limida). Testlarni ishga tushirishdan oldin mendan so'ra.
- Ochiq kamchiliklar: "yuk tashuvchi" ↔ "yuk tashuvlarini" (so'z o'zagi); kirill yozuvidagi RSS elementlari;
  jonli Claude javoblari uchun Anthropic krediti; serverga o'rnatish (`docs/DEPLOYMENT.md`).

## 7. Qoidalar

- `CLAUDE.md` ga amal qil: `lexuz.py` ni buzadigan refactor qilma; Lex.uz parserini faqat
  `tests/fixtures/lexuz/` dagi real namunalar asosida yoz; sozlamalar faqat `.env` orqali; har bosqich oxirida
  `PROGRESS.md` ni yangila va to'xtab tasdiqimni kut.
- Lex.uz'ga ehtiyotkor bo'l (1,5 s kechikish, ketma-ket so'rovlar). Katta hajmli yuklashdan oldin mendan so'ra.
- Commit'larni `claude/charming-cori-jsmqbv` branch'iga qil; `main` ga push qilishdan oldin so'ra.

Sozlash tugagach, qisqa hisobot ber: nima ishladi, nima ishlamadi va keyingi qadam uchun taklifing.
