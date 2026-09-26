# PROGRESS

## 0-bosqich — Repository tahlili (2026-09-26)

### Nima bor
- Repository **butunlay bo'sh** edi (commit yo'q, remote'da ham branch yo'q).
- Qo'shildi: `docs/MASTER_SPEC.md` (spec v2), `CLAUDE.md`, shu fayl.

### Spec kutgan, lekin repoda YO'Q fayllar
| Fayl | Holat | Nima qilish kerak |
|---|---|---|
| `lexuz.py` | Hech qayerda topilmadi | **Foydalanuvchi yuklashi shart.** Spec uni "test qilingan, qayta yozma" deydi — noldan yozish spec'ga zid. |
| `BOT-SYSTEM-PROMPT.md` | Topilmadi | Foydalanuvchi yuklaydi (ichidagi `KERAK:` / `ISHLATILDI:` protokollari saqlanadi). |
| `skill-bilimlar/` | Repoda yo'q, lekin foydalanuvchining `soliq-maslahatchi` Claude skill'ida bor | Tasdiqlansa, skill'dan ko'chiriladi (pastga qarang). |
| `requirements.txt`, `.env.example`, migrations, testlar | Yo'q | PHASE 1 da yaratiladi. |

### `soliq-maslahatchi` skill'ida topilgan bilimlar (import uchun nomzod)
- `bilimlar-bazasi.md`, `norezident-tolov-algoritmi.md`, `bitim-tarkibi-solishtirish.md`,
  `imtiyoz-sorovnomasi.md`, `hisobot-muddatlari-kalendari.md`, `jarima-malumotnomasi.md` — spec 19-bo'limidagi ro'yxat bilan to'liq mos.
- `kodeks-toliq/soliq-imtiyozlari-FAOL.csv` (553 qator), `soliq-imtiyozlari-royxati.csv` (959 qator) — kirill yozuvida.
- Qo'shimcha: `kodeks-toliq/*.txt` — Soliq kodeksining to'liq matni (2026-07-02 holatiga, PDF'dan olingan, ~2.2 MB),
  `kodeks-tuzilishi.md`, `maxsus-qism-indeksi.md`, `mijozlar-sohalari.md`, `yangiliklar-manbalari.md`.
- Muhim: `kodeks-toliq/*.txt` da Lex.uz **element ID'lari yo'q** (PDF matni). Shuning uchun u `elementlar` jadvali uchun
  asosiy manba bo'la olmaydi — faqat parser natijasini solishtirish/fallback uchun. Asosiy manba `lexuz.py` orqali Lex.uz.
- Ma'lum fakt: Soliq kodeksi Lex.uz ID = `-4674902` (uz, lotin), rus versiyasi `4674893` — PHASE 2 da real fetch bilan qayta tasdiqlanadi.

### Nima ishlaydi
- Hozircha hech narsa (kod yo'q).

### PHASE 1 uchun aniq o'zgarishlar (tasdiqdan keyin)
1. Spec 25-bo'limidagi `app/` tuzilmasi (bo'sh modullar + `__init__.py`).
2. `.env.example` (spec 21-bo'lim), `.gitignore`, `requirements.txt` (aiogram 3.x, asyncpg, anthropic, APScheduler, bs4, lxml, pydantic-settings, pytest).
3. `app/config.py` — `.env` dan typed config, model ID hard-code yo'q.
4. `app/utils/logging.py` — request_id (UUID) bilan structured logging, secret/PII filtrlash.
5. `migrations/001_init.sql` — spec 5-bo'limidagi barcha jadvallar, UNIQUE constraintlar, `pg_trgm`, `tsvector` (`simple`), status CHECK'lar.
6. `README.md`, `main.py` (skeleton), `tests/` skeleton (config, migration SQL sintaksisi).
7. PHASE 1 tugagach STOP.

### Foydalanuvchidan kerak
- [ ] `lexuz.py` faylini yuklash
- [ ] `BOT-SYSTEM-PROMPT.md` faylini yuklash
- [ ] `skill-bilimlar/` ni skill'dan ko'chirishga ruxsat (yoki yangi versiyasini yuklash)
- [ ] PHASE 1 ni boshlashga tasdiq
