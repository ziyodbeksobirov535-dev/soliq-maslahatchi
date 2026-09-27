"""Savolni qidiruv rejasiga aylantirish (spec 6: query understanding) — LLM'siz, deterministik.

Nima qiladi:
- matnni normallashtiradi (kichik harf, tutuq belgilarisiz — bazadagi `norm_uz()` bilan bir xil);
- aniq modda raqamini ("461-modda") va hujjat ishorasini ("Mehnat kodeksi") ajratadi;
- tarixiy sanani ("2024-yilda", "01.01.2025 holatiga") aniqlaydi;
- stop-so'zlarni olib tashlaydi, o'zbekcha qo'shimchalarni ehtiyotkor kesadi va prefiks qidiruvi
  (`soli:*`) quradi — "soliq", "solig'i", "soliqni" bir o'zakka tushadi;
- kichik sinonim lug'ati: QQS, JSHDS, aylanma solig'i, import, jarima, topshirish;
- mazmunsiz/ishorali savollarni ("Qaysi modda bu talabni belgilaydi?") `needs_clarification` qiladi.

Bu qatlam Claude'ga ishonmaydi: keyingi bosqichda fast model qo'shimcha so'rovlar taklif qilishi
mumkin, lekin asosiy reja shu yerda (spec 6: "modelga haddan tashqari ishonma").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_APOSTROPHES = str.maketrans("", "", "ʻʼ'‘’`´")
_WORD_RE = re.compile(r"[a-zа-яёўқғҳ0-9]+", re.IGNORECASE)

# Savol so'zlari, bog'lovchilar, olmoshlar va juda umumiy fe'llar (normallashtirilgan shaklda).
STOPWORDS = frozenset(
    """
    qanday qanaqa qachon qancha qaysi nima nimaga nega necha kim qayer qayerda qayerga
    kerak kerakmi bor bormi yoq emas uchun bilan va yoki ham esa lekin ammo balki agar
    bu shu u ular men biz siz mening bizning sizning ushbu osha ana mana
    qilish qiladi qilinadi qilib qilgan bolsa boladi bolgan bolishi mumkin mumkinmi
    edi ekan emish haqida boyicha deb dan ga da ni ning
    """.split()
)

# Mazmunan juda umumiy — yolg'iz kelsa savol aniq emas.
GENERIC = frozenset(
    """
    modda moddasi norma normasi talab talabni talabi qoida qoidasi tartib tartibi qonun
    qonunchilik hujjat belgilaydi belgilangan belgila holat holatda holatiga yil yilda
    vaqt vaqtda payt paytda
    """.split()
)

DEMONSTRATIVES = frozenset({"bu", "shu", "osha", "ushbu", "ana", "mana"})

# Qo'shimchalar: uzunidan qisqasiga. O'zak kamida MIN_STEM harf qoladi.
SUFFIXES = (
    "larining", "larning", "laridan", "larida", "lariga", "larini", "lardan", "larda", "larga",
    "larni", "lari", "lar",
    # "-chi" + kelishik: "-ining"/"-iga" "chi" ning "i" sini yeb qo'ymasin ("tashuvchining" → "tashuv", "tashuvch" emas)
    "chining", "chidan", "chida", "chiga", "chini",
    "sining", "sidan", "sida", "siga", "sini", "ining", "idan", "ida", "iga", "ini",
    "ning", "dagi", "dan", "tan", "da", "ga", "ka", "qa", "ni", "si",
    "anadi", "iladi", "ladi", "adi", "ydi", "ilgan", "gan", "ib",
    "chilar", "chi", "lik", "i",
)
MIN_STEM = 4
BIGRAM_WEIGHT = 0.6
# Soliq botida deyarli har savol va har bandda uchraydigan o'zaklar — ular bilan ibora tuzilmaydi
# ("soliq majburiyati" kabi umumiy iboralar noto'g'ri moddalarni yuqoriga chiqaradi).
DOMAIN_COMMON = frozenset({"soli"})

# Sinonimlar: kalit (normallashtirilgan so'z yoki o'zak) → qo'shimcha iboralar (har biri AND guruh).
SYNONYMS: dict[str, tuple[str, ...]] = {
    "qqs": ("qoshilgan qiymat soligi",),
    "jshds": ("jismoniy shaxslardan olinadigan daromad soligi",),
    "aylanma": ("aylanmadan olinadigan soliq",),
    "jarima": ("moliyaviy sanksiya", "penya"),
    "topshir": ("taqdim etish",),
    "topshirish": ("taqdim etish",),
    "ishchi": ("xodim",),
}

# Qisqartmalar qo'shimcha bilan keladi ("QQSga", "JSHDSni") — prefiks bo'yicha tan olinadi.
ABBREVIATIONS = ("jshds", "qqs")

DOCUMENT_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsoliq kodeks"), "-4674902"),
    (re.compile(r"\bmehnat kodeks"), "-6257288"),
    (re.compile(r"\bbojxona kodeks"), "-2876354"),
    (re.compile(r"\bfuqarolik kodeks"), "-111189,-180552"),
    (re.compile(r"\bbuxgalteriya hisobi togrisida"), "-2931253"),
)

_ARTICLE_RE = re.compile(r"\b(\d{1,4})\s*(?:[-.]\s*(\d{1,2}))?\s*-?\s*modda|\bmodda\s+(\d{1,4})\b")
_MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
    "iyul": 7, "avgust": 8, "sentabr": 9, "oktabr": 10, "noyabr": 11, "dekabr": 12,
}
_DATE_DMY_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_DATE_TEXT_RE = re.compile(r"\b(\d{4})\s*-?\s*yil\w*\s+(\d{1,2})\s*-?\s*(" + "|".join(_MONTHS) + r")")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\s*-?\s*yil")
_YEAR_MONTH_RE = re.compile(r"\b(19\d{2}|20\d{2})\s*-?\s*yil\w*\s+(" + "|".join(_MONTHS) + r")")


def normalize(text: str) -> str:
    return (text or "").lower().translate(_APOSTROPHES)


def _strip_suffixes(word: str) -> str:
    w = word
    changed = True
    while changed:
        changed = False
        for suf in SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= MIN_STEM:
                w = w[: -len(suf)]
                changed = True
                break
    return w


def stem(word: str) -> str:
    """Ehtiyotkor o'zak: qo'shimchalarni kesadi, o'zak MIN_STEM dan qisqarmaydi.

    Oxiridagi q/g/k tushiriladi (soliq/solig'i → soli), shunda prefiks qidiruvi ikkalasini topadi.
    """
    w = _strip_suffixes(word)
    if w.endswith(("ash", "ish")) and len(w) - 2 >= MIN_STEM + 1:
        w = w[:-2]  # saqlash → saqla, topshirish → topshiri
    if len(w) >= MIN_STEM + 1 and w[-1] in "qgk":
        w = w[:-1]
    return w


# Fe'l oilasi: ot (-uv/-ov, "-uvchi"/"-ovchi" ham shu yerga tushadi) → harakat nomi (-ish/-ash).
# Lex.uz matnida aralash: "yuk tashish" (18) va "yuk tashuvchi" (7), "to'lov" va "to'lash".
# Faqat ot → fe'l yo'nalishi: teskarisi "foydalanish" → "foydalanuvchi", "topshirish" → "topshiruvchi"
# kabi boshqa ma'noli so'zlarni qo'shib, spec savollarida natijani yomonlashtirdi (Supabase'da tekshirilgan).
# Umumiy qisqa o'zak ("tash:*") ishlatilmaydi — u "tashqi", "tashkil", "tashabbus" ni ham topadi.
_NOUN_TO_VERB = (("uv", "ish"), ("ov", "ash"))
MIN_VERB_ROOT = 3


def stem_variants(word: str) -> list[str]:
    """Otning fe'l oilasidagi juft o'zagi: "tashuvchi" → ["tashi"], "to'lov" → ["tolash"].

    Matnda bo'lmagan juft shakl zararsiz — qidiruvda asosiy o'zak bilan OR guruhida turadi.
    """
    w = _strip_suffixes(word)
    for noun, verb in _NOUN_TO_VERB:
        if w.endswith(noun) and len(w) - len(noun) >= MIN_VERB_ROOT:
            alt = stem(w[: -len(noun)] + verb)
            return [alt] if alt != stem(word) else []
    return []


@dataclass
class QueryPlan:
    question: str
    normalized: str
    terms: list[str] = field(default_factory=list)  # o'zaklar (stop-so'zlarsiz)
    bigrams: list[tuple[str, str]] = field(default_factory=list)  # yonma-yon so'zlar: "mehnat shartnoma"
    phrases: list[list[str]] = field(default_factory=list)  # sinonim iboralari (o'zaklar)
    variants: dict[str, list[str]] = field(default_factory=dict)  # o'zak → fe'l oilasidagi juft o'zaklar
    article_number: str | None = None
    lex_ids: list[str] | None = None
    historical_date: date | None = None
    historical_precision: str | None = None  # "day" | "month" | "year"
    needs_clarification: bool = False
    clarification_reason: str | None = None

    @property
    def ts_terms(self) -> list[str]:
        """search_articles() uchun bo'laklar: har bir o'zak prefiks, sinonim iborasi AND-guruh."""
        parts = [self._term(t) for t in self.terms]
        parts += [self._bigram(a, b) for a, b in self.bigrams]
        parts += ["(" + " & ".join(f"{t}:*" for t in phrase) + ")" for phrase in self.phrases]
        return list(dict.fromkeys(parts))

    def _term(self, t: str) -> str:
        forms = [t, *self.variants.get(t, ())]
        return f"{t}:*" if len(forms) == 1 else "(" + " | ".join(f"{f}:*" for f in forms) + ")"

    def _bigram(self, a: str, b: str) -> str:
        return f"({self._term(a)} <-> {self._term(b)})"

    @property
    def ts_weights(self) -> list[float]:
        """ts_terms bilan bir xil tartibda: iboralar (bigram) pastroq vazn oladi — umumiy iboralar
        ("soliq majburiyati") kam uchragani uchun IDF'i baland, lekin mazmunan asosiy so'zdan kuchli emas."""
        weights = {self._term(t): 1.0 for t in self.terms}
        weights.update({self._bigram(a, b): BIGRAM_WEIGHT for a, b in self.bigrams})
        weights.update({"(" + " & ".join(f"{t}:*" for t in p) + ")": 1.0 for p in self.phrases})
        return [weights.get(part, 1.0) for part in self.ts_terms]

    @property
    def tsquery(self) -> str | None:
        """Bitta to_tsquery ko'rinishi (log va tekshiruv uchun)."""
        return " | ".join(self.ts_terms) or None

    @property
    def trigram_text(self) -> str:
        return " ".join(self.terms)

    @property
    def is_historical(self) -> bool:
        return self.historical_date is not None


def _historical(norm: str, today: date) -> tuple[date | None, str | None]:
    m = _DATE_DMY_RE.search(norm)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))), "day"
        except ValueError:
            pass
    m = _DATE_TEXT_RE.search(norm)
    if m:
        try:
            return date(int(m.group(1)), _MONTHS[m.group(3)], int(m.group(2))), "day"
        except ValueError:
            pass
    m = _YEAR_MONTH_RE.search(norm)
    if m:
        return date(int(m.group(1)), _MONTHS[m.group(2)], 1), "month"
    m = _YEAR_RE.search(norm)
    if m:
        year = int(m.group(1))
        if year < today.year:
            return date(year, 12, 31), "year"  # yil oxiridagi holat; javobda aniqlashtiriladi
        return None, None
    return None, None


