# Bitim/operatsiya tarkibini soliq nuqtai nazaridan solishtirish — tayyor holatlar

Bu fayl 7-oqimda foydalaniladi. Quyidagi holatlar **mantiq namunasi** —
**aniq foiz/stavkalar bu yerda YO'Q**, chunki ular tez o'zgaradi. Har safar
javob berishda joriy stavkalarni (foyda solig'i, dividend solig'i, foizlar
bo'yicha ushlab qolinadigan soliq, QQS) `web_search`/`web_fetch` orqali
lex.uz/soliq.uz'dan tekshiring, keyin shu mantiqqa qo'ying.

## Holat 1: Muassis kompaniyaga pul kiritmoqchi (masalan aylanma mablag' to'ldirish uchun)

**Real maqsad**: kompaniyaning hisob-kitob hisobvarag'ini to'ldirish, real
qaytarish majburiyati yo'q (doimiy xarakterdagi kiritma).

| Variant | Kompaniya uchun oqibat | Muassis uchun oqibat |
|---|---|---|
| **A. "Daromad" sifatida kiritish** (masalan xayoliy xizmat/tovar evazi, yoki asossiz kirim sifatida) | Bu kompaniyaning jami daromadiga qo'shiladi → **foyda solig'i bazasini oshiradi**. Agar "sotuv" ko'rinishida rasmiylashtirilsa va kompaniya QQS to'lovchisi bo'lsa — **QQS ham** kelib chiqishi mumkin. | — |
| **B. Ustav fondiga (ustav kapitaliga) qo'shimcha hissa** | Bu **kapital operatsiyasi**, kompaniyaning soliq solinadigan daromadiga KIRMAYDI — foyda solig'i bazasini oshirmaydi. | Hozircha soliq oqibati yo'q (mulkni kompaniyaga topshirish). Kelajakda bu pulni kompaniyadan chiqarib olish (dividend sifatida) — **alohida bosqich**, o'z soliqqa tortilishi bilan (pastga qarang). |
| **C. Muassisdan kompaniyaga qarz (zayom)** | Kompaniya uchun bu **majburiyat** (passiv), daromad emas — foyda solig'i bazasiga kirmaydi. Agar foizli qarz bo'lsa, to'langan foiz kompaniya uchun **xarajat** bo'lishi mumkin (foyda solig'i bazasini kamaytiradi) — lekin bog'liq shaxslar/transfert narx cheklovlariga rioya qilingan holda (7-oqimdagi ogohlantirishga qarang). | Asosiy qarz summasini qaytarib olish — soliqqa tortilmaydi (bu shunchaki qarzning qaytarilishi). Agar foizli bo'lsa, olingan foiz — jismoniy shaxs uchun daromad, tegishli stavka bo'yicha soliqqa tortiladi (aniq stavkani live tekshiring — bank foizlaridan farqli tartib bo'lishi mumkin). |

**Xulosa mantiqi**: agar maqsad — kompaniyaga vaqtincha yoki doimiy mablag'
kiritish bo'lsa va "daromad" sifatida ko'rsatish shart emas (chunki bu
haqiqiy sotuv emas) — B yoki C variant odatda A dan sezilarli kam soliq
yukini beradi. B va C orasidagi tanlov esa **muassisning kelajakda pulni
qanday va qachon qaytarib olishni xohlashiga** bog'liq (pastga, Holat 2 ga
qarang).

## Holat 2: Yangi tasischi kompaniyaga pul kiritmoqchi, keyin uni chiqarib olish rejalashtirilgan

**Real maqsad**: mablag' kiritish + kelajakda (masalan foyda taqsimlanganda
yoki istalgan vaqtda) qisman/to'liq qaytarib olish imkoniyati.

| Variant | Kirish bosqichi | Ushlab turish | Chiqish bosqichi |
|---|---|---|---|
| **A. Ustav fondi hissasi** | Soliq oqibati yo'q. | Kompaniya foyda ko'rganda **foyda solig'i** (agar QQS to'lovchi bo'lsa, umumiy tartibda) to'laydi. | Foyda tasischiga **dividend** sifatida chiqarilganda — **dividend bo'yicha ushlab qolinadigan soliq** (joriy stavkani tekshiring) qo'shimcha to'lanadi. Ya'ni bitta pul ustiga **ikki bosqichli soliq** (kompaniya darajasida foyda solig'i + tasischi darajasida dividend solig'i). |
| **B. Muassisdan kompaniyaga qarz** | Soliq oqibati yo'q (majburiyat yaratiladi). | Agar foizli bo'lsa: kompaniya to'lagan foiz — **xarajat** (foyda solig'i bazasini kamaytiradi, bog'liq shaxs/transfert narx qoidalariga rioya qilinsa). | Qarz asosiy summasi qaytarilganda — bu **qarzning qaytarilishi**, qo'shimcha soliq yo'q. Foiz to'lansa — muassis bu foizdan **jismoniy shaxs sifatida soliq** to'laydi (dividend stavkasidan farqli, alohida tartib bo'lishi mumkin — live tekshiring), lekin kompaniya darajasida bu summa **avval xarajat sifatida foyda solig'i bazasidan chiqarilgan** bo'ladi — ya'ni A variantidagi "ikki bosqichli" soliqqa qaraganda odatda **kamroq umumiy soliq** kelib chiqadi.

**Xulosa mantiqi**: agar muassis kelajakda pulni qaytarib olishni
rejalashtirsa, **qarz strukturasi** ko'pincha ustav fondi + dividend
strukturasiga qaraganda kamroq umumiy soliq yukini beradi (chunki foizli
qarzda kompaniya darajasidagi soliq bazasi kamayadi, dividendda esa
kamaymaydi — ikki marta soliqqa tortiladi). **Lekin**: bu faqat qarz **real**
bo'lganda (haqiqiy shartnoma, muddat, bozor darajasidagi foiz, real
qaytarish niyati) to'g'ri keladi — aks holda 14-modda (iqtisodiy mazmun) va
bog'liq shaxslar/transfert narx qoidalari asosida qayta tasniflanish xavfi
bor (7-oqimdagi ogohlantirishga qarang).

## Umumiy prinsip (boshqa holatlar uchun ham qo'llash mumkin)

Har qanday "pul/mulk A dan B ga o'tishi" operatsiyasida ko'pincha kamida
uch xil yuridik shakl mavjud bo'ladi:
1. **Aylanma/daromad operatsiyasi** (sotuv, xizmat) — odatda eng ko'p soliq
   bosqichini (QQS + foyda solig'i) keltirib chiqaradi.
2. **Kapital operatsiyasi** (ustav fondi hissasi, keyin dividend) — kirishda
   soliqsiz, lekin chiqishda (dividend) alohida soliq, va bu compania
   darajasidagi foyda solig'i bazasini KAMAYTIRMAYDI.
3. **Qarz operatsiyasi** — kirish/asosiy summa qaytarilishi soliqsiz, foiz
   bo'lsa ikki tomonlama oqibat (kompaniya uchun xarajat/kamaytiruvchi,
   jismoniy shaxs uchun daromad/soliq), lekin bog'liq shaxslar
   cheklovlariga bo'ysunadi.

Har safar yangi holat kelganda shu uch (yoki ko'proq, agar tegishli bo'lsa —
masalan grant/sovg'a) variantni sanab, jadval qilib solishtiring.
