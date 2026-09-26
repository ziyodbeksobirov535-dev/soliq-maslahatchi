# PROGRESS

Spec: `docs/MASTER_SPEC.md` (v3).

## PHASE 0 — Repository audit va Lex.uz parser (davom etmoqda)

### Bajarildi
- [x] Repository tuzilmasi (`app/` modullari, `tests/`, `migrations/`, `skill-bilimlar/`)
- [x] Python 3.11+ setup: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml` (pytest)
- [x] `.env.example`, `.gitignore`
- [x] Config (`app/config.py`) va logging (`app/utils/logging.py`: request_id, secret redaction)
- [x] `lexuz.py` fetch client: timeout, retry (408/425/429/5xx, tarmoq xatolari), exponential backoff,
      `Retry-After`, so'rovlar orasida delay, disk cache (TTL), ketma-ket so'rovlar, faqat lex.uz host
- [x] `doc_url` (`?ONDATE=DD.MM.YYYY` bilan) va `elem_link` (`https://lex.uz/docs/<doc>#<elem>`)
- [x] Testlar: 29 ta, hammasi o'tadi (fetch/retry/cache/HTTP error/bo'sh javob, config, logging)
- [x] README skeleton
- [x] `skill-bilimlar/` — foydalanuvchi skill'idan ko'chirildi

### Bloklangan: Lex.uz tarmoqdan yopiq
Bu cloud muhitning network policy'si `lex.uz` ni bloklaydi (curl va WebFetch — 403 / EGRESS_BLOCKED).
Shu sababli quyidagilar hali qilinmadi:
- [ ] Lex.uz agreement (`https://lex.uz/agreement`) ni o'qish va avtomatik yuklash shartlarini tekshirish
- [ ] `parse_doc` — metadata, sarlavha, hujjat ID, element ID/type, modda raqami, band matni, `COMMENT`
- [ ] `load`
- [ ] Parser unit testlari (real HTML fixture bilan)

Yechim (biri kifoya):
1. Muhit sozlamalarida Network access'ga `lex.uz` ni qo'shish, yoki
2. `tests/fixtures/lexuz/README.md` da ko'rsatilgan sahifalarni brauzerda saqlab, repoga yuklash.

### Qarorlar
- `lexuz.py` mustaqil modul (app/ ga bog'liq emas), sinxron `httpx` bilan. Async kod uni `asyncio.to_thread` orqali chaqiradi.
- Model ID'lari `.env.example` da: `claude-opus-5` (asosiy), `claude-haiku-4-5` (tezkor) — PHASE 4 da qayta tekshiriladi.
- Migrations PHASE 1 ga qoldirildi (v3 tartibi bo'yicha).
