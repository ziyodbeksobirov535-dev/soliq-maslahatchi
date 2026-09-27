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
- [ ] Jonli Claude bilan 5 savol: `ANTHROPIC_API_KEY` muhitda yo'q. Kalit environment variables ga qo'shilgach:
      `python -m app.ai.console` (natija `docs/phase4_console_report.md` ga yoziladi).
