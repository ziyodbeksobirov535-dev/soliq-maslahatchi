# Bilim bazasi — to'planib boruvchi xotira

Bu fayl har safar chuqur tekshirilgan mavzular bo'yicha **sana bilan** to'ldirib boriladi. Formatga rioya qiling: mavzu → xulosa → modda/manba → tekshirilgan sana. Eskirish qoidasi uchun SKILL.md dagi "Qidirishdan oldin" bo'limiga qarang.

---

## Asosiy stavkalar (tekshirilgan: 2026-avgust)
- Foyda solig'i (umumiy): **15%**
- QQS (umumiy): **12%**
- Rezidentga dividend/foiz: **5%**
- Norezidentga dividend/shunga tenglashtirilgan daromad (to'lov manbaida): **~10%** (**351-modda**), xalqaro shartnoma bo'lsa pasaytirilishi mumkin (**354, 357, 358-modda**)
- Manba: https://lex.uz/docs/-4674902, [soliq.uz](https://soliq.uz/press-services/news/show/foyda-soligi-boyicha-qonunchilikka-kiritilgan-ozgarishlar)

## ⚠️ TUZATISH (2026-avgust) — QQS to'lovchi bo'lish chegarasi o'zgargan

**Xato aniqlangan**: `kodeks-toliq/11-aylanma-soligi.txt` dagi 461-modda "1 mlrd so'm"
chegarani ko'rsatadi (2026-yil 2-iyul holatiga), lekin bu **YANGILANGAN**:

**2026-yil 1-iyundan 2030-yil 1-yanvargacha**, Prezident farmoni bilan
**savdo, umumiy ovqatlanish va xizmat ko'rsatish sohalari** uchun QQS
to'lovchi bo'lish chegarasi **BHMning 12 000 barobariga** (2026-yilda
412 000 × 12 000 = **~4,94 mlrd so'm**) oshirilgan. Shu davrda qo'shimcha
tanlov ham bor: **6% soddalashtirilgan QQS + foyda solig'idan ozod**,
yoki umumiy tartibda davom etish.
Manba: [spot.uz, 2026-yil 9-iyun](https://www.spot.uz/oz/2026/06/09/vat-payer)

**Sabab-natija darsi**: bu — Soliq kodeksining o'zida (461-modda matni)
emas, balki **alohida Prezident farmonida** joylashgan maxsus/vaqtinchalik
rejim, shuning uchun `kodeks-toliq/` korpusida (bu faqat kodeks matni)
ko'rinmaydi. **Chegara/stavka kabi "faol o'zgaruvchan" mavzularda, hatto
mahalliy korpusda javob topilgan taqdirda ham, QOʻSHIMCHA LIVE QIDIRUV
qiling** — ayniqsa agar korpusning o'zida "yaqinda o'zgargan" deb
qayd etilgan modda bo'lsa (bu — signal, ko'proq ehtiyot bo'lish kerak
degani, "javob topildi, tugadi" degani emas).
- **BHM (bazaviy hisoblash miqdori)**: **412 000 so'm** (2026-yil, manba: https://lex.uz/bhm — rasmiy kalkulyator, doim joriy qiymatni ko'rsatadi)
- **MHTEKM (mehnatga haq to'lashning eng kam miqdori)**: **1 155 000 so'm** (manba: gov.uz)
- **Pensiya hisoblashning bazaviy miqdori**: 2026-yil 1-iyuldan **504 000 so'm** (PF-115-son, 23-iyun 2026)
- ⚠️ Bu ko'rsatkichlar **yiliga bir necha marta** o'zgaradi (odatda farmon bilan) — har safar aniq hisob-kitobda ishlatishdan oldin https://lex.uz/bhm dan joriy qiymatni tasdiqlang, bu sahifa har doim eng yangi BHM'ni ko'rsatadi.
- Tekshirilgan: 2026-avgust

## 6% soddalashtirilgan QQS vs umumiy rejim — breakeven formula (tasdiqlangan, 2026-avgust)

Savdo/ovqatlanish/xizmat sohalarida (2026-yil 1-iyundan 2030-yil 1-yanvargacha
amal qiluvchi maxsus rejim, yuqoridagi tuzatishga qarang) 6% soddalashtirilgan
QQS (foyda solig'idan ozod) va umumiy rejim (QQS 12% + foyda solig'i 15%,
sodda holatda) orasidagi tanlov **to'liq marjaga bog'liq**:

- **Umumiy rejim yuk** ≈ marja × 27% (QQS 12% + foyda solig'i 15%, xarajatlarsiz sodda hisobda)
- **6% rejim yuk** ≈ aylanma × 6%
- **Breakeven nuqtasi** ≈ marja/aylanma nisbati **~22%** atrofida (6% ÷ 27% ≈ 22,2%)
- **Qoida**: marja **22% dan past** bo'lsa → umumiy rejim arzonroq (past-o'rta marjali chakana savdo — masalan qurilish mollari, odatda 7-20% — deyarli har doim shu toifaga tushadi). Marja **22% dan yuqori** bo'lsa (masalan yuqori nacenka xizmat/restoran turlari) → 6% rejim foydali bo'lishi mumkin.
- ⚠️ Bu — sodda formula, real operatsion xarajatlar (ijara, ish haqi) umumiy rejimdagi foyda solig'i bazasini yanada kamaytiradi, ya'ni umumiy rejim bu formuladagidan ham arzonroq chiqishi mumkin — aniq hisobda xarajatlarni albatta hisobga oling.
- Har bir mijoz uchun ishlatish: marjani so'rang → yuqoridagi 22% chegara bilan solishtiring → kerak bo'lsa to'liq jadval bilan (ikkala rejimning aniq summasi) tasdiqlang.

## Norezidentga to'lov manbaida ushlab qolinadigan soliq — 353-modda (TO'LIQ TASDIQLANGAN, 2026-yil 2-iyul)
- Dividend va foizlar: **10%**
- Sug'urta mukofotlari: **10%**
- Xalqaro aloqa/tashish (freyt): **6%**
- Investitsiya loyihasi krediti foizlari (bank/lizing beruvchi orqali chet el moliya institutiga): **0%**
- Rezident banklarning vakillik hisobvarag'i xizmatlari: **0%**
- **Boshqa daromadlar** (351-modda 17-18-band, jumladan boshqaruv/texnik/maslahat xizmatlari — masalan tadbir tashkil etish): **20%**
- Manba: `references/kodeks-toliq/5-foyda-soligi.txt` (351-358-modda shu faylda), asl PDF 2026-yil 2-iyul holatiga
- Tekshirilgan: 2026-avgust — TO'LIQ MATNDAN, taxmin emas

## Qishloq xo'jaligi — foyda solig'i 0%
- **57-modda TO'LIQ MATNI TOPILDI (2026-avgust)**: "qishloq xo'jaligi tovar ishlab chiqaruvchisi" deb tan olinishi uchun BIRGALIKDA ikki shart: (1) mahsulot ishlab chiqaruvchi VA uni birlamchi qayta ishlovchi bo'lishi, jami daromadida o'zi ishlab chiqargan (shu jumladan o'zi ishlab chiqargan xom ashyoni qayta ishlashdan olingan) mahsulot ulushi **kamida 80%** bo'lishi kerak; (2) tegishli yer uchastkalariga ega bo'lishi kerak. **Sanoatda qayta ishlangan mahsulot bu ta'rifga kirmaydi.**
- Qishloq xo'jaligi mahsuloti ta'rifiga **chorvachilik, parrandachilik, asalarichilik, ipakchilik, baliqchilik** mahsulotlari ham aniq kiritilgan.
- ✅ Bu — avvalgi "sotib olib boqilgan chorva yetishtirilgan hisoblanadimi" savolini hal qiladi: asosiy mezon **80% daromad ulushi**, hayvonni qanday olganingiz emas — agar chorvachilik faoliyatidan (boqish/urchitish orqali) daromadingiz jami daromadning 80%+ini tashkil qilsa, mezonga javob berasiz.
- Manba: `references/kodeks-toliq/1-umumiy-qismi.txt`, 57-modda (2026-yil 2-iyul holatiga)
- Tekshirilgan: 2026-avgust — TO'LIQ MATNDAN

## Qishloq xo'jaligi — QQS 0% (264-modda)
- **264-modda aniq matni** (paraphrase): qishloq xo'jaligi tovar ishlab chiqaruvchilari tomonidan **yetishtirilgan** hamda Qishloq xo'jaligi vazirligi va Soliq qo'mitasi tomonidan tasdiqlangan ro'yxatga (paxta va g'alladan tashqari) kiritilgan mahsulotlarni realizatsiya qilish aylanmasiga 0% stavka qo'llanadi.
- Ikki shart birgalikda: (1) "yetishtirilgan" (57-modda mezoni — HALI TO'LIQ ANIQLANMAGAN, keyingi tekshiruvda 57-modda to'liq matnini olish kerak), (2) rasmiy ro'yxatda bo'lish (PF-153-son, 04.09.2025 — Qishloq xo'jaligi vazirligi + Soliq qo'mitasi tasdiqlagan, 14 ta mahsulot turi, jumladan tirik buzoq/sigir/buqa/qo'y/echki/ot/tuya/eshak/baliq/asalari/ipak qurti)
- Manba: https://lex.uz/docs/-4674902, [gazeta.uz](https://www.gazeta.uz/oz/2026/05/18/nol-qqs/)
- ⚠️ ochiq savol: sotib olib keyin uzoq boqilgan (masalan 3 yil) chorva "yetishtirilgan" hisoblanadimi — 57-moddaning to'liq matni bilan tasdiqlanmagan, keyingi safar birinchi ish sifatida 57-modda to'liq matnini o'qib chiqish kerak
- Tekshirilgan: 2026-avgust

## QQS mexanizmi — 0% stavka vs ozod qilish farqi
- 0% stavka (masalan 264-modda) — kirish QQS (zachet) huquqi SAQLANADI, faqat "ozod qilish" (exemption) da yo'qoladi
- Qishloq xo'jaligi ishlab chiqaruvchilari (paxta/g'alladan tashqari) uchun 3 kunlik tezlashtirilgan QQS qoplash: **274-modda**
- Manba: https://lex.uz/docs/-4674902, [buxgalter.uz](https://buxgalter.uz/oz/publish/doc/text212516_2026_yil_uchun_uzbekiston_respublikasi_soliq_kodeksida_qanday_uzgarishlar_kutilmoqda)
- Tekshirilgan: 2026-avgust

## Chorvachilik — nasldor chorva import QQS ozod
- 2026-yil 1-iyundan 2029-yil 1-yanvargacha (ba'zi manbalarda 1-avgust deyilgan, lex.uz asosiy manba 1-yanvar deydi — asosiy manbaga ishoning) xorijdan nasldor qoramol/qo'y/echka olib kirish QQS'dan ozod
- Manba: **PQ-179-son, 12.05.2026**, https://lex.uz/uz/docs/-8214026
- Tekshirilgan: 2026-avgust

## O'zbekiston-Tojikiston ikki tomonlama soliq shartnomasi
- Hujjat: 09.03.2018, kuchga kirgan 06.06.2018, https://lex.uz/docs/3799860
- Dividend: kompaniya + kamida 25% ulush — 5%; boshqa holatlarda (shu jumladan jismoniy shaxs) — 10% (10-modda)
- Foiz: barcha holatlarda 10% (11-modda)
- Tekshirilgan: 2026-avgust

## Ochiq savollar — YANGILANDI 2026-avgust (asosiylari yopildi)

- ✅ **351-modda, 2-qism, 18 bandning to'liq matni** — TOPILDI, `references/kodeks-toliq/5-foyda-soligi.txt` faylida to'liq. Endi ochiq emas.
- ✅ **57-moddadagi mezon** — TOPILDI (80% daromad ulushi + yer uchastkasi). Endi ochiq emas.
- ⚠️ **DM ro'yxatdan o'tganda qo'shimcha 10% ("filial foydasi solig'i")** — bu qoida FAQAT 1997-2005 yillardagi eski tahrirda topilgan edi. `kodeks-toliq/5-foyda-soligi.txt` faylida 351-358-modda orasida bu haqda aniq band ko'rinmadi — ehtimol bekor qilingan. Keyingi safar shu faylda яна bir bor maxsus qidiring (masalan "chet elga oʻtkaz" so'zi bilan grep) va tasdiqlang.
- **DM chegarasi — tasdiqlangan**: istalgan ketma-ket 12 oylik davrda 183 kalendar kundan ortiq faoliyat = DM. Manba: https://lex.uz/mact/-1286558 (metodik qo'llanma) — endi `references/kodeks-toliq/1-umumiy-qismi.txt` dagi 36-moddada ham tasdiqlash mumkin.
- **Shveytsariya bilan shartnoma — tasdiqlangan**: 2002-yil 3-aprel, kuchga kirgan 2003-yil 15-avgust. Manba: https://lex.uz/docs/265768 (VM 183-son, 29.05.2002)

## Mol-mulk/yer solig'i — qishloq xo'jaligi, yangi 2026 shart
- 414-modda (mol-mulk), 428-modda (yer) imtiyozlari endi 75-modda asosida yangi shartga bog'liq: (1) aylanma imtiyoz summasidan katta, (2) kamida 3 xodim
- Manba: https://lex.uz/docs/-4674902, [mf.uz](https://api.mf.uz/media/filestore/Sharx_26-11.pdf)
- Tekshirilgan: 2026-avgust