def analyze(question: str, today: date) -> QueryPlan:
    norm = normalize(question)
    plan = QueryPlan(question=question, normalized=norm)

    m = _ARTICLE_RE.search(norm)
    if m:
        main, sub, alt = m.groups()
        plan.article_number = f"{int(main)}-{int(sub)}" if sub else str(int(main or alt))

    for pattern, ids in DOCUMENT_HINTS:
        if pattern.search(norm):
            plan.lex_ids = (plan.lex_ids or []) + ids.split(",")

    hist, precision = _historical(norm, today)
    if hist is not None and hist < today:
        plan.historical_date, plan.historical_precision = hist, precision

    words = [w for w in _WORD_RE.findall(norm) if not w.isdigit()]
    content = [w for w in words if w not in STOPWORDS and len(w) >= 2]
    meaningful = [w for w in content if w not in GENERIC and not re.fullmatch(r"(yil|modda)\w*", w)]
    # Hujjat nomidagi so'zlar mazmun emas, faqat filtr.
    if plan.lex_ids:
        meaningful = [w for w in meaningful if w not in {"kodeksi", "kodeks", "kodeksning", "soliq", "mehnat",
                                                         "bojxona", "fuqarolik", "buxgalteriya", "hisobi",
                                                         "togrisida"}] or meaningful

    meaningful = [w for w in meaningful if w not in _MONTHS]
    seen: set[str] = set()
    for w in meaningful:
        abbr = next((a for a in ABBREVIATIONS if w.startswith(a) and len(w) - len(a) <= 4), None)
        s = abbr or stem(w)
        if s not in seen:
            variants = [] if abbr else stem_variants(w)
            seen.add(s)
            seen.update(variants)  # "tashish ... tashuvchi" — bitta oila, bitta so'z
            plan.terms.append(s)
            if variants:
                plan.variants[s] = variants
        for key in (w, s):
            for phrase in SYNONYMS.get(key, ()):
                stems = [stem(p) for p in phrase.split()]
                if stems not in plan.phrases:
                    plan.phrases.append(stems)

    # Iboralar: asl matnda yonma-yon turgan ikki mazmunli so'z (orada stop-so'z bo'lmasa).
    kept = set(meaningful)
    for a, b in zip(words, words[1:]):
        if a in kept and b in kept:
            def key(w: str) -> str:
                return next((x for x in ABBREVIATIONS if w.startswith(x) and len(w) - len(x) <= 4), None) or stem(w)

            pair = (key(a), key(b))
            if pair[0] != pair[1] and pair not in plan.bigrams and not (set(pair) & DOMAIN_COMMON):
                plan.bigrams.append(pair)

    has_demonstrative = any(w in DEMONSTRATIVES for w in words)
    if plan.article_number is None:
        if not plan.terms:
            plan.needs_clarification = True
            plan.clarification_reason = "savolda qidirish uchun mazmunli so'z yo'q"
        elif has_demonstrative and len(plan.terms) <= 1:
            plan.needs_clarification = True
            plan.clarification_reason = "savol oldingi kontekstga ishora qiladi ('bu', 'shu'), mavzu aniq emas"
    return plan
