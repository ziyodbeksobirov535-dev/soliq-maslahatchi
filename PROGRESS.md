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

## PHASE 1 — Structure, config, logging, migrations ✅ (user tasdig'ini kutmoqda)

### Bajarildi
- [x] Project structure, `.env.example`, config, logging (PHASE 0 da tayyor bo'lgan)
- [x] `migrations/001_init.sql` — spec 5-bo'limdagi barcha jadvallar
- [x] `app/database/migrate.py` — runner: tartib, bitta tranzaksiya, checksum, advisory lock, `--status`
- [x] Database testlari (26 ta, real PostgreSQL 16 da): insert, upsert idempotentligi (butun Soliq kodeksi —
      8 137 element — ikki marta yozilganda dublikat ham, keraksiz UPDATE ham yo'q), duplicate prevention,
      status CHECK, versiyalash, o'zgarishlar jurnali, RLS, FK/cascade, FTS + trigram qidiruv
- [x] Test skeleton: search (10 savol), hallucination (10 holat), citation — PHASE 3/4 uchun SKIP
- [x] README: DB o'rnatish va testlar
- Natija: `TEST_DATABASE_URL` bilan 94 passed; usiz 67 passed, 52 skipped

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

### Keyingi bosqich: PHASE 2 (tasdiqdan keyin)
- Soliq kodeksini (`-4674902`) Lex.uz'dan yuklab, bazaga import qilish (hujjat + kartochka holati + elementlar)
- `/modda 461` uchun to'g'ridan-to'g'ri qidiruv, link testlari
- Real Supabase ulanishi kerak bo'ladi (`SUPABASE_DB_URL`)
