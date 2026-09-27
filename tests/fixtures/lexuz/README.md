# Lex.uz real namunalari (2026-09-26/27 da yuklangan)

Parser testlari faqat shu real sahifalar asosida yoziladi. Yangilash kerak bo'lsa —
`lexuz.LexUzClient().fetch(url)` bilan qayta yuklab, testlarni qayta tekshiring.

| Fayl | Manba | Nimani tekshiradi |
|---|---|---|
| `soliq-kodeksi.html.gz` | https://lex.uz/docs/-4674902 (versiya 06.08.2026) | to'liq parsing, 461-modda, jadval, izohlar, versiyalar |
| `soliq-kodeksi-2007-ru.html.gz` | https://lex.uz/docs/1286689 | rus tilidagi, kuchini yo'qotgan hujjat, `edi<N>` ID formati |
| `pf-206-matnsiz.html` | https://lex.uz/docs/-8509858 | matni hali e'lon qilinmagan hujjat, raqamli sarlavha |
| `card1-soliq-kodeksi.html` | https://lex.uz/actinfo/card1/-4674902 | holat "Действующий" |
| `card1-soliq-kodeksi-uz-qiymat.html` | o'sha, boshqa sessiyada | holat o'zbekcha "Amalda" |
| `card1-vm-508-kelajakda.html` | https://lex.uz/actinfo/card1/-8503735 | kelajakda kuchga kiradi, lekin "Действующий" |
| `card1-soliq-kodeksi-2007.html` | https://lex.uz/actinfo/card1/1286689 | "Утративший силу" + kuchini yo'qotgan sana |
| `card1-pf-206.html` | https://lex.uz/actinfo/card1/-8509858 | hujjat raqami |
| `agreement.html` | https://lex.uz/agreement | foydalanish shartlari |
| `rss.xml` | https://lex.uz/uz/rss | PHASE 6 uchun |
| `search-soliq-imtiyoz.html.gz` | https://lex.uz/uz/search/nat?searchtitle=soliq+imtiyoz&status=Y&lang=4 | qidiruv: 20 natija, jami 30, keyingi sahifa postback'i, ikki xil badge |
| `search-soliq-imtiyoz-p2.html.gz` | o'sha, `LinkButton1` postback (POST) | oxirgi sahifa: 10 natija (21–30), "Keyingisi" havolasi yo'q |
| `search-aralash-holat.html.gz` | https://lex.uz/uz/search/nat?searchtitle=soliq+imtiyoz&lang=4 | holat filtrisiz: `status_code_y` va `status_code_r`, jami 84 |
| `search-bosh.html.gz` | https://lex.uz/uz/search/nat?searchtitle=qwzxqwzx&lang=4 | natija yo'q |
