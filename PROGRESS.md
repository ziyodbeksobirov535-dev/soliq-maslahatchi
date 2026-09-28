# PROGRESS

Spec: `docs/MASTER_SPEC.md` (v3).

## PHASE 0 — Repository audit va Lex.uz parser ✅ (tasdiqlandi)

### Bajarildi
- [x] Repository tuzilmasi, Python 3.11+ setup, `requirements*.txt`, `pyproject.toml`
- [x] `.env.example`, `.gitignore`, config (`app/config.py`), logging (`app/utils/logging.py`)
- [x] Lex.uz agreement tekshirildi (pastga qarang)
- [x] `lexuz.py` fetch client: timeout, retry, exponential backoff, `Retry-After`, delay, disk cache, cookie'siz mustaqil so'rovlar
- [x] `lexuz.parse_doc` — metadata + elementlar (ID, tur, modda, bob, yo'l, matn, jadval, izohlar, canonical link)
- [x] `lexuz.parse_card` + `resolve_status` — rasmiy holat (amalda / kuchga_kirmagan / kuchini_yoqotgan / noma'lum)
- [x] `lexuz.load` — joriy yoki tarixiy (`pick_version` bilan) versiya; `load_card`
- [x] Testlar: 65 ta, hammasi o'tadi; parser testlari real HTML fixture'larda (`tests/fixtures/lexuz/`)
- [x] Jonli tekshiruv: Soliq kodeksi joriy, 01.01.2025 va 12.12.2026 versiyalari, kartochka — ishladi
- [x] `skill-bilimlar/` ko'chirildi

### Lex.uz agreement
`https://lex.uz/agreement` — faqat **maxfiylik siyosati** (foydalanuvchi shaxsiy ma'lumotlari haqida).
Avtomatik yuklash, nusxalash yoki qayta foydalanishni taqiqlovchi band **yo'q**; `robots.txt` yo'q (404).
Shunga qaramay spec 3-bo'lim cheklovlari saqlanadi: 1,5 s delay, ketma-ket so'rov, cache, retry limit,
aniq User-Agent. Katta hajmli yuklashdan oldin (PHASE 2+) foydalanuvchi tasdig'i so'raladi.

### Real HTML'dan aniqlangan faktlar (parser shularga asoslangan)
- Soliq kodeksi: 500 modda (1–483, `121¹` kabi qo'shimchalar bilan), 99 sarlavha, 14 jadval
  (aksiz, foyda solig'i va boshqa stavka jadvallari), 2 264 izoh.
- **Tarixiy versiya**: `?ONDATE=` faqat sahifadagi versiyalar ro'yxatidagi sana bilan ishlaydi
  (`27.07.2026`, `12.12.2026 01`); ixtiyoriy sana → 404. Shuning uchun `pick_version` bor.
  Spec'dagi `?ONDATE=DD.MM.YYYY` taxmini shu bilan aniqlashtirildi.
- **Kelajakdagi tahrirlar**: Soliq kodeksida 12.12.2026 dan kuchga kiradigan versiya bor; tegishli
  elementlar `future_version` bilan belgilanadi.
- **Holat**: kartochka kelajakda kuchga kiradigan hujjatni ham "Действующий" deydi (VM-508, 24.12.2026) →
  `resolve_status` kuchga kirish sanasini ham tekshiradi. Noma'lum qiymat → `noma'lum`.
- Kartochka qiymatlari sessiyaga qarab ruscha yoki o'zbekcha keladi → client cookie saqlamaydi, ikkala til tanib olinadi.
- Izohlar: CHANGES_ORIGINS / "LexUZ sharhi" → oldingi elementga; "Oldingi tahrirga qarang" → keyingi
  elementga; "keyingi tahrir" havolasi → oldingi elementga (hammasi real hujjatda sanab tekshirilgan).
- Matni hali e'lon qilinmagan hujjatlar bor (PF-206) → `text_available = False`.
- `INDEXES_ON_REF` (tasniflagich indeksi) va Lex.uz'dagi 6 ta bo'sh "LexUZ sharhi" saqlanmaydi.

## PHASE 1 — Structure, config, logging, migrations ✅ (tasdiqlandi)

### Bajarildi
- [x] Project structure, `.env.example`, config, logging (PHASE 0 da tayyor bo'lgan)
- [x] `migrations/001_init.sql` — spec 5-bo'limdagi barcha jadvallar
- [x] `app/database/migrate.py` — runner: tartib, bitta tranzaksiya, checksum, advisory lock, `--status`
- [x] Database testlari (26 ta, real PostgreSQL 16 da): insert, upsert idempotentligi (butun Soliq kodeksi —
      8 137 element — ikki marta yozilganda dublikat ham, keraksiz UPDATE ham yo'q), duplicate prevention,
      status CHECK, versiyalash, o'zgarishlar jurnali, RLS, FK/cascade, FTS + trigram qidiruv
- [x] Test skeleton: search (10 savol), hallucination (10 holat), citation — PHASE 3/4 uchun SKIP
- [x] README: DB o'rnatish va testlar
- Natija: `TEST_DATABASE_URL` bilan 94 passed, 25 skipped (skelet); usiz 67 passed, 52 skipped

### Sxema: spec'dan farqlar
| O'zgarish | Sabab |
|---|---|
| `o'zgarishlar` → `ozgarishlar` | apostrofli nom SQL'da doim qo'shtirnoq talab qiladi |
| `hujjat_versiyalari.version_token` | Lex.uz faqat ro'yxatdagi versiya tokenini qabul qiladi (`12.12.2026 01`) |
| yangi `versiya_elementlari` jadvali | tarixiy savolga javobda o'sha versiya matnidan iqtibos kerak; `elementlar` dagi UNIQUE bitta versiyaga mo'ljallangan |
| `elementlar`: `kind`, `text_hash`, `future_version` | turga ko'ra filtr, o'zgarishni aniqlash, kelajakdagi tahrir belgisi |
| `elementlar.link` CHECK `https://lex.uz/docs/%#%` | uydirma/noto'g'ri havola bazaga tushmaydi |
| `hujjatlar`: `status_raw`, `status_checked_at`, `current_version` | holat manbasini audit qilish |
| `bilimlar`: `record_key` UNIQUE, `search_vector` | idempotent import, qidiruv |
| `ozgarishlar`: `UNIQUE NULLS NOT DISTINCT` + change_type/hash CHECK | collector qayta ishga tushsa dublikat yo'q |
| barcha jadvallarda RLS | Supabase anon API orqali ma'lumot sizib chiqmasligi |

## PHASE 2 — Soliq kodeksi importi, /modda, havolalar ✅ (tasdiqlandi)

### Supabase
- Loyiha: `soliq-maslahatchi`, ref `lxhpaappvrzxxqzafnct`, mintaqa eu-central-1 (Frankfurt), free tarif, PostgreSQL 17.
- URL: `https://lxhpaappvrzxxqzafnct.supabase.co`
- Migration'lar qo'llangan: `001_init`, `002_hardening`, `003_import_rpc` (`schema_migrations` da checksum bilan).
- Security advisor: faqat `rls_enabled_no_policy` (INFO) — ataylab: public API yopiq, backend RLS'ni chetlab o'tadi.

### Bajarildi
- [x] `002_hardening` — pg_trgm `extensions` sxemasiga, trigger funksiyasi search_path (advisor WARN'lari yo'qoldi)
- [x] `003_import_rpc` — `import_staging` + `finish_import()`: import mantiqi bazada, bitta tranzaksiya
- [x] `app/collector/importer.py` — ikki yo'l: to'g'ridan-to'g'ri Postgres va Supabase REST (bo'laklab, xatoda tozalash)
- [x] `app/collector/initial_load.py` — sukut bo'yicha quruq rejim (metadata ko'rsatadi), `--yes` bilan import
- [x] `app/retrieval/articles.py` — `/modda N` (N, N-1, N¹ formatlari), topilmasa None
- [x] `app/collector/core_documents.py` — asosiy hujjatlar ID'lari Lex.uz kartochkasi orqali tasdiqlangan
- [x] Testlar: 128 passed (DB bilan), jumladan butun Soliq kodeksi importi, qayta import no-op, o'zgarish jurnali,
      461-modda bazadan parser natijasi bilan bir xil, barcha 8 137 havola canonical va real anchor'ga ishora qiladi
- [x] Quruq rejim jonli Lex.uz'da: Soliq kodeksi — 8 137 element, 500 modda, holat `amalda`

### Supabase'ga import (2026-09-27) ✅
Cloud dev muhit raw TCP (Postgres) ochmaydi va service_role kaliti yo'q edi, shuning uchun vaqtinchalik
`import-proxy` Edge Function ishlatildi (`supabase/functions/import-proxy/index.ts`): bazaga Supabase ichki
ulanishi orqali yozadi, faqat 3 amalni bajaradi, tasodifiy token bilan himoyalangan (kodda faqat SHA-256).
- Birinchi import: 8 137 element qo'shildi; qayta import: 0 qo'shilgan / 0 o'zgargan / 0 o'chirilgan.
- Tekshiruv (Supabase'da): 500 modda, holat `amalda` ("Действующий"), versiya 06.08.2026,
  noto'g'ri havola 0, `ozgarishlar` 0, staging bo'sh, baza hajmi 43 MB.
- `/modda`: 461 → `-4688907` "461-modda. Soliq toʻlovchilar"; 121-1 → "121¹-modda..."; 9999 → topilmadi.
- Import tugagach funksiya o'chirildi (verify_jwt yoqilgan, har qanday so'rovga 410). Qayta yoqish uchun
  repodagi manbani yangi token hash'i bilan deploy qilish kerak.
- CLI: `IMPORT_PROXY_TOKEN=... python -m app.collector.initial_load <id> --yes --proxy-url <function URL>`.

Production'da bot to'g'ridan-to'g'ri `SUPABASE_DB_URL` bilan ishlaydi (PHASE 7).

### Asosiy hujjatlar (Lex.uz kartochkasi bilan tekshirilgan, hammasi import qilingan 2026-09-27)
Jami Supabase'da: 6 hujjat, 24 254 element, 2 741 modda, noto'g'ri havola 0. Import funksiyasi yana o'chirilgan.

| Hujjat | Lex.uz ID | Kartochka holati | Import |
|---|---|---|---|
| Soliq kodeksi | -4674902 | Действующий | ✅ 8 137 el., 500 modda |
| Mehnat kodeksi (2022) | -6257288 | Действующий | ✅ 4 270 el., 593 modda |
| Fuqarolik kodeksi, 1-qism | -111189 | Действующий | ✅ 2 876 el., 386 modda |
| Fuqarolik kodeksi, 2-qism | -180552 | Действующий | ✅ 4 556 el., 811 modda |
| Bojxona kodeksi | -2876354 | Действующий | ✅ 4 151 el., 419 modda |
| Buxgalteriya hisobi to'g'risida (O'RQ-404 yangi tahrir) | -2931253 | Действующий | ✅ 264 el., 32 modda |

Eslatmalar: 1995-yilgi Mehnat kodeksi (-142859) 30.04.2023 dan kuchini yo'qotgan. 1996-yilgi buxgalteriya qonuni
(-90762) kartochkada "Не действующий" — bu qiymat parserga noma'lum, shuning uchun `noma'lum` (taxmin qilinmaydi).

## PHASE 3 — PostgreSQL search, retrieval, 10 savol ✅ (tasdiqlandi)

### Bajarildi
- [x] `migrations/004_search.sql` — `norm_uz()` (o'zbek tutuq belgilari: "toʻlov" = "to'lov"), search_vector
      qayta qurildi (A sarlavha, B matn, C bob yo'li), trigram indeks, `search_articles()`
- [x] `migrations/005_search_weights.sql` — IDF × ts_rank, modda bo'yicha qamrov, bo'laklar vazni
- [x] `app/retrieval/query.py` — stop-so'zlar, o'zak (qo'shimchalarni kesish), sinonimlar (QQS, JSHDS, aylanma,
      jarima, topshirish), iboralar, modda raqami, hujjat ishorasi, tarixiy sana, aniqlashtirish kerakligi
- [x] `app/retrieval/search.py` — aniq modda → to'g'ridan-to'g'ri; noaniq → `needs_clarification`;
      tarixiy → joriy matn berilmaydi (`historical_unavailable`); faqat `amalda`; qamrov chegarasi 50%
- [x] `app/retrieval/evaluation.py` — 10 savol, kutilgan moddalar qidiruvdan mustaqil belgilangan
- [x] Testlar: 171 passed (43 tasi qidiruvga oid, lokal Postgres'da)
- [x] Hisobot: `docs/retrieval_report.md` — Supabase'da 6 hujjat bo'yicha

### Natija (Supabase, 6 hujjat)
Top-1 kutilgan ro'yxatda 6/8, asosiy modda top-3 da 6/8, kamida bitta kutilgan modda top-6 da 8/8, noaniq
savollar 2/2 aniqlashtirishga yuborildi, qaytarilgan hujjatlar 100% `amalda`, uydirma havola 0.
Ochiq kamchiliklar: 8-savol (mehnat shartnomasi) va 9-savol (bojxona to'lovi) asosiy moddalari top-6 da yo'q.

## PHASE 4 — Claude API, structured output, citation validation (qisman: jonli test kutilmoqda)

Anthropic hujjatlari (claude-api skill, SDK 1.8.0 manba kodi) bo'yicha tekshirildi: `client.beta.messages.parse`
(`output_format` = Pydantic), `fallbacks="default"` + `server-side-fallback-2026-07-01`, adaptiv thinking
(`budget_tokens` ishlatilmaydi), `output_config.effort` ixtiyoriy, `stop_reason` (refusal/max_tokens), usage/cache maydonlari,
xatolar ierarxiyasi. SDK 1.x `httpx2` ustida — testlarda client soxta obyekt bilan almashtiriladi.

### Bajarildi
- [x] `app/ai/schemas.py` — AnswerOutput {answer_markdown, citations[source_id, claim], needs_more, confidence}, QueryRewrite
- [x] `app/ai/prompts.py` — o'zgarmas system prompt (keshlanadi), manbalar XML (`<element id="EL-…">`), savol oxirida, escape
- [x] `app/ai/validation.py` — faqat kontekstdagi source_id; havola faqat bazadan; javobdagi barcha URL olib tashlanadi
- [x] `app/ai/client.py` — ClaudeLLM: fast model (so'rovlarni qayta yozish), main model (javob), xatolar → sodda xabar
- [x] `app/services/answer.py` — to'liq zanjir: noaniq/tarixiy/topilmadi → Claude chaqirilmaydi; needs_more ≤ 2 round;
      iqtibossiz javob 1 marta qayta so'raladi; baribir asos bo'lmasa — "ma'lumot yetarli emas" + eng yaqin manbalar
- [x] `app/ai/console.py` — 5 savol konsol testi (`--no-llm` rejimi ham bor)
- [x] Testlar: 198 passed; `tests/test_answer.py` (27 ta) — spec 27 dagi 10 hallucination holati va spec 28 citation testi
      (soxta LLM bilan, backend qoidalari modelga bog'liq emas)
- [x] Lokal nusxa (6 hujjat, 24 254 element) — retrieval natijalari Supabase bilan bir xil; kontekst 6–20 ming belgi

### Kutilmoqda
- [ ] Jonli Claude bilan 5 savol. 2026-09-27: kalit bilan urinildi — API "credit balance is too low" (400) qaytardi;
      zanjir xatoni to'g'ri ushladi (foydalanuvchiga sodda xabar, logda request_id). Anthropic hisobiga kredit
      qo'shilgach: `bash scripts/dev_replica.sh` (kerak bo'lsa) va
      `SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:5433/soliq_replica python -m app.ai.console`
      (natija `docs/phase4_console_report.md` ga yoziladi). Kalit repoga yozilmaydi — faqat muhit o'zgaruvchisi.

## PHASE 5 — Telegram bot ✅ kod va testlar (tasdiqlandi; jonli Telegram sinovi token kutmoqda)

### Bajarildi
- [x] `app/bot/handlers.py` — /start (ro'yxatga olish), /profil (soha/rejim/shakl, kunlik limit), /modda N [hujjat]
      (Claude'siz, bazadan: soliq/mehnat/bojxona/fuqarolik/buxgalteriya), /stat (faqat ADMIN_TELEGRAM_IDS),
      /yangiliklar (PHASE 6 da), oddiy savol → answer zanjiri; xato ishlovchi (sodda xabar, stack trace yo'q)
- [x] `app/bot/formatting.py` — Telegram HTML, escape, cheklangan markdown, 4096 belgi bo'lish, havolalar faqat bazadan
- [x] `app/services/users.py` — foydalanuvchi, profil, kunlik limit (Asia/Tashkent kuni, admin cheklanmagan),
      `suhbatlar` jurnali (so'rovlar, element id'lari, iqtiboslar, tokenlar, vaqt, status)
- [x] `migrations/006_suhbat_status.sql` — suhbat natijasi turi (Supabase'ga qo'llangan)
- [x] Claude chaqiruvlari `asyncio.to_thread` da — bir foydalanuvchi boshqalarni kutdirmaydi
- [x] ANTHROPIC kaliti bo'lmasa bot ishlayveradi: /modda ishlaydi, savollarga "sozlanmagan" javobi
- [x] `main.py` — botni ishga tushiradi (`python main.py`), `--check` sozlama tekshiruvi
- [x] Testlar: 224 passed; `tests/test_bot.py` (26 ta) — haqiqiy aiogram Dispatcher + soxta Telegram sessiyasi

### Kutilmoqda
- [ ] Jonli Telegram sinovi: `TELEGRAM_BOT_TOKEN` (@BotFather) kerak. Doimiy ishlashi — PHASE 7 (server).
- [ ] Jonli savol-javob — Anthropic krediti (loyiha oxirida to'ldiriladi).

## PHASE 6 — Collector: RSS, relevantlik, kunlik yangilanish, /yangiliklar ✅ kod (testlar keyinroq)

Foydalanuvchi so'rovi bo'yicha testlar bu bosqichda ishga tushirilmadi (token tejash) — loyiha oxirida boshqa model
bilan to'liq test o'tkaziladi. Faqat `py_compile`/import tekshiruvi va RSS fixture'da parser tekshirildi (131 element).

### Bajarildi
- [x] `migrations/007_yangiliklar.sql` — yangiliklar jadvali (Supabase'ga qo'llangan)
- [x] `lexuz.parse_rss` — Lex.uz RSS: nom, lex_id, turi, raqami, qabul/kuchga kirish sanalari (xavfsiz XML parser)
- [x] `app/collector/news.py` — SOLIQ_SOZLARI filtri → fast model (bo'lsa) relevantlik + faktik xulosa →
      relevant hujjatni to'liq yuklash va `import_document`; kreditsiz rejimda faqat keyword; bir run'da ≤20 import
- [x] `app/collector/jobs.py` — rss / future (kuchga kirish sanasi kelgan hujjatlar) / refresh (asosiy hujjatlar,
      o'zgarishlar `ozgarishlar` ga); CLI: `python -m app.collector.jobs rss|future|refresh`
- [x] `app/scheduler/scheduler.py` — APScheduler, Asia/Tashkent: RSS 07:10, future 07:40, refresh yakshanba 03:20;
      botga ulangan (`python main.py`), job xatosi bot/scheduler'ni yiqitmaydi
- [x] `/yangiliklar` — oxirgi 7 kun, relevant; metadata, holat, xulosa, Lex.uz havolasi

### Filtr kengaytirildi va topilgan hujjatlar kuzatiladi (2026-09-27, foydalanuvchi so'rovi)
- RSS (`https://lex.uz/uz/rss`) barcha yangi hujjatlarni beradi: jonli RSS'da 131 tadan 13 Prezident farmoni,
  17 Prezident qarori, 28 VM qarori, 8 qonun — manba yetarli, filtr muammo edi.
- Eski filtr substring bo'yicha ishlardi → soxta mosliklar: "olish haqida" → "ish haqi", "tartibga solish" →
  "soli", "akkreditatsiya" → "kredit", "Yangibozor" → "bozor". Endi faqat so'z boshidan mos keladi.
- Ikki daraja: `KUCHLI_SOZLAR` (soliq, BHMS/BHS, schyotlar rejasi, imtiyoz, litsenziya, ruxsatnoma, xabardor
  qilish, ma'muriy reglament, xususiylashtirish, elektron tijorat...) — kalitsiz ham relevant;
  `SOHA_SOZLARI` (qishloq xo'jaligi, qurilish, tibbiyot, IT, bank, transport...) — faqat fast model tekshiradi.
  Fixture'da: 27 kuchli, 48 soha, 56 mos emas. Yangi topilganlar: BHS "Yagona schyotlar rejasi", xususiylashtirish
  farmoni, kichik biznes farmoni, elektron tijorat qonuni, litsenziyalash tartib-taomillari.
- News prompt: istalgan sohadagi imtiyoz/subsidiya/hisobot talablari va faoliyat yuritish tartiblari ahamiyatli.
- `weekly_refresh_job` endi 6 asosiy hujjat + RSS'dan import qilingan (kuchini yo'qotmagan) hujjatlarni yangilaydi
  (`tracked_documents`) — farmon/qarorga o'zgartirish kiritilsa, bir hafta ichida bazada yangilanadi.
- Jonli (lokal nusxa): `jobs rss` — 27 relevant, 2 run'da 27 import, xato 0; kuzatiladigan hujjatlar 33 ta.
- Testlar ishga tushirilmadi (foydalanuvchi so'rovi) — `py_compile` va jonli job tekshiruvi.

### Lex.uz qidiruvi: amaldagi eski hujjatlar (2026-09-27, foydalanuvchi so'rovi)
RSS faqat yangi hujjatlarni beradi; eski farmon/qarorlar, imtiyozlar va faoliyat tartiblari qidiruv orqali topiladi.

Real sahifalardan aniqlangan faktlar (`tests/fixtures/lexuz/search-*.html.gz`):
- URL `/uz/search/nat?searchtitle=..&query=..&status=Y&form_id=..&lang=4` (sayt JS'idagi `goSearch`). `form_id`:
  Farmon 3973, Qaror 3972, Qonun 3968, Nizom 487, Tartib 573, Qoidalar 488, Reglament 575.
- Natijalar server tomonida: `tr.dd-table__main-item`, 20 ta/sahifa, "<N> hujjat topildi".
- `?page=` ishlamaydi — keyingi sahifa ASP.NET postback (`__VIEWSTATE` + `__EVENTTARGET=ucFoundActsControl$LinkButton1`,
  POST, cookie'siz ishlaydi). Oxirgi sahifada havola yo'q.
- Badge: "<tur>, DD.MM.YYYY yildagi PF-140-son" yoki "..., DD.MM.YYYY yilda ro'yxatdan o'tgan, ro'yxat raqami 2822-1".
- Holat belgisi `status_code_y` / `status_code_r`; boshqalari namunada yo'q → xom saqlanadi, yakuniy holat kartochkadan.
- Qidiruv to'liq so'z bo'yicha: "bojxona to'lov" → 0, "bojxona to'lovlari" → 8.

Bajarildi:
- [x] `lexuz.search_url`, `parse_search`, `search` (sahifalash), `LexUzClient.fetch(data=...)` — POST, keshsiz
      (GET yo'li o'zgarmagan)
- [x] `migrations/008_topilgan_hujjatlar.sql` — topilganlar, qaysi qidiruv topgani, relevantlik, import urinishlari
- [x] `app/collector/discovery.py` — 16 qidiruv (soliq, imtiyoz, aksiz, QQS, buxgalteriya, moliyaviy hisobot,
      bojxona, subsidiya, litsenziya, ruxsatnoma, ruxsat berish, xabardor qilish, faoliyat tartiblari, tadbirkorlik);
      relevant = nomida kuchli so'z; import: avval Prezident/VM hujjatlari, keyin yangilari; 3 martagacha urinish
- [x] Job'lar: `discover` (shanba 04:10), `import-found` (har kuni 08:10, `DISCOVERY_DAILY_LIMIT`, sukut 0 = o'chiq);
      `tracked_documents` qidiruvdan import qilinganlarni ham haftalik yangilaydi
- [x] Jonli (lokal nusxa): 16 qidiruv 1m42s, 1 198 natija → 1 059 noyob, 986 relevant (188 Prezident, 317 VM,
      72 qonun, ~400 idoraviy); hamma qidiruvda olingan = sayt aytgan jami. `import-found --limit 10` — 7 yangi,
      3 tasi bazada bor edi, xato 0, ~2 s/hujjat
- [x] Hajm bahosi: element ~2,3 KB → 986 hujjat × ~80 element ≈ 180 MB (Supabase Free 500 MB ichida)

### Moddasiz hujjatlar qidiruvda (2026-09-27, foydalanuvchi tasdig'i bilan)
Muammo: `search_articles` faqat moddalar bo'yicha ishlardi; kodekslardan tashqari 33 hujjatdan 32 tasida modda yo'q
(bandlar, boblar, ilovalar) → ular savol-javobda chiqmasdi.
- [x] `migrations/009_bolimlar.sql`: `elementlar.birlik`, `birlik_nomi`; `hisobla_birliklar(document_id)` —
      moddaga kirmagan matn bo'limlarga: chegara — bob sarlavhasi, "N-ILOVA" qatori, hujjat sarlavhasi, modda.
      Nomi: "1-ilova, 2-bob. ..." / "Asosiy qism". Katta bo'lim ~4 000 belgidan keyin band boshida bo'laklanadi
      ("..., 12-band"); mezon — kodeks moddalari (mediana ~1 100, 90% ≤ 3 000 belgi). `finish_import` har importda
      qayta hisoblaydi (003 dagi funksiya aynan, faqat `PERFORM` qo'shilgan); mavjud hujjatlar migratsiyada.
- [x] `search_articles`: modda yoki bo'lim birligi (`m:`/`b:`); natijada `birlik`, `birlik_nomi`. 4 000 belgidan
      katta bo'lim bahosi `1/(1+ln(hajm/4000))` ga kamayadi (bitta ulkan jadval hamma so'zni qamramasin).
      Moddalar bahosi o'zgarmagan.
- [x] Python: `get_section`, `ArticleHit.unit_key`, `SourceArticle.key/title`, promptda `<bolim nomi=...>`,
      javob va Telegram formatida bo'lim nomi; iqtibos/havola avvalgidek element darajasida (bazadan).
- [x] Tekshiruv (lokal nusxa, 39 hujjat): spec'dagi 10 savol — natija PHASE 3 bilan aynan bir xil (top-1 6/8,
      asosiy top-3 6/8, top-6 8/8). Yangi hujjatlar bo'yicha 8 savol: kerakli qaror top-1 da 7/8 (avval 0/8).
      Soxta LLM bilan to'liq zanjir: bo'limdan iqtibos validatsiyadan o'tdi, havola bandga (`#-8221820`).
- Testlar ishga tushirilmadi (foydalanuvchi so'rovi); `test_database` dagi migratsiya ro'yxati 009 bilan yangilandi.

### Kunlik import yoqildi, Supabase (2026-09-27, foydalanuvchi tasdig'i bilan)
- [x] `DISCOVERY_DAILY_LIMIT=50` — `.env.example` va lokal `.env`; har kuni 08:10.
- [x] Lokal birinchi partiya: 50 hujjat 2m30s, xato 0; baza +5 MB (~100 KB/hujjat → 986 ta ≈ 100 MB, avvalgi
      180 MB bahosidan kam). Bo'limlar import paytida avtomatik (`finish_import` → `hisobla_birliklar`).
      Navbatda 926 ta. Ikkala baholash o'zgarmadi (spec 10 savol: 6/8, 6/8, 8/8; yangi qarorlar: 7/8).
- [x] Supabase: 001–007 checksum'lari lokal fayllar bilan mos. **008 qo'llandi** (`apply_migration` +
      `schema_migrations` checksum `525cd752…`); jadval bor, RLS yoqilgan, baza 63 MB; security advisor — faqat
      ataylab qoldirilgan `rls_enabled_no_policy` (INFO).
- [x] **Supabase'ga 009 qo'llandi** (2026-09-27, foydalanuvchi ruxsati bilan, MacBook sessiyasidan): fayl matni +
      `schema_migrations` yozuvi bitta tranzaksiyada (runner'dagi advisory lock bilan), checksum `2af5fac1…`.
      Oldin tekshirildi: 001–008 checksum'lari lokal fayllar bilan mos; `finish_import` 003 dagidan faqat
      `PERFORM hisobla_birliklar` bilan farq qiladi. Natija: `birlik`/`birlik_nomi` ustunlari bor; 5 kodeksda
      bo'lim 0 (hammasi moddada), buxgalteriya qonunida 1 bo'lim; `search_articles` ishlaydi (moddalar qaytadi);
      anon'da `search_articles`/`hisobla_birliklar` EXECUTE yo'q; baza 63 MB. Supabase'da hozircha 6 hujjat,
      `topilgan_hujjatlar` bo'sh — qidiruv/kunlik import faqat lokal nusxada sinalgan, Supabase'da bot ishga
      tushgach boshlanadi.

### Keyingi qadam
- [x] "yuk tashuvchi" — so'z o'zagi (2026-09-27, MacBook). Tekshiruvda aniqlandi: "tashuvchi" va "tashuvlarini"
      allaqachon bitta o'zakka (`tashuv`) tushardi; haqiqiy sabab — Lex.uz matnida asosan "yuk tashish" (Supabase:
      18 marta, "tashuvchi" 7), `stem` esa `tashi`/`tashuv`/`tash` ga ajratadi. Tuzatildi (`app/retrieval/query.py`):
      - `-chi` + kelishik ("tashuvchining", "tashuvchiga") endi `tashuv`, avval `tashuvch` edi;
      - `stem_variants`: ot → fe'l juft o'zagi (-uv → -ish, -ov → -ash: tashuvchi → tashi, to'lov → to'lash);
        qidiruvda bitta OR guruhi `(tashuv:* | tashi:*)` — bitta so'z sanaladi, qamrov o'zgarmaydi.
      - Teskari yo'nalish (fe'l → ot) sinab ko'rildi va olib tashlandi: "foydalanish" → "foydalanuvchi",
        "topshirish" → "topshiruvchi" spec savollarida natijani yomonlashtirdi. "tash:*" ishlatilmaydi (tashqi, tashkil).
      - Supabase'da eski/yangi reja solishtirildi: spec 10 savoldan faqat 2 tasining rejasi o'zgaradi; top-1,
        asosiy top-3, top-6 ko'rsatkichlari o'zgarmadi; norezident savolida top-6 da kutilgan moddalar 4 → 5.
        "Yuk tashuvchi uchun imtiyozlar" → Fuqarolik kodeksi tashish bobi (709–724), avval aralash natija.
      - Eski sessiyadagi "8 qaror" savollari repoda saqlanmagan — ular bo'yicha qayta o'lchanmadi (qarorlar
        Supabase'da hali yo'q). Bazasiz testlar: `test_stem`, `test_stem_variants`, OR guruh; jami 180 passed.
        DB'li `test_search` (sk_db) kutilgan qiymatlari lokal Postgres bilan qayta tekshirilishi kerak.
- [x] Kirill yozuvidagi RSS — tekshirildi (2026-09-28), muammo yo'q: fixture (131) va jonli RSS (122, bitta
      so'rov) da nomi kirillcha element **yo'q**. Yagona element — Senat qarori: turi kirillcha
      ("Ўзбекистон Республикаси Олий Мажлиси Сенатининг қарори", №СҚ-355-V), nomi lotincha va "ko'chmas mulk"
      bo'yicha filtrga tushadi. Regressiya testi qo'shildi; kod o'zgartirilmadi. Kirillcha nomlar paydo bo'lsa —
      kalit so'zlar uchun kirill→lotin transliteratsiya qo'shish mumkin.

### Test qilinishi kerak (oxirida)
- [x] Bazasiz testlar (2026-09-27, MacBook, Python 3.12): `tests/test_collector.py` — 41 ta: parse_search
      (4 fixture: badge ikki turi, holat y/r, jami, postback, bo'sh), search_url, search sahifalash (soxta client:
      postback, takror sahifa himoyasi, max_pages), parse_rss (131 element, maydonlar, XXE yo'q), keyword filtri
      (27/48/56, so'z boshi), discovery (so'rovlarni birlashtirish, xato izolyatsiyasi, relevantlik, import_pending),
      process_rss (kalitsiz / soxta LLM / LLM xatosi), format_news, scheduler job'lari. Jami: 165 passed,
      100 skipped (DB).
- [x] Testlar topgan xato tuzatildi: RSS'dagi idoraviy hujjatlar ("...buyrugʻi рег. № МЮ 3941", 131 dan 23 ta)
      raqami `МЮ`, turi "... рег" bo'lib qolardi → endi raqam `3941`, turdan "рег" olib tashlanadi.
- [x] DB testlari (2026-09-28, MacBook, foydalanuvchi ruxsati bilan lokal PostgreSQL 17 — faqat testlar uchun,
      Supabase ma'lumotlarisiz). `tests/test_sections.py` — 11 ta: hisobla_birliklar (asosiy qism, bob sarlavhasi,
      izoh/imzo/"1-ILOVA"/matnsiz bob kirmaydi, ilova nomi, 4 000+ band bo'yicha va 8 000+ o'lcham bo'yicha
      bo'laklash, moddalar NULL, idempotent, qayta importda qayta hisob), search_articles bo'lim + modda natijasi,
      get_section, `<bolim>` konteksti, discovery upsert (so'rovlar birlashadi), import_pending (tartib, xato
      urinishi), tracked_documents (kuchini yo'qotgan chiqmaydi), recent_news (7 kun, relevant, holat).
      test_database 007–009 va test_bot /yangiliklar allaqachon bor edi. **Jami: 292 passed, 0 skipped.**
      Mac'da test bazasini ishga tushirish (fon xizmati emas):
      `LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@17/bin/pg_ctl -D /opt/homebrew/var/postgresql@17 -o "-p 5433 -c listen_addresses=127.0.0.1" -l /opt/homebrew/var/postgresql@17/test-server.log start`,
      so'ng `TEST_DATABASE_URL=postgresql://macbook@127.0.0.1:5433/postgres .venv/bin/python -m pytest`
      (to'xtatish: `... pg_ctl -D /opt/homebrew/var/postgresql@17 stop`).
- [ ] Jonli: `python -m app.collector.jobs rss` (Lex.uz + baza)

## PHASE 7 — Production deployment ✅ kod va qo'llanma (testlar keyinroq)

Testlar ishga tushirilmadi (foydalanuvchi so'rovi); `bash -n` va `py_compile` tekshiruvlari o'tdi.

### Bajarildi
- [x] Narxlar taqqoslovi (2026-09): Hetzner CX23 ~€5.49, DO $6/$12, Railway Hobby $5+, Render worker $7,
      Supabase Free/Pro $25 — manbalar bilan `docs/DEPLOYMENT.md` da. Tavsiya: VPS 2–4 GB + Supabase Free (pilot),
      production uchun Supabase Pro (backup)
- [x] `docs/DEPLOYMENT.md` — o'zbekcha qadamlar: server, `.env` (bot token, Anthropic, Session pooler URI),
      systemd, scheduler, loglar, backup, health check, yangilash, muammolar jadvali
- [x] `deploy/soliq-bot.service` — systemd (Restart=always, alohida `soliq` user, ProtectSystem=strict, MemoryMax)
- [x] `deploy/backup.sh` — kunlik `pg_dump` (custom format, 14 kun); `.env` source qilinmaydi (parol belgilari)
- [x] `deploy/healthcheck.sh` — cron har 10 daqiqa; muammo bo'lsa birinchi adminga Telegram xabar
- [x] `app/health.py` — `python -m app.health [--bot]`: db, hujjatlar, RSS ≤36 soat, heartbeat ≤15 daqiqa (JSON, exit 1)
- [x] Scheduler'ga heartbeat job (5 daqiqa); bot ishga tushganda darhol heartbeat yoziladi

### Loyiha oxirida qilinadigan ishlar
- [ ] To'liq test (boshqa model bilan): PHASE 6–7 modullari uchun yangi testlar + barcha eski testlar
- [ ] Anthropic krediti → jonli 5 savol (`python -m app.ai.console`)
- [ ] Telegram token → jonli bot sinovi, keyin serverga o'rnatish (`docs/DEPLOYMENT.md`)
- [ ] Chatda ko'rsatilgan Anthropic kalitini revoke qilib, yangisini faqat server `.env` ga yozish

## Mac'da jonli sinov (2026-09-28)
- Bot @soliqexpertibot Mac'da Supabase bilan ishga tushdi (`.env`: Session pooler `aws-0-eu-central-1`,
  `DISCOVERY_DAILY_LIMIT=0`). `/start`, `/modda 440`, `/profil`, `/yangiliklar` — to'g'ri.
- Oddiy savol: Anthropic "credit balance is too low" → foydalanuvchiga faqat "texnik xatolik" — noqulay.
  "Qqs satvkasi" (imlo xatosi) → kerakli 258-modda 4-o'rinda. Shundan PHASE 8.

## PHASE 8 — Foydalanuvchi qulayligi

### A bosqich ✅ kod va testlar (2026-09-28)
- [x] **Claude'siz javob** (`sources_only`): kalit yo'q / kredit tugagan / API xatosi → "texnik xatolik" o'rniga
      3 ta eng yaqin modda/bo'lim, har biridan mos parcha (≤300 belgi) va Lex.uz havolasi
      (`answer.sources_only`, `answer_without_llm`). Aniq modda so'ralsa — o'sha modda.
- [x] **Kirill yozuvi**: savol lotinga o'giriladi (`query.transliterate`, е → ye so'z boshida/unlidan keyin);
      rus klaviaturasidagi "качон", "канча" stop-so'z. Yangiliklar kalit so'z filtri ham kirillni tushunadi.
- [x] **Ruscha savol**: soliq atamalari lug'at bo'yicha o'zbekchaga (`RU_TERMS`: НДС → qqs, налог → soliq,
      статья → modda...), qolgan ruscha so'zlar tashlanadi; javobda "savol rus tilida — o'girib qidirdim".
      To'liq tarjima Claude krediti bilan (rewrite_queries) yaxshilanadi.
- [x] **Imlo xatolari**: `migrations/010_sozlar.sql` — `sozlar` lug'ati (ts_stat, ~18 800 so'z, qurish ~2 s),
      `yangila_sozlar()`; `app/retrieval/spelling.py` — o'zagi lug'atda yo'q so'z → trigram nomzodlar →
      Damerau–Levenshtein (5–7 harf: 1, 8+: 2), teng bo'lsa ko'p uchraydigani. Supabase lug'atida tekshirildi:
      satvkasi → stavkasi, tulanadi → tolanadi, deklaratsya → deklaratsiya, imtyoz → imtiyoz; to'g'ri
      so'zlar o'zgarmaydi (spec savollari bo'yicha test). Javobda "✏️ Imlo tuzatildi: «...» → «...»".
      Lug'at import job'laridan keyin yangilanadi (rss, future, refresh, import-found; `jobs vocab`).
      010 qo'llanmagan bazada qidiruv tuzatishsiz ishlayveradi (ogohlantirish logda).
- [x] **/modda raqamsiz** → "Qaysi modda?" va keyingi xabar raqam sifatida (FSM); raqam bo'lmasa — oddiy savol.
      "461", "461-modda", "modda 461", "106 mehnat" kabi xabar — to'g'ridan-to'g'ri modda.
- [x] **Javob tugmalari**: "📖 258-modda" (to'liq matn, bo'lim ham), 👍/👎 → `suhbatlar.rating`
      (faqat o'z savoliga), baho berilgach baho tugmalari yo'qoladi.
- [x] **/profil tugmalar bilan**: soha / rejim / shakl → variantlar, "Boshqa (o'zim yozaman)", "Tozalash";
      eski `/profil rejim ...` ham ishlaydi.
- Testlar: 332 passed (lokal PostgreSQL 17), bazasiz 207 passed.
- [x] Supabase'ga **010** qo'llandi (foydalanuvchi ruxsati bilan, `python -m app.database.migrate`): checksum `ff5ce163…`,
      `sozlar` 17 200 so'z, anon'da EXECUTE yo'q, baza 69 MB. Bot Mac'da yangi kod bilan qayta ishga tushirildi.

### B bosqich — yangilik xabarlari (dizayn; foydalanuvchi qarorlari 2026-09-28)
Hujjat havolasi emas — tahlil qilingan qisqa yangilik xabari obunachilarga yuboriladi.
- Yuborish: yangilik aniqlanishi bilan, lekin kunduzi (tunda topilsa — ertalab navbat bilan).
- **Yuborishdan oldin admin tasdig'i**: admin ko'rinishini oladi → [✅ Yuborish] [❌ Bekor]; tasdiqsiz hech kimga
  ketmaydi.
- Tahlil: Claude bilan — bandlar hujjat elementlariga bog'lanadi va tekshiriladi; Claude'siz — metadata +
  hujjatning birinchi bandlari.
- Qabul qiluvchilar: `/start` bosgan hamma foydalanuvchi (obuna keyinchalik pullik bo'ladi — hozir emas).
- Soliq kodeksi va boshqa kuzatiladigan hujjatlardagi o'zgarishlar ham xabar bo'ladi — admin tasdig'i bilan.
- Keyinchalik kanalga ham yuborish (hozir emas).

### B bosqich ✅ kod va testlar (2026-09-28)
- [x] `migrations/011_xabarlar.sql`: `xabarlar` (turi, kalit UNIQUE, matn, havola, tugmalar, usul, holat:
      kutilmoqda → tasdiqlandi/bekor → yuborildi, admin ko'rinishlari), `xabar_yuborishlar` (PK xabar+foydalanuvchi),
      `foydalanuvchilar.bloklagan`, `ozgarishlar.xabar_id`.
- [x] `app/services/xabarlar.py`: yangilik xabari (Claude bilan — oddiy tildagi sarlavha, bandlar elementga
      bog'langan va tekshirilgan, uydirma band tashlanadi; Claude'siz — hujjatning birinchi raqamli bandlari,
      kalit so'zlardan soha), o'zgarish xabari (moddalar bo'yicha, hujjat tartibida, "📖 N-modda" tugmalari),
      adminga ko'rinish [✅ Yuborish] [❌ Bekor qilish] — birinchi qaror kuchda, ko'rinishdagi tugma holatga
      almashadi ("✅ Yuborildi: N ta foydalanuvchiga"). Yuborish faqat `NEWS_SEND_START_HOUR..END_HOUR`
      (sukut 09–20) — tunda tasdiqlangani ertalab; ~20 xabar/s, RetryAfter, bloklagan → belgilanadi,
      yana yozsa — belgi olinadi; qayta ishga tushishda hech kimga ikki marta ketmaydi.
- [x] Scheduler: `publish` har 15 daqiqa (faqat kunduzi): tayyorlash → adminlarga ko'rinish → yuborish;
      RSS kuniga 3 marta (07:10, 12:10, 17:10).
- Testlar: `tests/test_xabarlar.py` (13 ta, soxta Telegram bot); jami 345 passed.
- [x] Supabase'ga **011** qo'llandi (ruxsat bilan, runner orqali): checksum `2f077b46…`, RLS yoqilgan.
- [x] Bot Mac'da qayta ishga tushirildi (job'lar: heartbeat, publish, rss, future_recheck, import_found, discover,
      weekly_refresh). Mac uyqu sozlamalari o'zgartirilmaydi (foydalanuvchi so'rovi) — Mac uxlasa bot to'xtaydi.
- [ ] Jonli sinov: 07:10 da RSS avtomatik (≤20 import), 09:00 dan keyin adminga tasdiq ko'rinishlari.

### Majburiy kanal a'zoligi ✅ kod va testlar (2026-09-28; kanal havolasi hali berilmagan — o'chiq)
- [x] `app/bot/subscription.py`: `REQUIRED_CHANNEL` (@nom yoki -100 id) va `REQUIRED_CHANNEL_URL` (.env). A'zo
      bo'lmagan foydalanuvchining xabari/tugmasi handler'ga yetmaydi — "📢 Kanalga o'tish" + "✅ A'zo bo'ldim".
      /start ishlaydi (ro'yxatga olinadi) va taklif ko'rsatadi; adminlar tekshirilmaydi; a'zolik 10 daqiqa
      keshlanadi; tekshirib bo'lmasa (bot kanalda admin emas) — foydalanuvchi to'xtatilmaydi, logda ogohlantirish.
- **Yoqish:** kanalga botni admin qilib qo'shing, `.env` ga `REQUIRED_CHANNEL=@kanal` (yopiq bo'lsa
  `REQUIRED_CHANNEL=-100...` va `REQUIRED_CHANNEL_URL=https://t.me/+...`), botni qayta ishga tushiring.
- Testlar: 7 ta (test_bot); jami 352 passed.

## Keyingi yaxshilanishlar (takliflar, 2026-09-28 — foydalanuvchi bilan muhokama qilinadi)
1. **Serverga ko'chirish** (docs/DEPLOYMENT.md) — Mac uxlasa bot to'xtaydi; yangilik xabarlari va RSS 24/7 server talab qiladi.
2. **Kanalga yangiliklarni avtomatik joylash** — admin tasdiqlagan xabar kanalga ham (jadval tayyor).
3. **Obuna / pullik tarif** — `obunalar` jadvali, bepul limit (masalan, kuniga 5 savol), Click/Payme to'lov.
4. **Profilga moslashgan javob** — soha/rejim Claude promptiga (masalan, aylanma soliq to'lovchi uchun QQS javobi farqli).
5. **Hisob-kitob yordamchisi** — QQS, JSHDS, aylanma solig'i, jarima va penya kalkulyatori (formula + modda havolasi).
6. **Soliq kalendari** — hisobot va to'lov muddatlari eslatmasi (15-sana va h.k.), profil bo'yicha.
7. **Suhbat konteksti** — "u qachon to'lanadi?" kabi davomiy savollar oldingi savolga bog'lansin.
8. **Admin paneli** — /stat kengaytmasi: 👎 baholangan javoblar, topilmagan savollar (baza to'ldirish uchun), xabarlar holati.
9. **Ovozli savol** — Telegram voice → matn (keyinchalik).
10. **Baza kengayishi** — kunlik import (`DISCOVERY_DAILY_LIMIT=50`) Supabase'da yoqilsa ~20 kunda ~1 000 farmon/qaror.

## PHASE 9 — Yangi imkoniyatlar (2026-09-28, foydalanuvchi so'rovi: takliflar 2–10; 1 — server keyinroq)
- [x] RSS tuzatishi: model xato bersa (kredit yo'q) faqat kuchli so'z relevant. 08:48 dagi qo'lda RSS'da 67 relevant
      (44 tasi faqat soha so'zi bilan — xato) → bot 09:00 dan oldin to'xtatildi, tuzatish ruxsat kutmoqda.
- [x] 2. Kanalga joylash: `NEWS_CHANNEL` — tasdiqlangan xabar kanalga bir marta (`xabarlar.kanal_xabar_id`),
      faqat havola tugmalari (Lex.uz, "Botda savol berish").
- [x] 3. Obuna: `/obuna`, Telegram Payments (`PAYMENT_PROVIDER_TOKEN` — Click/Payme, UZS), pre-checkout tekshiruvi,
      to'lov bir marta (`tolovlar.telegram_charge_id`), `/obuna_ber <id> <kun>`, `/obuna_ol <id>`;
      premium — `PREMIUM_DAILY_LIMIT`. Token yo'q — `PAYMENT_CONTACT` ko'rsatiladi.
- [x] 4. Profil Claude promptida (`<profil>`, escape; manba emas).
- [x] 5. `/hisobla`: QQS qo'shish/ajratish (12%, 258), JSHDS (12%, 381), aylanma (4/2/1%, 467 jadvali), penya
      (MB stavkasi/300, 110 — stavkani foydalanuvchi kiritadi). Iqtiboslar real Soliq kodeksi matnida testlanadi.
- [x] 6. `/kalendar`: aylanma/JSHDS/ijtimoiy — 15-kun (470, 389, 407), QQS — 20-kun (273, davr 259), foyda —
      chorakdan keyin 20-kun (339, davr 338); profil rejimi bo'yicha filtr; eslatma roziligi, 09:30 da 3 kun oldin
      va muddat kuni, bir marta (`eslatmalar_yuborilgan`). Dam olish kuni ko'chirilishi hisobga olinmagan.
- [x] 7. Davomiy savol: "u/bu/shu/unda..." + ≤3 so'z → oxirgi 15 daqiqadagi savol bilan birga qidiriladi (izoh 🔗).
- [x] 8. `/admin`: salbiy baholar, javobsiz savollar, xabarlar holati (kutayotganini qayta ko'rish).
- [x] 9. Ovozli xabar: STT xizmati yo'q — "matn bilan yozing" javobi; rasm/hujjat — "faqat matn".
- [x] 10. Baza kengayishi (ruxsat bilan): `jobs discover` — 16 qidiruv, 1 059 noyob, 986 relevant, xato 0;
      `.env` `DISCOVERY_DAILY_LIMIT=50`; birinchi partiya qo'lda: 48 import + 2 bor edi, xato 0. Navbatda 936.
      Supabase: 74 hujjat, 31 178 element, **102 MB**. Hujjat o'rtacha 111 element ≈ 280 KB → 936 ta ≈ +262 MB,
      jami ≈ 365–380 MB (Free 500 MB ning ~75%) — keyin Supabase Pro yoki indeks/hajm optimizatsiyasi kerak bo'lishi mumkin.
- Testlar: 412 passed (lokal PostgreSQL), bazasiz 250 passed.
- [x] Ruxsat bilan: 44 yangilik `relevant = false` (tekshiruv: aynan 44; qoldi 23); **012** qo'llandi (checksum
      `b5f04b94…`, RLS yoqilgan); bot oddiy rejimda qayta ishga tushirildi (8 job, reminders ham).
- Birinchi `publish` (10:25): xabar yaratilmadi — RSS'dagi eng yangi relevant hujjat 22.09 (6 kun oldin),
  `NEWS_MAX_AGE_DAYS=3`. 7 kunlikda 3 ta, 14 kunlikda 10 ta. Oraliqni foydalanuvchi hal qiladi.
- [x] Foydalanuvchi qarori: yangiliklar oralig'i **7 kun** (`.env` `NEWS_MAX_AGE_DAYS=7`; bot doimiy ishlaganda
      yangiliklar har kuni o'zi keladi). Bot 11:35 da qayta ishga tushirildi.
- [x] **Baza filtri** (foydalanuvchi qarori, hajm): discovery faqat Prezident farmoni/qarori va Vazirlar Mahkamasi
      qarori, nomida soliq/buxgalteriya/tadbirkorlik so'zi (`discovery.DOC_TYPES`, `MAVZU_SOZLARI`). Idoraviy,
      qo'shma, farmoyish va boshqa mavzular yuklanmaydi. `jobs reclassify` — navbat qayta baholandi: relevant
      986 → **414** (572 o'zgardi), navbatda 371. Kutilgan jami hajm ≈ 210–220 MB (Free 500 MB ning ~45%).
- [x] Ilgari import qilingan 50 tadan 7 tasi yangi filtrga mos emas edi (ruxsatnoma, xalqaro yuk tashish, o'rmon,
      litsenziyalash jamoatchilik nazorati, yer qa'ri, xorijda mehnat) — foydalanuvchi ruxsati bilan o'chirildi
      (7 hujjat, 693 element; `topilgan_hujjatlar.imported` belgisi qoldi — qayta import qilinmaydi). Lug'at
      yangilandi (22 057 so'z). Supabase: 67 hujjat, 30 485 element, 101 MB (bo'shagan joy jadvalda qayta ishlatiladi).

### Yangilik xabarlari — foydalanuvchi talablari (2026-09-28)
- [x] Birinchi 3 ta xabar (AI'siz) admin tomonidan bekor qilindi; format va tayyorlash usuli qayta ishlandi.
- [x] Yangi format: turi va raqami, oddiy tildagi sarlavha + rasmiy nom, 💡 qisqacha, 📌 raqamlangan asosiy
      o'zgarishlar (↗ manba havolasi), 👥 kimga tegishli, ✅ nima qilish kerak, 📅 sanalar, heshteglar.
- [x] `NEWS_REQUIRE_AI=true` — xabarni faqat Claude tayyorlaydi; kredit yo'q bo'lsa kutiladi (har 15 daqiqada qayta).
- [x] `NEWS_AUDIENCE=admins` — tasdiqlangan xabar hozircha faqat adminlarga.
- [x] Kanal avtomatik emas: tasdiqlangan xabar ostida "📢 Kanalga joylash" (NEWS_CHANNEL berilganda).
- [x] Bekor qilingan 3 ta xabar yozuvi o'chirildi (foydalanuvchi ruxsati bilan) — kredit qo'shilgach AI bilan
      qayta tayyorlanadi (hozir 7 kunlik oraliqda 2 ta yangilik).
- [ ] Anthropic krediti (console.anthropic.com → Billing) va yangi API kalit `.env` ga — foydalanuvchi.
