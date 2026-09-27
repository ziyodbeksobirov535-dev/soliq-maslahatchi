# Loyihani MacBook'da davom ettirish — Claude Code uchun prompt

Mac'ga faqat kod keladi (GitHub orqali); ma'lumotlar Supabase'da qoladi, lokal baza ko'tarilmaydi.
Quyidagi matnni MacBook'dagi Claude Code'ga (Terminal'da `claude`) to'liq nusxalab yuboring.

---

```text
Men soliq-maslahatchi loyihasini (O'zbekiston soliq/buxgalteriya bo'yicha Telegram bot) cloud sessiyadan
MacBook'ga ko'chirib, shu yerda davom ettiraman. Noldan boshlama — hamma ish GitHub'da, ma'lumotlar Supabase'da.
Mac'ga faqat kod kerak: lokal PostgreSQL ko'tarma, hujjatlarni Lex.uz'dan qayta yuklama.

1. KOD
- Uy papkamdagi loyihalar papkasini top (`ls ~`: project / projects / Projects). Topilmasa yoki bir nechta
  bo'lsa — mendan so'ra. Uning ichida `soliq-experti` papkasini och (bo'sh joysiz).
- Shu papkaga klonla va oxirgi ish branch'iga o't:
  git clone https://github.com/ziyodbeksobirov535-dev/soliq-maslahatchi.git <loyihalar-papkasi>/soliq-experti
  cd <loyihalar-papkasi>/soliq-experti && git checkout claude/charming-cori-jsmqbv
  Klon yoki push ruxsat so'rasa — `gh auth login` qilishimni ayt.
- Avval o'qi: CLAUDE.md (qoidalar), PROGRESS.md (holat va ochiq ishlar), docs/MASTER_SPEC.md, docs/DEPLOYMENT.md.
- Python 3.11+ venv: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

2. SUPABASE (faqat o'qish)
- Supabase MCP tool'lari (execute_sql, list_tables, list_migrations) senda bormi — tekshir.
  Loyiha: soliq-maslahatchi, ref lxhpaappvrzxxqzafnct.
- Bor bo'lsa, faqat o'qib holatni ayt: `schema_migrations` dagi versiyalar; hujjatlar soni;
  elementlar soni; baza hajmi.
- Tool'lar yo'q bo'lsa — to'xta va menga ayt; ulanish usulini birga tanlaymiz. Parolni chatga yozishimni so'rama.
- Supabase'ga YOZISH (migratsiya, import, UPDATE/DELETE) — faqat mening aniq ruxsatim bilan.

3. HOZIRGI HOLAT (PROGRESS.md da batafsil)
- PHASE 0–7 kodi tayyor. Oxirgi ishlar: RSS filtri; Lex.uz qidiruv parseri (lexuz.search, real fixture'lar
  asosida); eski farmon/qarorlarni topish va kuniga 50 tadan import (app/collector/discovery.py);
  moddasiz hujjatlar bo'limlar bo'yicha qidiruvda (migration 009).
- Supabase'da 001–008 qo'llangan, 009_bolimlar QO'LLANMAGAN. Yangi qidiruv kodi 009 siz Supabase bilan
  ishlamaydi. Birinchi taklifing shu bo'lsin: 009 ni qo'llash — lekin faqat mening ruxsatimdan keyin.
  Qo'llash usuli: fayl matni + `schema_migrations` ga (version, checksum) yozuvi. checksum — faylning
  sha256 hex qiymati (app/database/migrate.py dagi kabi).
- Testlar oxirgi bosqichlarda ishga tushirilmagan; yozilishi kerak bo'lgan testlar ro'yxati PROGRESS.md
  "Test qilinishi kerak" bo'limida. DB testlari lokal Postgres talab qiladi (TEST_DATABASE_URL);
  ularsiz faqat DB'siz testlar ishlaydi. Testlarni ishga tushirishdan oldin mendan so'ra.
- Ochiq kamchiliklar: "yuk tashuvchi" ↔ "yuk tashuvlarini" (so'z o'zagi); kirill yozuvidagi RSS;
  Anthropic krediti yo'q (jonli javoblar sinalmagan); bot hali serverga qo'yilmagan (docs/DEPLOYMENT.md).

4. BOTNI MAC'DA ISHGA TUSHIRISH (faqat men so'rasam)
- .env ni o'zim to'ldiraman (TELEGRAM_BOT_TOKEN, SUPABASE_DB_URL — Session pooler URI). Tokenlarni chatda
  so'rama; .env hech qachon commit qilinmasin.
- Bitta token bilan faqat bitta bot ishlaydi. TelegramConflictError chiqsa — bot boshqa joyda ishlayapti.

5. QOIDALAR
- CLAUDE.md ga amal qil: lexuz.py ni buzadigan refactor qilma; Lex.uz parserini faqat
  tests/fixtures/lexuz/ dagi real namunalar asosida yoz; sozlamalar faqat .env orqali; har bosqich oxirida
  PROGRESS.md ni yangila va to'xtab tasdiqimni kut.
- Commit va push faqat claude/charming-cori-jsmqbv branch'iga. main ga push yoki PR — mendan so'ra.
- Lex.uz'ga ehtiyotkor bo'l (1,5 s kechikish, ketma-ket so'rovlar). Katta yuklashdan oldin so'ra.

Tayyor bo'lgach qisqa hisobot ber: kod joyi, branch, Supabase holati, keyingi qadam uchun taklifing.
```
