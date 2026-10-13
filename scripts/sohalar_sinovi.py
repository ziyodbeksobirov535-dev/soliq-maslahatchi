"""Sohalar bo'yicha qidiruv sinovi (Supabase, botdagi `retrieve`): har savolga kutilgan modda(lar) top-1/3/6 da.

    python scripts/sohalar_sinovi.py          # yig'indi har soha bo'yicha
    python scripts/sohalar_sinovi.py -v       # har savol: o'rni, qidiruv so'zlari, top-3
    python scripts/sohalar_sinovi.py --yangi  # 2-to'plam (tuzatishlarning ikkinchi bosqichida qaralgan)
    python scripts/sohalar_sinovi.py --uchinchi  # 3-to'plam (tuzatishlarda qaralmagan savollar)

Kutilgan moddalar qidiruvdan mustaqil — Lex.uz modda sarlavhalarini o'qib belgilangan (2026-10-13). Savollar
so'zlashuv tilida: imlo xatolari, ruscha so'zlar ("NDS", "nalog", "aborot"), kirill va rus tilidagi savollar.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database.connection import connect  # noqa: E402
from app.retrieval.search import retrieve  # noqa: E402

SK, MK, BK, BX = "-4674902", "-6257288", "-2876354", "-2931253"


def sk(*n: str) -> set[tuple[str, str]]:
    return {(SK, x) for x in n}


CASES: dict[str, list[tuple[str, set[tuple[str, str]]]]] = {
    "QQS": [
        ("QQSni kim to'laydi?", sk("237")),
        ("QQS to'lovchisi kim hisoblanadi?", sk("237")),
        ("QQS stavkasi necha foiz?", sk("258")),
        ("Qanday tovarlar QQSdan ozod qilinadi?", sk("243")),
        ("Moliyaviy xizmatlar QQSdan ozodmi?", sk("244")),
        ("QQS bo'yicha soliq davri qancha?", sk("259")),
        ("QQS hisobotini qachon topshirish kerak?", sk("273")),
        ("Eksportda QQS qanday stavkada olinadi?", sk("260")),
        ("Xalqaro tashish xizmatlariga QQS", sk("263")),
    ],
    "Aylanma solig'i": [
        ("Aylanma solig'ini kimlar to'laydi?", sk("461")),
        ("aylanma soligi stavkasi qancha", sk("467")),
        ("Aylanmadan olinadigan soliq hisobotini qachon topshiraman?", sk("470")),
        ("Aylanma solig'i bo'yicha soliq davri", sk("469")),
        ("Aylanma solig'ining soliq bazasi nima?", sk("464")),
    ],
    "Foyda solig'i": [
        ("Foyda solig'i to'lovchilari kimlar?", sk("294")),
        ("Foyda solig'i stavkasi qancha?", sk("337")),
        ("Foyda solig'ini qachon to'lash kerak?", sk("340", "339")),
        ("Zararni kelgusi yilga o'tkazish mumkinmi?", sk("333")),
        ("Qaysi xarajatlar chegirib tashlanmaydi?", sk("317")),
        ("Dividendlardan qancha soliq olinadi?", sk("337", "343", "345", "381")),
    ],
    "JSHDS": [
        ("Jismoniy shaxslardan olinadigan daromad solig'i stavkasi", sk("381")),
        ("Ish haqidan qancha soliq ushlanadi?", sk("381", "388")),
        ("Qanday daromadlarga soliq solinmaydi?", sk("378")),
        ("Norezident jismoniy shaxs uchun soliq stavkasi", sk("382")),
        ("Jami yillik daromad deklaratsiyasini qachon topshirish kerak?", sk("397", "389", "398")),
    ],
    "Ijtimoiy soliq": [
        ("Ijtimoiy soliq stavkasi qancha?", sk("405")),
        ("Ijtimoiy soliqni kim to'laydi?", sk("402")),
    ],
    "Mol-mulk solig'i": [
        ("Korxonalar uchun mol-mulk solig'i stavkasi", sk("415")),
        ("Jismoniy shaxslar mol-mulk solig'i stavkasi", sk("422")),
        ("Mol-mulk solig'i bo'yicha imtiyozlar", sk("414", "421")),
        ("Uyim uchun mol-mulk solig'ini kim to'laydi?", sk("418")),
    ],
    "Yer solig'i va boshqalar": [
        ("Yuridik shaxslar yer solig'i stavkasi", sk("429")),
        ("Jismoniy shaxslar yer solig'ini qachon to'laydi?", sk("440")),
        ("Yer solig'idan imtiyozlar", sk("428", "436")),
        ("Suv resurslaridan foydalanganlik uchun soliq stavkasi", sk("445")),
        ("Yer qa'ridan foydalanganlik uchun soliqni kim to'laydi?", sk("449")),
        ("Aksiz solig'ini kim to'laydi?", sk("283")),
        ("Aksiz solig'i stavkalari", sk("289", "289-1", "289-2", "289-3")),
    ],
    "Umumiy qoidalar": [
        ("Soliqni kech to'lasam penya qancha bo'ladi?", sk("110")),
        ("Ortiqcha to'langan soliqni qanday qaytarib olaman?", sk("103", "104")),
        ("Soliq hisobotini kech topshirganlik uchun jarima", sk("220")),
        ("Soliq auditi qancha muddat davom etadi?", sk("141")),
        ("Kameral soliq tekshiruvi nima?", sk("138")),
        ("Soliq hisobotini qanday tartibda topshirish kerak?", sk("82")),
        ("Soliq hisobotini saqlash muddati", sk("84")),
        ("Soliq agenti kim?", sk("23")),
        ("Soliq to'lashni kechiktirish yoki bo'lib-bo'lib to'lash mumkinmi?", sk("100", "101", "97")),
        ("Soliqni to'lamaganlik uchun javobgarlik", sk("224")),
    ],
    "Mehnat": [
        ("Yillik mehnat ta'tili necha kun?", {(MK, "217")}),
        ("Sinov muddati qancha bo'ladi?", {(MK, "130")}),
        ("Ishdan bo'shatilganda qancha nafaqa beriladi?", {(MK, "173")}),
        ("Xodim o'z xohishi bilan ishdan ketsa nima qilish kerak?", {(MK, "160")}),
        ("Homiladorlik va tug'ish ta'tili", {(MK, "404")}),
        ("Ish haqi qachon to'lanishi kerak?", {(MK, "253")}),
        ("Ish vaqtining normal davomiyligi qancha?", {(MK, "182")}),
        ("Mehnat shartnomasi qanday shaklda tuziladi?", {(MK, "106")}),
    ],
    "Buxgalteriya": [
        ("Buxgalteriya hujjatlarini saqlash muddati", {(BX, "29")}),
        ("Moliyaviy hisobotni qachon topshirish kerak?", {(BX, "25")}),
        ("Inventarizatsiya qachon o'tkaziladi?", {(BX, "16")}),
    ],
    "Bojxona": [
        ("Bojxona to'lovlarining turlari", {(BK, "289")}),
        ("Bojxona qiymatini aniqlash usullari", {(BK, "302")}),
        ("Bojxona to'lovlarini to'lash muddati", {(BK, "327")}),
    ],
    "So'zlashuv, rus, kirill": [
        ("NDS stavkasi qancha?", sk("258")),
        ("nalog na pribil stavkasi", sk("337")),
        ("aborotdan olinadigan soliq stavkasi", sk("467")),
        ("QQS stafkasi qancha", sk("258")),
        ("penya qanday hisoblanadi", sk("110")),
        ("otpusk necha kun beriladi", {(MK, "217")}),
        ("deklaratsiyani kech topshirsam shtraf qancha", sk("220")),
        ("ҚҚС ставкаси қанча?", sk("258")),
        ("Какая ставка НДС?", sk("258")),
        ("Кто платит налог с оборота?", sk("461")),
        ("firmamning aboroti 2 mlrd, qqs to'lovchi bo'lamanmi", sk("461", "237")),
    ],
}

# Nazorat to'plami: tuzatishlar paytida qaralmagan savollar (umumlashuvni tekshirish uchun). `--yangi` bilan.
YANGI: dict[str, list[tuple[str, set[tuple[str, str]]]]] = {
    "Soliqlar (yangi)": [
        ("QQS qanday hisoblanadi?", sk("265", "248")),
        ("QQSni qaytarib olish mumkinmi?", sk("274")),
        ("Hisobvaraq-fakturani noto'g'ri rasmiylashtirsam jarima bormi?", sk("225")),
        ("Import qilingan tovarlar bo'yicha QQS", sk("277", "254", "246")),
        ("Aylanma solig'idan QQSga o'tish tartibi", sk("462")),
        ("YaTT aylanma solig'ini qanday hisoblaydi?", sk("465", "470")),
        ("Aylanma soliqda nima soliq solish obyekti hisoblanadi?", sk("463")),
        ("Foyda solig'i bo'yicha hisobot davri", sk("338")),
        ("Foyda solig'i bazasi qanday aniqlanadi?", sk("296")),
        ("Qanday daromadlar foyda solig'iga tortilmaydi?", sk("304")),
        ("Daromad solig'ini kim to'laydi?", sk("364")),
        ("JSHDS bo'yicha soliq davri", sk("384")),
        ("Ijtimoiy soliq qachon to'lanadi?", sk("407")),
        ("Ijtimoiy soliq bazasi nima?", sk("404")),
        ("Jismoniy shaxslar mol-mulk solig'ini qachon to'laydi?", sk("423")),
        ("Korxona yer solig'ini qanday to'laydi?", sk("432", "431")),
        ("Suv solig'ini kim to'laydi?", sk("441")),
        ("Alkogol mahsulotlariga aksiz stavkasi", sk("289-2")),
        ("Tamaki mahsulotlari aksiz solig'i", sk("289-1")),
    ],
    "Umumiy (yangi)": [
        ("Soliq to'lovchining huquqlari qanday?", sk("21")),
        ("Soliq to'lovchining majburiyatlari", sk("22")),
        ("Soliq tekshiruvi turlari", sk("137")),
        ("Sayyor soliq tekshiruvi qanday o'tkaziladi?", sk("139")),
        ("Soliq organida hisobga qo'yish tartibi", sk("129", "128")),
        ("Moliyaviy sanksiyalar nima?", sk("218")),
        ("Soliq javobgarligiga tortish muddati", sk("217")),
        ("Kassa apparatini qo'llamaganlik uchun jarima", sk("221")),
        ("Soliq bazasini yashirganlik uchun javobgarlik", sk("223")),
    ],
    "Mehnat (yangi)": [
        ("Ish beruvchi xodimni ishdan bo'shatishdan oldin qancha muddat oldin ogohlantiradi?", {(MK, "165")}),
        ("Ishdan bo'shatilganda hisob-kitob qilish", {(MK, "172")}),
        ("Ish vaqtidan tashqari ish", {(MK, "189"), (MK, "190")}),
        ("Bola parvarishlash ta'tili", {(MK, "405")}),
        ("Muddatli mehnat shartnomasi qachon tuziladi?", {(MK, "112"), (MK, "113")}),
        ("Ish haqi saqlanmaydigan ta'til", {(MK, "241")}),
        ("Ta'tilni pul bilan almashtirish mumkinmi?", {(MK, "234")}),
        ("O'rtacha ish haqi qanday hisoblanadi?", {(MK, "257")}),
        ("Mehnatga haq to'lashning eng kam miqdori", {(MK, "245")}),
        ("Ishga qabul qilishda qanday hujjatlar kerak?", {(MK, "124")}),
        ("Sinov muddati natijasi qoniqarsiz bo'lsa", {(MK, "132")}),
    ],
    "Buxgalteriya, bojxona (yangi)": [
        ("Moliyaviy hisobotning hisobot davri", {(BX, "24")}),
        ("Boshlang'ich hisob hujjatlari", {(BX, "14")}),
        ("Buxgalteriya hisobi standartlari", {(BX, "10")}),
        ("Bojxona yig'imlari", {(BK, "291")}),
        ("Bojxona to'lovlari bo'yicha imtiyozlar", {(BK, "296")}),
        ("Eksport bojxona rejimi", {(BK, "29")}),
        ("Jismoniy shaxslar olib kiradigan tovarlarga bojxona to'lovi", {(BK, "157"), (BK, "164")}),
    ],
    "So'zlashuv (yangi)": [
        ("kassa apparati bo'lmasa shtraf qancha", sk("221")),
        ("НДФЛ ставка какая?", sk("381")),
        ("Какой срок сдачи отчета по НДС?", sk("273")),
        ("Налог на имущество для физических лиц", sk("418", "422")),
        ("dekretga chiqish tartibi", {(MK, "404")}),
        ("zarplatani kechiktirsa nima bo'ladi", {(MK, "333")}),
    ],
}

# Uchinchi to'plam: ikkala to'plam bo'yicha tuzatishlardan keyin yozilgan, tuzatishda ishlatilmagan. `--uchinchi`.
UCHINCHI: dict[str, list[tuple[str, set[tuple[str, str]]]]] = {
    "Soliqlar (3)": [
        ("Asosiy vositalar amortizatsiyasi soliqda qanday hisobga olinadi?", sk("306")),
        ("Investitsiyaviy chegirma nima?", sk("308")),
        ("Umidsiz qarzlarni xarajatga o'tkazish mumkinmi?", sk("313")),
        ("Kurs farqidan soliq", sk("320")),
        ("Doimiy muassasa nima?", sk("36")),
        # savolda soha yo'q — Soliq kodeksi 37 va Bojxona kodeksi 307 ("O'zaro bog'liq shaxslar") ikkalasi ta'rif
        ("O'zaro bog'liq shaxslar kimlar?", sk("37") | {(BK, "307")}),
        ("Soliq to'lovchining shaxsiy kabineti", sk("56")),
        ("QQS bo'yicha soliq bazasi qanday aniqlanadi?", sk("247", "248")),
        ("Mol-mulk solig'ini korxona qachon to'laydi?", sk("417")),
        ("Yer solig'i bo'yicha soliq bazasi", sk("427", "435")),
        ("Aksiz solig'i qachon to'lanadi?", sk("293")),
        ("Norezidentga dividend to'laganda qancha soliq ushlanadi?", sk("353", "351", "354")),
        ("Daromad solig'i bo'yicha imtiyozlar", sk("379", "380", "378")),
    ],
    "Mehnat (3)": [
        ("Bayram kunlari ishlaganlik uchun haq to'lash", {(MK, "263")}),
        ("Tungi ish uchun qo'shimcha haq", {(MK, "264")}),
        ("Xizmat safari xarajatlari kompensatsiyasi", {(MK, "287")}),
        ("Xodimni intizomiy javobgarlikka tortish", {(MK, "300"), (MK, "301")}),
        ("O'rindoshlik asosida ishlaganda ta'til", {(MK, "439")}),
        # 234 birinchi qismi: shartnoma bekor qilinganda foydalanilmagan ta'tillar uchun pulli kompensatsiya
        ("Ishdan bo'shatilganda foydalanilmagan ta'til uchun kompensatsiya", {(MK, "234"), (MK, "235")}),
        ("Mehnat daftarchasini berish", {(MK, "171")}),
    ],
    "Buxgalteriya, bojxona (3)": [
        ("Moliyaviy hisobotni e'lon qilish", {(BX, "26")}),
        # kim yuritishi shart — 6 (subyektlar); kim amalda yuritadi — 11 (rahbar, buxgalter, tashkilot), 12
        ("Buxgalteriya hisobini kim yuritadi?", {(BX, "6"), (BX, "11"), (BX, "12")}),
        ("Ichki nazorat", {(BX, "21")}),
        ("Bojxona to'lovlarini to'lash tartibi", {(BK, "328")}),
        ("Reeksport bojxona rejimi", {(BK, "32")}),
    ],
    "So'zlashuv (3)": [
        ("NDSni qanday hisoblash kerak?", sk("265")),
        ("Срок уплаты налога на прибыль", sk("340")),
        ("Ставка земельного налога", sk("429", "437")),
        ("otpuskni pulga almashtirsa bo'ladimi", {(MK, "234")}),
        ("zarplatadan qancha nalog ushlanadi", sk("381")),
        ("aylanma soliqni qachon to'lash kerak", sk("470")),
    ],
}


async def main() -> None:
    verbose = "-v" in sys.argv
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    conn = await connect(settings.supabase_db_url.get_secret_value())
    total = [0, 0, 0, 0]
    try:
        sets = UCHINCHI if "--uchinchi" in sys.argv else YANGI if "--yangi" in sys.argv else CASES
        for soha, cases in sets.items():
            t1 = t3 = t6 = 0
            for question, expected in cases:
                r = await retrieve(conn, question, today, limit=6)
                if r.direct_article is not None:
                    got = [(r.direct_article.document_lex_id, r.direct_article.number)]
                else:
                    got = [(h.lex_id, h.modda_raqami) for h in r.hits]
                rank = next((i + 1 for i, g in enumerate(got) if g in expected), None)
                t1 += rank == 1
                t3 += bool(rank and rank <= 3)
                t6 += bool(rank)
                if verbose:
                    top = ", ".join(str(m or "-") for _, m in got[:3])
                    fixes = f" imlo {r.corrections}" if r.corrections else ""
                    print(f"   {str(rank):4} {question[:58]:58} {r.status:10} [{top}] {r.plan.terms}{fixes}")
            n = len(cases)
            total = [total[0] + n, total[1] + t1, total[2] + t3, total[3] + t6]
            print(f"{soha:24} ({n:2}): top1 {t1:2}  top3 {t3:2}  top6 {t6:2}")
    finally:
        await conn.close()
    print(f"{'JAMI':24} ({total[0]:2}): top1 {total[1]:2}  top3 {total[2]:2}  top6 {total[3]:2}")


if __name__ == "__main__":
    asyncio.run(main())
