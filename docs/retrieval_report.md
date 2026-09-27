# Retrieval hisoboti — PHASE 3 (2026-09-27)

**Baza:** Supabase, 6 ta hujjat (Soliq, Mehnat, Fuqarolik 1–2, Bojxona kodekslari, Buxgalteriya hisobi
to'g'risidagi qonun), 24 254 element, 2 741 modda. Hammasi `amalda`.

**Qidiruv:** `app/retrieval/query.py` (so'rov tahlili) → `search_articles()` (migrations 004–005): normallashtirilgan
FTS (`simple`), IDF vazni, modda bo'yicha qamrov, iboralar, faqat `amalda` hujjatlar. LLM ishlatilmagan.

**Kutilgan moddalar** qidiruvdan oldin, modda sarlavhalarini o'qib belgilangan (`app/retrieval/evaluation.py`).
Belgilar: ✅ kutilgan ro'yxatda; 🟡 kutilgan ro'yxatda yo'q, lekin mavzuga yaqin; ❌ tegishli emas.
`SK` Soliq kodeksi, `MK` Mehnat kodeksi, `BK` Bojxona kodeksi, `BX` Buxgalteriya hisobi to'g'risidagi qonun, `FK2` Fuqarolik kodeksi 2-qism.

## Natijalar

| # | Savol | Holat | Top-1 | Top-2 | Top-3 | Asosiy modda top-3 da |
|---|---|---|---|---|---|---|
| 1 | Aylanma solig'idan QQSga qachon o'tish kerak? | ok | ✅ SK 462 Aylanmadan olinadigan soliqni qo'llash xususiyatlari | ❌ SK 243 QQS'dan ozod aylanma | ❌ SK 268 | ✅ (462; 237 — 5-o'rinda) |
| 2 | Norezidentga to'lovda qanday soliq majburiyati bor? | ok | ✅ SK 400 Norezidentlar daromadlariga soliq | 🟡 SK 347 | ✅ SK 356 | ✅ (400, 356; 351 — 5-o'rinda) |
| 3 | Hisobot topshirish muddati qachon? | ok | 🟡 BX 25 Moliyaviy hisobotni taqdim etish | ✅ SK 83 | ✅ SK 82 Soliq hisobotini taqdim etish tartibi | ✅ (82; 389 — 6-o'rinda) |
| 4 | Soliq imtiyozidan foydalanish uchun qanday shartlar bor? | ok | ✅ SK 75 Soliq imtiyozlari | ✅ SK 483 | ✅ SK 436 | ✅ |
| 5 | Jarima qanday hisoblanadi? | ok | ✅ SK 228 | ✅ SK 218 Moliyaviy sanksiyalar | 🟡 SK 55 Soliq qarzi | ✅ (218; 110 Penya — 6-o'rinda) |
| 6 | 2024-yilda bu norma qanday edi? | needs_clarification | — | — | — | ✅ manba qaytarilmadi |
| 7 | Qaysi modda bu talabni belgilaydi? | needs_clarification | — | — | — | ✅ manba qaytarilmadi |
| 8 | Korxona xodim bilan qanday mehnat shartnomasi tuzadi? | ok | 🟡 MK 127 Ishga qabul qilish to'g'risidagi buyruq | ❌ FK2 495 Korxonani topshirish | ✅ MK 111 Muddatli mehnat shartnomasini tuzish | ❌ (103/104/106 top-6 da yo'q) |
| 9 | Importda bojxona to'lovi qanday aniqlanadi? | ok | ✅ BK 53 (import rejimi) | 🟡 BK 56 Erkin muomalaga chiqarish (import) | 🟡 BK 294 Bojxona to'lovlarini to'lash majburiyati | ❌ (289/293/301/302/322/323 top-6 da yo'q) |
| 10 | Buxgalteriya hujjatini qancha vaqt saqlash kerak? | ok | ✅ BX 29 Buxgalteriya hujjatlarini saqlash | 🟡 BX 15 | 🟡 BX 5 | ✅ |

## Ko'rsatkichlar

| Ko'rsatkich | Natija |
|---|---|
| Top-1 kutilgan ro'yxatda (qidiruvli 8 savol) | **6 / 8** |
| Asosiy modda top-3 da | **6 / 8** |
| Kamida bitta kutilgan modda top-6 da | **8 / 8** |
| Noaniq savollar aniqlashtirishga yuborildi (6, 7) | **2 / 2** |
| Qaytarilgan hujjat holati `amalda` | **100%** |
| Havolalar bazadan (Lex.uz element ID'sidan) | **100%**, uydirma havola 0 |

Tekshiruv spec 26 talablari bo'yicha: *relevant source topildimi* — 8/8 (top-6); *article to'g'rimi* — asosiy modda 6/8;
*current/historical status to'g'rimi* — faqat `amalda`, tarixiy savolga joriy matn berilmaydi (test bilan tasdiqlangan);
*citation realmi* — ha, havola faqat bazadan.

## Kamchiliklar (ochiq)

1. **8-savol:** "korxona" so'zi Fuqarolik kodeksidagi "korxona (mulk majmuasi)" moddalarini tortadi; asosiy moddalar
   (103 "Mehnat shartnomasining tushunchasi", 106 "shakli") top-6 ga chiqmadi. Leksik qidiruv "korxona = ish beruvchi"
   ekanini bilmaydi.
2. **9-savol:** import rejimi moddalari topildi, lekin "Bojxona to'lovlarining turlari" (289) va "hisoblab chiqarish
   tartibi" (323) chiqmadi — savolda "aniqlanadi", matnda "hisoblab chiqariladi".
3. **3-savol** umumiy: soliq hisoboti ham, moliyaviy hisobot ham mos. To'g'ri yo'l — foydalanuvchidan aniqlashtirish
   yoki ikkala manbani ko'rsatish (PHASE 4 da javob qatlami).
4. **Tarixiy savollar:** versiya matni hali bazada yo'q, shuning uchun `historical_unavailable` qaytadi (joriy matn
   berilmaydi). Kerakli versiya `lexuz.load(on_date=...)` bilan olinadi — keyingi bosqich.

## Halollik izohi

- Kutilgan moddalar ro'yxatini men (qidiruv muallifi) tuzdim; ular modda sarlavhalariga asoslangan.
- Parametrlar qisman shu savollarda sozlandi: IDF + qamrov, iboralar vazni (0.6), "soliq" bilan ibora tuzmaslik,
  "import → olib kirish" sinonimini olib tashlash. Har bir o'zgarish umumiy sababga ega (PROGRESS.md), lekin
  overfitting xavfi bor — yangi savollar to'plamida qayta tekshirish kerak.

## Keyingi qadamlar (taklif)

- PHASE 4: fast model (Haiku) bilan savolni 2–4 qidiruv so'roviga qayta yozish (spec 6) — 8/9-savollardagi
  sinonim muammosini hal qilishi kutiladi; natija shu jadval bilan qayta o'lchanadi.
- Spec 7 Phase 2: pgvector + multilingual embeddings (hybrid) — MVP'dan keyin.
