# Soliq kodeksi — TO'LIQ MATN (2026-yil 2-iyul holatiga, lex.uz'dan)

⚠️ **Bu — eng katta yutuq**: foydalanuvchi lex.uz'dan brauzer orqali "chop etish" qilib
saqlagan, kodeksning **butun 408 sahifalik matnini** o'z ichiga olgan PDF asosida
tuzilgan. Bu fayllar orqali endi **web_fetch'ning kesilish muammosisiz** istalgan
moddani to'liq o'qish mumkin — `grep`/`view` orqali qidiring, internet kerak emas.

## Qanday foydalanish kerak

1. **Modda raqami ma'lum bo'lsa** — to'g'ridan-to'g'ri qidiring:
   ```
   grep -n "^351-modda\." /home/claude/soliq-maslahatchi/references/kodeks-toliq/*.txt
   ```
   yoki mos faylni pastdagi jadvaldan aniqlab, `view` bilan o'sha qatordan o'qing.
2. **Mavzu bo'yicha qidirish kerak bo'lsa** — kalit so'z bilan grep qiling:
   ```
   grep -n -i "qishloq xoʻjaligi" /home/claben/soliq-maslahatchi/references/kodeks-toliq/5-foyda-soligi.txt
   ```
3. **Modda topilgach** — o'sha qatordan boshlab ~100-200 qatorni `view` bilan o'qing
   (modda odatda shuncha qatorda tugaydi, keyingi modda raqami ko'ringanda to'xtang).

## ⚠️ Muhim eslatma — sana

Bu matn **2026-yil 2-iyul** holatiga tegishli (PDF sarlavhasidagi vaqt belgisidan).
Bu degani:
- **Rejalar/qismlar/mezonlar** (definitsiyalar) — ishonchli, chunki bular kam o'zgaradi.
- **Aniq foiz/summa/muddat** — SKILL.md dagi "eng oxirgi tahrir" qoidasiga muvofiq,
  agar 2026-yil 2-iyuldan keyin o'zgargan bo'lishi mumkin bo'lsa (masalan yangi
  qonun/farmon e'lon qilingan bo'lsa), **baribir live tekshiring**. Bu fayl —
  boshlang'ich nuqta, yakuniy haqiqat emas.
- Agar foydalanuvchi kelajakda yangilangan versiyani (masalan yana PDF) yuborsa,
  shu papkani yangi fayllar bilan almashtiring va sanani shu faylda yangilang.

## Fayllar xaritasi (bo'lim → fayl)

| Bo'lim | Fayl | Qamrab oladi |
|---|---|---|
| I bo'lim | `1-umumiy-qismi.txt` | 1-75-modda: asosiy qoidalar, tushunchalar (jumladan 14-modda iqtisodiy mazmun, 36-modda DM, 37-modda bog'liq shaxslar, 57-modda qishloq xo'jaligi ishlab chiqaruvchisi, 75-modda soliq imtiyozlari) |
| II bo'lim | `2a-soliq-hisobi-hisobot.txt` | 76-84-modda: soliq hisobi va hisobot |
| III bo'lim | `2b-soliq-majburiyatini-bajarish.txt` | 85-125-modda: majburiyat, to'lash, penya (110-modda), qarz undirish |
| IV bo'lim | `2c-hisobga-olish.txt` | 126-134-modda: soliq to'lovchilarni hisobga olish, STIR |
| V bo'lim | `2d-soliq-nazorati.txt` | 135-168-modda: tekshiruvlar (kameral 138, sayyor 139), audit |
| VI bo'lim | `2e-transfert-narx.txt` | 169-202-modda: soliq monitoringi, transfert narx nazorati, bog'liq shaxs bitimlari |
| VII bo'lim | `2f-cfc-chet-el-kompaniya.txt` | 203-209-modda: nazorat qilinadigan chet el kompaniyalari (CFC) |
| VIII bo'lim | `2g-huquqbuzarlik-javobgarlik.txt` | 210-226+ modda: huquqbuzarlik va javobgarlik (223-modda soliq bazasini yashirish) |
| X bo'lim | `3-qqs.txt` | 237-283-modda: QQS/NDS (soliq to'lovchilar, realizatsiya, ozod qilish 243-246, 0% stavka 260-264, korrektirovka) |
| XI bo'lim | `4-aksiz.txt` | Aksiz solig'i |
| XII bo'lim | `5-foyda-soligi.txt` | 294-358-modda: foyda solig'i (soliq bazasi, xarajatlar 305+, imtiyozlar 337, investitsiya chegirmasi 308), **shu faylning oxirida: 351-358-modda — norezidentlarga soliq solish** (stavkalar 353-modda, soliq agentlari 352, xalqaro shartnoma 357-358) |
| XIII bo'lim | `6-jshds.txt` | 369-399-modda: jismoniy shaxslar daromad solig'i (JSHDS), soliqsiz daromadlar (369, 378-modda) |
| XIV bo'lim | `7-ijtimoiy-soliq.txt` | Ijtimoiy soliq (403-405-modda) |
| XV bo'lim | `8-mol-mulk-soligi.txt` | Mol-mulk solig'i (411, 414-modda) |
| XVI bo'lim | `9-yer-soligi.txt` | Yer solig'i (424-437-modda) |
| XVII-XVIII bo'lim | `10-suv-yer-qaridan-renta.txt` | Suv resurslari, yer qa'ridan foydalanish, renta solig'i |
| XX bo'lim | `11-aylanma-soligi.txt` | Aylanmadan olinadigan soliq (461-467-modda) |
| XXI bo'lim | `12-ayrim-toifalar-xalqaro.txt` | Ayrim toifadagi soliq to'lovchilar (YAT va h.k.) |

## Rasmiy soliq imtiyozlari ro'yxati (858 ta band, byudjet ochiqligi nizomiga 9-ilova)

Foydalanuvchi tomonidan taqdim etilgan rasmiy hujjat (2024-yil 9 oylik holatiga,
Moliya vazirligi/soliq qo'mitasi tomonidan tasdiqlangan) — har bir soliq turi
bo'yicha aniq modda, hujjat sanasi/raqami va **amal qilish muddati** bilan.

- **`soliq-imtiyozlari-royxati.csv`** — barcha 858 ta band (tarixiy, shu jumladan
  eskirganlari ham — solishtirish/tarix uchun kerak bo'lsa).
- **`soliq-imtiyozlari-FAOL.csv`** — faqat **hozir amaldagi** 507 ta band
  (2026-yil avgust holatiga muddati o'tmaganlar). ⚠️ **5-oqim (imtiyoz qidirish)da
  har doim shu FAOL faylni ishlating**, to'liq faylni emas — 858 tadan **351 tasi
  (41%) allaqachon muddati o'tgan** (ko'pchiligi 2024-2025 yillarda tugagan), ularni
  amaldagi imtiyoz sifatida taqdim etish jiddiy xato bo'ladi.
- Ustunlar: `Tartib_raqami, Soliq_turi, Imtiyoz_nomi (modda+tavsif), Hujjat_turi,
  Hujjat_sanasi, Hujjat_raqami, Amal_qilish_muddati`.
- Qidirish uchun: `grep -i "kalit_soz" soliq-imtiyozlari-FAOL.csv` yoki Python/pandas
  bilan `Soliq_turi` ustuni bo'yicha filtrlang.
- ⚠️ Bu ro'yxat ham 2024-yil 9 oylik holatiga — undan keyin qabul qilingan yangi
  imtiyozlar (masalan PF-153, PQ-179 — bilimlar-bazasi.md'da bor) bu faylda **yo'q**,
  ularni alohida hisobga oling.

Norezidentga (DM yo'q) to'lov manbaida ushlab qolinadigan soliq:
- Dividend va foizlar: **10%**
- Sug'urta mukofotlari: **10%**
- Xalqaro aloqa/tashish (freyt): **6%**
- Investitsiya krediti foizlari (bank orqali): **0%**
- Bank vakillik hisobvarag'i xizmatlari: **0%**
- **Boshqa daromadlar** (17-18-band, jumladan boshqaruv/texnik/maslahat xizmatlari): **20%**

Manba: 353-modda, ushbu papkadagi `12-ayrim-toifalar-xalqaro.txt` fayli (yoki asl PDF).
