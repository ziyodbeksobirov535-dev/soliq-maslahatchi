"""Lex.uz fetch client, parser va havola quruvchi.

Bu modul mustaqil (app/ ga bog'liq emas): sozlamalar konstruktor orqali beriladi.

Asosiy funksiyalar:
- `fetch` — ehtiyotkor yuklash (quyida).
- `parse_doc` — hujjat sahifasini metadata + elementlarga ajratadi.
- `parse_card` / `resolve_status` — "Asosiy rekvizitlar" kartochkasi va huquqiy holat.
- `load` — hujjatni (kerak bo'lsa tarixiy versiyasini) yuklab, parse qiladi.
- `doc_url`, `elem_link`, `card_url`, `pick_version` — havolalar va versiya tanlash.

Parser real Lex.uz HTML'i asosida yozilgan (2026-09-26 holati, namunalar:
`tests/fixtures/lexuz/`). Sahifa tuzilmasi:
- `#divCont` ichida ketma-ket `div.lx_elem.<TUR>` elementlar; element ID va matn
  ichki `div[id]` da (masalan `<div id="-4675087">...`).
- Element turlari: ACT_TITLE, TEXT_HEADER_DEFAULT (qism/bo'lim/bob), CLAUSE_DEFAULT
  (modda sarlavhasi), ACT_TEXT (band/qism matni), FOOTNOTE, NEW_EDITION, ACT_FORM, BY_DEFAULT.
- Elementdan keyin keladigan `div.lx_no_select` bloklar: CHANGES_ORIGINS (o'zgartirish
  manbasi), COMMENT (oldingi/keyingi tahrir havolasi yoki "LexUZ sharhi"),
  INDEXES_ON_REF (tasniflagich indeksi — saqlanmaydi).
- Tarixiy versiya: `?ONDATE=` faqat sahifadagi versiyalar ro'yxatidagi sanalar bilan
  ishlaydi (masalan `27.07.2026` yoki `12.12.2026 01`); ixtiyoriy sana 404 qaytaradi.
- Kartochka (`/actinfo/card1/<id>`) kelajakda kuchga kiradigan hujjatni ham
  "Действующий" deb ko'rsatadi — shuning uchun holat kuchga kirish sanasi bilan birga baholanadi.

Lex.uz'ni ortiqcha yuklamaslik uchun (spec 3-bo'lim): timeout, retry,
exponential backoff, so'rovlar orasida kechikish, disk cache, ketma-ket
(parallel emas) so'rovlar.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

log = logging.getLogger(__name__)

BASE_URL = "https://lex.uz"
DEFAULT_USER_AGENT = "soliq-maslahatchi/0.1 (+https://github.com/ziyodbeksobirov535-dev/soliq-maslahatchi)"

_ID_RE = re.compile(r"^-?\d+$")
# Izoh bloklari (COMMENT) anchor ID'si: yangi hujjatlarda "edi-5464766", eskilarida "edi1575785".
_ELEMENT_ID_RE = re.compile(r"^(?:-?\d+|edi-?\d+)$")
_EDI_RE = re.compile(r"^edi(-?)(\d+)$")
_VERSION_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}(?: \d{2})?$")
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class LexUzError(Exception):
    """Lex.uz bilan ishlashdagi umumiy xato."""


class LexUzHTTPError(LexUzError):
    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"Lex.uz HTTP {status_code}: {url}")
        self.url = url
        self.status_code = status_code


class LexUzEmptyResponse(LexUzError):
    def __init__(self, url: str) -> None:
        super().__init__(f"Lex.uz bo'sh javob qaytardi: {url}")
        self.url = url


def _check_id(value: str, what: str, pattern: re.Pattern[str] = _ID_RE) -> str:
    value = str(value).strip()
    if not pattern.match(value):
        raise ValueError(f"Noto'g'ri Lex.uz {what}: {value!r}")
    return value


def doc_url(doc_id: str, version: date | str | None = None) -> str:
    """Hujjat URL'i. `version` — sahifadagi versiyalar ro'yxatidan sana (`?ONDATE=`).

    Diqqat: Lex.uz faqat mavjud versiya sanasini qabul qiladi; ixtiyoriy sana uchun
    avval `pick_version` bilan mos versiyani tanlang.
    """
    url = f"{BASE_URL}/docs/{_check_id(doc_id, 'hujjat ID')}"
    if version is not None:
        token = f"{version:%d.%m.%Y}" if isinstance(version, date) else str(version).strip()
        if not _VERSION_RE.match(token):
            raise ValueError(f"Noto'g'ri versiya sanasi: {version!r}")
        url += f"?ONDATE={token}"
    return url


def elem_link(doc_id: str, element_id: str) -> str:
    """Element uchun canonical havola, masalan https://lex.uz/docs/-4674902#-7966265."""
    return f"{doc_url(doc_id)}#{_check_id(element_id, 'element ID', _ELEMENT_ID_RE)}"


def card_url(doc_id: str) -> str:
    """Hujjatning "Asosiy rekvizitlar" kartochkasi (holat, sanalar, raqam)."""
    return f"{BASE_URL}/actinfo/card1/{_check_id(doc_id, 'hujjat ID')}"


class LexUzClient:
    """Lex.uz sahifalarini ehtiyotkorlik bilan yuklovchi sinxron client.

    Bitta client ichida so'rovlar lock bilan ketma-ket bajariladi va har biri
    orasida kamida `delay_seconds` kutiladi.
    """

    def __init__(
        self,
        *,
        delay_seconds: float = 1.5,
        max_retries: int = 5,
        timeout_seconds: float = 30.0,
        backoff_base_seconds: float = 2.0,
        backoff_max_seconds: float = 60.0,
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: float = 24 * 3600,
        user_agent: str = DEFAULT_USER_AGENT,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if delay_seconds < 0 or max_retries < 0 or timeout_seconds <= 0:
            raise ValueError("delay/max_retries manfiy, timeout musbat bo'lishi kerak")
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl_seconds = cache_ttl_seconds
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._last_request_at: float | None = None
        self._headers = {"User-Agent": user_agent}
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> LexUzClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- cache ---------------------------------------------------------

    def _cache_path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html")

    def _cache_get(self, url: str) -> str | None:
        path = self._cache_path(url)
        if path is None or not path.is_file():
            return None
        if self._wall_clock() - path.stat().st_mtime > self.cache_ttl_seconds:
            return None
        return path.read_text(encoding="utf-8")

    def _cache_put(self, url: str, text: str) -> None:
        path = self._cache_path(url)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    # --- network -------------------------------------------------------

    def _wait_for_slot(self) -> None:
        if self._last_request_at is not None:
            remaining = self.delay_seconds - (self._clock() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), self.backoff_max_seconds)
        return min(self.backoff_base_seconds * (2**attempt), self.backoff_max_seconds)

    def fetch(self, url: str, *, use_cache: bool = True, data: dict[str, str] | None = None) -> str:
        """URL matnini qaytaradi. Xatoda LexUzHTTPError / LexUzEmptyResponse / LexUzError.

        `data` berilsa — POST (qidiruv natijalarining keyingi sahifasi, ASP.NET postback); POST keshlanmaydi.
        """
        if urlsplit(url).hostname not in {"lex.uz", "www.lex.uz"}:
            raise ValueError(f"Faqat lex.uz manzillari qabul qilinadi: {url!r}")
        if data is not None:
            use_cache = False

        if use_cache:
            cached = self._cache_get(url)
            if cached is not None:
                log.debug("lexuz cache hit url=%s", url)
                return cached

        with self._lock:
            attempt = 0
            while True:
                self._wait_for_slot()
                started = self._clock()
                response: httpx.Response | None = None
                # Lex.uz javobi sessiya cookie'siga qarab o'zgaradi (masalan kartochka tili);
                # har so'rov mustaqil bo'lishi uchun cookie saqlanmaydi.
                self._http.cookies.clear()
                try:
                    if data is None:
                        response = self._http.get(url, headers=self._headers)
                    else:
                        response = self._http.post(url, headers=self._headers, data=data)
                except httpx.TransportError as exc:
                    error: LexUzError = LexUzError(f"Lex.uz tarmoq xatosi ({type(exc).__name__}): {url}")
                    retryable = True
                else:
                    if response.status_code == 200:
                        text = response.text
                        if not text.strip():
                            log.warning("lexuz empty response url=%s", url)
                            raise LexUzEmptyResponse(url)
                        log.info(
                            "lexuz fetched url=%s bytes=%d ms=%d attempt=%d",
                            url, len(response.content), (self._clock() - started) * 1000, attempt,
                        )
                        if use_cache:
                            self._cache_put(url, text)
                        return text
                    error = LexUzHTTPError(url, response.status_code)
                    retryable = response.status_code in _RETRYABLE_STATUS

                if not retryable or attempt >= self.max_retries:
                    log.error("lexuz fetch failed url=%s error=%s attempts=%d", url, error, attempt + 1)
                    raise error
                wait = self._backoff(attempt, response)
                log.warning("lexuz retry url=%s error=%s wait=%.1fs attempt=%d", url, error, wait, attempt + 1)
                self._sleep(wait)
                attempt += 1


def fetch(url: str, *, client: LexUzClient | None = None, use_cache: bool = True) -> str:
    """Qulaylik uchun: bitta URL'ni yuklash. Ko'p so'rov uchun bitta `LexUzClient` ishlating."""
    if client is not None:
        return client.fetch(url, use_cache=use_cache)
    with LexUzClient() as tmp:
        return tmp.fetch(url, use_cache=use_cache)




# --- parser ------------------------------------------------------------------

STATUS_AMALDA = "amalda"
STATUS_KUCHGA_KIRMAGAN = "kuchga_kirmagan"
STATUS_KUCHINI_YOQOTGAN = "kuchini_yoqotgan"
STATUS_NOMALUM = "noma'lum"

# Kartochkadagi "Ҳужжат ҳолати" qiymatlari. Lex.uz sessiya holatiga qarab qiymatni
# ruscha ("Действующий") yoki o'zbekcha ("Amalda") qaytaradi — ikkalasi real namunada kuzatilgan.
# Ro'yxatda yo'q qiymat → noma'lum (taxmin qilinmaydi).
_CARD_STATUS = {
    "действующий": STATUS_AMALDA,
    "amalda": STATUS_AMALDA,
    "утративший силу": STATUS_KUCHINI_YOQOTGAN,
}

_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_TITLE_RE = re.compile(r"^(?:(?P<number>\S+)-сон\s+)?(?P<date>\d{2}\.\d{2}\.\d{4})\.\s*(?P<name>.+)$")
# Modda sarlavhasi (faqat CLAUSE_DEFAULT uchun): "461-modda.", "121¹-modda.", "461-модда.",
# "Статья 461.", shuningdek eski hujjatlarda so'zsiz "159¹. Ставки ..."
_ARTICLE_RE = re.compile(
    r"^\s*(?:(?P<num>\d+)(?P<sup>[⁰¹²³⁴⁵⁶⁷⁸⁹]*)\s*-\s*(?:modda|модда)\b"
    r"|Статья\s+(?P<ru>\d+)(?P<rusup>[⁰¹²³⁴⁵⁶⁷⁸⁹]*)"
    r"|(?P<bare>\d+)(?P<baresup>[⁰¹²³⁴⁵⁶⁷⁸⁹]*)\.\s)",
    re.IGNORECASE,
)
# Sarlavha darajalari: qism > bo'lim > bob; boshqa sarlavhalar eng quyi daraja.
_HEADER_LEVELS = (
    (0, re.compile(r"\b(QISM|ҚИСМ|ЧАСТЬ)\b", re.IGNORECASE)),
    (1, re.compile(r"\b(BOʻLIM|BO'LIM|BO‘LIM|БЎЛИМ|РАЗДЕЛ)\b", re.IGNORECASE)),
    (2, re.compile(r"(-bob\b|-боб\b|^Глава\s)", re.IGNORECASE)),
)
_OTHER_HEADER_LEVEL = 3

KIND_TITLE = "title"
KIND_HEADER = "header"
KIND_ARTICLE = "article"
KIND_TEXT = "text"
KIND_FOOTNOTE = "footnote"
KIND_TABLE = "table"
KIND_AMENDMENT = "amendment"  # CHANGES_ORIGINS
KIND_EDITION_NOTE = "edition_note"  # COMMENT: oldingi/keyingi tahrir
KIND_LEXUZ_COMMENT = "lexuz_comment"  # COMMENT: "LexUZ sharhi"
KIND_OTHER = "other"

_KIND_BY_CLASS = {
    "ACT_TITLE": KIND_TITLE,
    "TEXT_HEADER_DEFAULT": KIND_HEADER,
    "CLAUSE_DEFAULT": KIND_ARTICLE,
    "ACT_TEXT": KIND_TEXT,
    "FOOTNOTE": KIND_FOOTNOTE,
}


@dataclass
class Element:
    element_id: str
    doc_id: str
    order_no: int
    type: str  # Lex.uz CSS klassi, masalan CLAUSE_DEFAULT, COMMENT
    kind: str  # normallashtirilgan tur (KIND_*)
    text: str
    link: str
    parent_element_id: str | None = None
    bob: str | None = None
    modda: str | None = None
    modda_raqami: str | None = None  # "461", "121-1" (121¹)
    element_path: str = ""
    amendment_note: str | None = None
    refs: list[str] = field(default_factory=list)  # matndagi havolalar (absolyut)
    future_version: str | None = None  # "12.12.2026 01" — kelajakdagi tahrir mavjud bo'lsa

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass
class Document:
    doc_id: str
    url: str
    title: str
    name: str
    number: str | None
    adoption_date: date | None
    effective_date: date | None
    header_label: str | None
    version: str | None  # ochilgan sahifa versiyasi, masalan "06.08.2026"
    versions: list[str]  # sahifadagi barcha versiyalar (yangi → eski)
    elements: list[Element]

    @property
    def text_available(self) -> bool:
        return any(e.kind in (KIND_ARTICLE, KIND_TEXT) for e in self.elements)

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        for e in self.elements:
            h.update(f"{e.element_id}\x1f{e.text}\x1e".encode("utf-8"))
        return h.hexdigest()

    def articles(self) -> list[Element]:
        return [e for e in self.elements if e.kind == KIND_ARTICLE]

    def article(self, number: str) -> list[Element]:
        """Modda sarlavhasi va unga tegishli barcha elementlar (tartib bo'yicha)."""
        number = number.strip()
        return [e for e in self.elements if e.modda_raqami == number]


@dataclass
class ActCard:
    doc_id: str
    name: str | None
    doc_type: str | None
    form: str | None
    adoption_date: date | None
    number: str | None
    status_raw: str | None
    effective_date: date | None
    repeal_date: date | None
    official_source_number: str | None


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def version_date(token: str) -> date | None:
    """Versiya tokenidan sana: "12.12.2026 01" → 2026-12-12."""
    return _parse_date(token)


_version_date = version_date


def _clean(text: str) -> str:
    lines = (re.sub(r"[ \t ​]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


_BLOCK_TAGS = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})


def _render(node: Tag, out: list[str]) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            if child.parent is not None and child.parent.name == "sup":
                out.append(str(child).strip().translate(_SUPERSCRIPT))
            else:
                out.append(str(child))
        elif not isinstance(child, Tag):
            continue
        elif child.name == "br":
            out.append("\n")
        elif child.name == "table":
            out.append("\n" + _render_table(child) + "\n")
        elif child.name in _BLOCK_TAGS:
            out.append("\n")
            _render(child, out)
            out.append("\n")
        else:
            _render(child, out)


def _render_table(table: Tag) -> str:
    """Jadvalni qatorma-qator "katak | katak" ko'rinishida (stavka jadvallari uchun muhim)."""
    lines = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = [
            _node_text(td).replace("\n", " ")
            for td in tr.find_all(["td", "th"])
            if td.find_parent("tr") is tr
        ]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _node_text(node: Tag) -> str:
    """Element matni: <br> → yangi qator, <sup>1</sup> → ¹, jadval → "a | b" qatorlari."""
    out: list[str] = []
    _render(node, out)
    return _clean("".join(out))


def _article_number(heading: str) -> str | None:
    m = _ARTICLE_RE.match(heading)
    if not m:
        return None
    for num_group, sup_group in (("num", "sup"), ("ru", "rusup"), ("bare", "baresup")):
        if m.group(num_group):
            num, sup = m.group(num_group), m.group(sup_group)
            break
    if sup:
        sup_digits = sup.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        return f"{num}-{sup_digits}"
    return num


def _header_level(text: str) -> int:
    for level, pattern in _HEADER_LEVELS:
        if pattern.search(text):
            return level
    return _OTHER_HEADER_LEVEL


def _refs(node: Tag) -> list[str]:
    return [urljoin(BASE_URL + "/", a["href"]) for a in node.find_all("a", href=True)]


def _version_from_href(href: str) -> str | None:
    values = parse_qs(urlsplit(href).query).get("ONDATE")
    if not values:
        return None
    token = values[0].strip()
    # Havolalarda vaqt qismi ham bo'ladi ("01.01.2020 00") — "00" asosiy versiya.
    if token.endswith(" 00"):
        token = token[:-3]
    return token if _VERSION_RE.match(token) else None


def _parse_versions(soup: BeautifulSoup) -> tuple[str | None, list[str]]:
    selected = soup.select_one(".lx_date_selected")
    current = _clean(selected.get_text(" ")) if selected else None
    versions: list[str] = []
    menu = soup.select_one(".lx_date_ddm")
    items = menu.select(".lx_date_link, .lx_date_selected") if menu else []
    for item in items:
        if "lx_date_selected" in item.get("class", []):
            token = current
        else:
            m = re.search(r"ONDATE=([^'\"]+)", item.get("onclick", ""))
            token = m.group(1).strip() if m else None
        if token and _VERSION_RE.match(token) and token not in versions:
            versions.append(token)
    return current, versions


def _parse_header(soup: BeautifulSoup) -> tuple[str | None, date | None]:
    label_el = soup.select_one(".docHeader__item-label")
    label = _clean(label_el.get_text(" ")) if label_el else None
    effective = None
    for item in soup.select(".docHeader__item"):
        item_label = item.select_one(".docHeader__item-label")
        value = item.select_one(".docHeader__item-value")
        if item_label and value and "Кучга кириш" in item_label.get_text():
            effective = _parse_date(value.get_text(" "))
            break
    return label, effective


def parse_doc(html: str, doc_id: str) -> Document:
    """Lex.uz hujjat sahifasini (`/docs/<id>`) metadata va elementlarga ajratadi.

    Matni hali e'lon qilinmagan hujjatlarda `#divCont` bo'lmaydi — bunda elementlar
    bo'sh va `text_available` False bo'ladi. Sahifa umuman Lex.uz hujjati bo'lmasa
    (sarlavha ham, kontent ham yo'q) LexUzError ko'tariladi.
    """
    doc_id = _check_id(doc_id, "hujjat ID")
    if not html or not html.strip():
        raise LexUzError(f"Bo'sh HTML: {doc_id}")
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.find("title")
    title = _clean(title_el.get_text(" ")) if title_el else ""
    container = soup.select_one("#divCont")
    header_label, effective_date = _parse_header(soup)
    if not title and container is None and header_label is None:
        raise LexUzError(f"Lex.uz hujjat sahifasi emas: {doc_id}")

    m = _TITLE_RE.match(title)
    name = m.group("name").strip() if m else title
    number = m.group("number") if m else None
    adoption_date = _parse_date(m.group("date")) if m else None
    version, versions = _parse_versions(soup)

    elements = _parse_elements(container, doc_id) if container is not None else []
    return Document(
        doc_id=doc_id,
        url=doc_url(doc_id),
        title=title,
        name=name,
        number=number,
        adoption_date=adoption_date,
        effective_date=effective_date,
        header_label=header_label,
        version=version,
        versions=versions,
        elements=elements,
    )


def _parse_elements(container: Tag, doc_id: str) -> list[Element]:
    """Ikki bosqich: (1) asosiy elementlar va ierarxiya, (2) izohlarni egasiga biriktirish."""
    mains: list[Element] = []
    # Hujjat tartibidagi ketma-ketlik: ("main", indeks) yoki ("note", blok, oldingi main indeksi)
    sequence: list[tuple] = []
    headers: list[tuple[int, Element]] = []  # (daraja, sarlavha) steki
    article: Element | None = None

    def path(extra: Element | None = None) -> str:
        names = [h.text for _, h in headers]
        if extra is not None:
            names.append(extra.text)
        return " > ".join(names)

    def current_bob() -> str | None:
        for level, h in reversed(headers):
            if level == 2:
                return h.text
        return None

    for block in container.find_all("div", recursive=False):
        classes = block.get("class", [])
        inner = block.find("div", id=True, recursive=False)
        if inner is None:
            continue
        if "lx_elem" not in classes:
            if "CHANGES_ORIGINS" in classes or "COMMENT" in classes:
                sequence.append(("note", block, inner, len(mains) - 1))
            continue  # INDEXES_ON_REF — tasniflagich, saqlanmaydi

        el_type = next((c for c in classes if c != "lx_elem"), "UNKNOWN")
        text = _node_text(inner)
        if not text:  # BY_DEFAULT, ACT_FORM kabi bo'sh ajratkichlar
            continue
        kind = KIND_TABLE if inner.find("table") is not None else _KIND_BY_CLASS.get(el_type, KIND_OTHER)
        if kind in (KIND_HEADER, KIND_ARTICLE, KIND_TITLE):
            text = text.replace("\n", " ")  # "I BOʻLIM.<br/>UMUMIY QOIDALAR" → bitta qator
        el = Element(
            element_id=inner["id"],
            doc_id=doc_id,
            order_no=0,
            type=el_type,
            kind=kind,
            text=text,
            link=elem_link(doc_id, inner["id"]),
            refs=_refs(inner),
        )
        if kind == KIND_HEADER:
            level = _header_level(text)
            while headers and headers[-1][0] >= level:
                headers.pop()
            el.parent_element_id = headers[-1][1].element_id if headers else None
            headers.append((level, el))
            el.bob = current_bob()
            el.element_path = path()
            article = None
        elif kind == KIND_ARTICLE:
            el.parent_element_id = headers[-1][1].element_id if headers else None
            el.bob = current_bob()
            el.modda = text
            el.modda_raqami = _article_number(text)
            el.element_path = path(el)
            article = el
        else:
            owner = article or (headers[-1][1] if headers else None)
            el.parent_element_id = owner.element_id if owner else None
            el.bob = current_bob()
            if article is not None:
                el.modda = article.modda
                el.modda_raqami = article.modda_raqami
            el.element_path = path(article)
        sequence.append(("main", len(mains)))
        mains.append(el)

    elements: list[Element] = []
    for item in sequence:
        if item[0] == "main":
            el = mains[item[1]]
        else:
            _, block, inner, prev_idx = item
            el = _make_note(block, inner, doc_id, mains, prev_idx)
            if el is None:
                continue
        el.order_no = len(elements) + 1
        elements.append(el)
    return elements


def _note_owner(note_id: str, is_next_version: bool, mains: list[Element], prev_idx: int) -> Element | None:
    """Izoh egasini aniqlaydi (Soliq kodeksidagi 2 264 ta izoh bo'yicha tekshirilgan):
    - CHANGES_ORIGINS va "LexUZ sharhi" — o'zgargan fragment oxirida, oldingi elementga tegishli;
    - "Oldingi tahrirga qarang" (edi-N) — o'zgargan fragment boshida, keyingi elementga tegishli;
    - "... kuchga kiradigan o'zgarishlarga qarang" (lx_next_ver) — oldingi elementga tegishli.
    `edi-N` ID'si `-N` (yoki `N`) elementga to'g'ridan-to'g'ri mos kelsa, o'sha element tanlanadi.
    """
    prev_el = mains[prev_idx] if prev_idx >= 0 else None
    next_el = mains[prev_idx + 1] if prev_idx + 1 < len(mains) else None
    m = _EDI_RE.match(note_id)
    if m is None:
        return prev_el
    targets = {m.group(2), "-" + m.group(2)}
    for candidate in (next_el, prev_el):
        if candidate is not None and candidate.element_id in targets:
            return candidate
    if is_next_version:
        return prev_el or next_el
    return next_el or prev_el


def _make_note(block: Tag, inner: Tag, doc_id: str, mains: list[Element], prev_idx: int) -> Element | None:
    classes = block.get("class", [])
    if "CHANGES_ORIGINS" in classes:
        kind, el_type = KIND_AMENDMENT, "CHANGES_ORIGINS"
    else:
        is_lexuz = block.select_one(".COMMENTLEXUZ") is not None
        kind, el_type = (KIND_LEXUZ_COMMENT if is_lexuz else KIND_EDITION_NOTE), "COMMENT"
    text = _node_text(inner)
    next_ver = inner.select_one("a.lx_next_ver")
    owner = _note_owner(inner["id"], next_ver is not None, mains, prev_idx)
    if not text or owner is None:
        return None
    note = Element(
        element_id=inner["id"],
        doc_id=doc_id,
        order_no=0,
        type=el_type,
        kind=kind,
        text=text,
        link=elem_link(doc_id, inner["id"]),
        parent_element_id=owner.element_id,
        bob=owner.bob,
        modda=owner.modda,
        modda_raqami=owner.modda_raqami,
        element_path=owner.element_path,
        refs=_refs(inner),
    )
    if next_ver is not None:
        note.future_version = _version_from_href(next_ver["href"])
        owner.future_version = note.future_version
    if kind in (KIND_AMENDMENT, KIND_EDITION_NOTE):
        owner.amendment_note = f"{owner.amendment_note}\n{text}" if owner.amendment_note else text
    return note


def parse_card(html: str, doc_id: str) -> ActCard:
    """`/actinfo/card1/<id>` kartochkasini o'qiydi."""
    doc_id = _check_id(doc_id, "hujjat ID")
    if not html or not html.strip():
        raise LexUzError(f"Bo'sh kartochka: {doc_id}")
    soup = BeautifulSoup(html, "lxml")
    fields: dict[str, str] = {}
    for label in soup.select("td.lbl"):
        value = label.find_next_sibling("td")
        key = _clean(label.get_text(" "))
        if key and value is not None and key not in fields:
            fields[key] = _clean(value.get_text(" "))
    if not fields:
        raise LexUzError(f"Lex.uz kartochkasi emas: {doc_id}")

    adoption_date = number = None
    organ_row = soup.select_one("table.otmTab tr:has(td.otmVal)")
    if organ_row is not None:
        # Ustunlar: t/r, organ, lavozim, imzolagan shaxs, qabul sanasi, raqam, joy
        cells = [_clean(td.get_text(" ")) for td in organ_row.select("td.otmVal")]
        for i, cell in enumerate(cells):
            if _DATE_RE.fullmatch(cell):
                adoption_date = _parse_date(cell)
                number = cells[i + 1] if i + 1 < len(cells) and cells[i + 1] else None
                break

    def get(prefix: str) -> str | None:
        for key, value in fields.items():
            if key.startswith(prefix):
                return value or None
        return None

    name_el = None
    for label in soup.select("td.lbl"):
        if _clean(label.get_text(" ")) == "Ҳужжат номи":
            name_el = label.find_next_sibling("td")
            break
    return ActCard(
        doc_id=doc_id,
        name=_clean(name_el.get_text(" ")) if name_el else get("Ҳужжат номи"),
        doc_type=get("Ҳужжат тури"),
        form=get("Ҳужжат шакли"),
        adoption_date=adoption_date,
        number=number,
        status_raw=get("Ҳужжат ҳолати"),
        effective_date=_parse_date(get("Кучга кириш санаси")),
        repeal_date=_parse_date(get("Кучини йўқотган санаси")),
        official_source_number=get("Расмий манба нашри"),
    )


def resolve_status(card: ActCard, today: date) -> str:
    """Hujjatning huquqiy holati.

    Qoidalar (spec 5, 16-bo'lim):
    - kuchini yo'qotgan sana o'tgan yoki kartochka "Утративший силу" → kuchini_yoqotgan;
    - kuchga kirish sanasi kelajakda → kuchga_kirmagan (kartochka bunday hujjatni ham
      "Действующий" deb ko'rsatadi);
    - kartochka "Действующий" va kuchga kirish sanasi o'tgan → amalda;
    - qolgan barcha holatda → noma'lum (faqat sanaga qarab "amalda" deyilmaydi).
    """
    official = _CARD_STATUS.get((card.status_raw or "").strip().lower())
    if official == STATUS_KUCHINI_YOQOTGAN or (card.repeal_date and card.repeal_date <= today):
        return STATUS_KUCHINI_YOQOTGAN
    if card.effective_date and card.effective_date > today:
        return STATUS_KUCHGA_KIRMAGAN
    if official == STATUS_AMALDA and card.effective_date and card.effective_date <= today:
        return STATUS_AMALDA
    return STATUS_NOMALUM


def pick_version(versions: list[str], on_date: date) -> str | None:
    """`on_date` holatidagi amaldagi versiya: sanasi `on_date` dan kech bo'lmagan eng so'nggisi."""
    best: tuple[date, str] | None = None
    for token in versions:
        d = _version_date(token)
        if d is None or d > on_date:
            continue
        if best is None or (d, token) > best:
            best = (d, token)
    return best[1] if best else None


def load(doc_id: str, on_date: date | None = None, *, client: LexUzClient) -> Document:
    """Hujjatni yuklab parse qiladi. `on_date` berilsa — o'sha sana holatidagi versiya.

    Tarixiy versiya uchun avval joriy sahifadan versiyalar ro'yxati olinadi, so'ng
    `pick_version` bilan mos versiya ochiladi. Mos versiya bo'lmasa LexUzError.
    """
    current = parse_doc(client.fetch(doc_url(doc_id)), doc_id)
    if on_date is None:
        return current
    version = pick_version(current.versions, on_date)
    if version is None:
        raise LexUzError(f"{doc_id}: {on_date:%d.%m.%Y} holatiga versiya topilmadi")
    if version == current.version:
        return current
    return parse_doc(client.fetch(doc_url(doc_id, version)), doc_id)


def load_card(doc_id: str, *, client: LexUzClient) -> ActCard:
    return parse_card(client.fetch(card_url(doc_id)), doc_id)


def today_tashkent() -> date:
    """Holatni baholash uchun Asia/Tashkent bo'yicha bugungi sana."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Tashkent")).date()


# --- RSS -------------------------------------------------------------------------

RSS_URL = f"{BASE_URL}/uz/rss"
_RSS_DOC_RE = re.compile(r"/docs/(-?\d+)")
# Idoraviy hujjatlarda raqam o'rnida Adliya vazirligi ro'yxat raqami: "...buyrugʻi рег. № МЮ 3941."
# (2026-09-27 RSS'da 131 dan 23 tasi) — raqam "3941", tur oxiridagi "рег" olib tashlanadi.
_RSS_NUMBER_RE = re.compile(r"№\s*(?:МЮ\s+)?([^\s.]+(?:\.[^\s.]+)*)")
_RSS_REG_SUFFIX_RE = re.compile(r"\s+рег$")


@dataclass(frozen=True)
class RssItem:
    lex_id: str
    title: str
    url: str  # canonical: https://lex.uz/docs/<id>
    description: str
    doc_type: str | None
    number: str | None
    adoption_date: date | None
    effective_date: date | None
    pub_date: datetime | None


def _rss_description_fields(desc: str) -> tuple[str | None, str | None, date | None, date | None]:
    """"Oʻzbekiston Respublikasi Prezidentining Farmoni №PF-206. Qabul qilingan sana 23.09.2026. Kuchga kirish sanasi 25.09.2026"."""
    doc_type = desc.split("№")[0].strip(" .") or None if "№" in desc else (desc.split(".")[0].strip() or None)
    doc_type = _RSS_REG_SUFFIX_RE.sub("", doc_type) if doc_type else None
    m = _RSS_NUMBER_RE.search(desc)
    number = m.group(1).rstrip(".") if m else None
    adoption = _parse_date(desc.split("Qabul qilingan sana", 1)[1]) if "Qabul qilingan sana" in desc else None
    effective = _parse_date(desc.split("Kuchga kirish sanasi", 1)[1]) if "Kuchga kirish sanasi" in desc else None
    return doc_type, number, adoption, effective


def parse_rss(xml_text: str) -> list[RssItem]:
    """Lex.uz RSS (https://lex.uz/uz/rss). Tashqi entity/DTD yuklanmaydi."""
    from email.utils import parsedate_to_datetime

    from lxml import etree

    if not xml_text or not xml_text.strip():
        raise LexUzError("Bo'sh RSS")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(xml_text.lstrip("﻿").encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        raise LexUzError(f"RSS XML xatosi: {exc}") from exc
    items: list[RssItem] = []
    for it in root.iter("item"):
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        m = _RSS_DOC_RE.search(link)
        if not m:
            continue
        lex_id = m.group(1)
        desc = _clean(it.findtext("description") or "")
        doc_type, number, adoption, effective = _rss_description_fields(desc)
        pub = None
        if it.findtext("pubDate"):
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate").strip())
            except (TypeError, ValueError):
                pub = None
        items.append(RssItem(
            lex_id=lex_id, title=_clean(it.findtext("title") or ""), url=doc_url(lex_id), description=desc,
            doc_type=doc_type, number=number, adoption_date=adoption, effective_date=effective, pub_date=pub,
        ))
    return items


# --- Qidiruv (milliy qonunchilik: https://lex.uz/uz/search/nat) ---------------------
#
# Real sahifalar asosida (2026-09-27, `tests/fixtures/lexuz/search-*.html.gz`):
# - URL: `/uz/search/nat?searchtitle=..&query=..&status=Y&form_id=..&lang=4` (sayt JS'idagi `goSearch`).
# - Natijalar server tomonida: `tr.dd-table__main-item`, sahifada 20 ta; jami "<N> hujjat topildi".
# - Holat belgisi: `span.lx_act_state i.status_code_<x>` — namunalarda `y` (amaldagi) va `r` (kuchini
#   yo'qotgan). Boshqa qiymatlar xom holda saqlanadi; yakuniy holat baribir kartochkadan olinadi.
# - Badge: "<tur>, DD.MM.YYYY yildagi <raqam>-son" yoki
#   "<tur>, DD.MM.YYYY yilda ro'yxatdan o'tgan, ro'yxat raqami <raqam>" (idoraviy hujjatlar).
# - Keyingi sahifa `?page=` bilan emas, ASP.NET postback: `form#Form1` yashirin maydonlari +
#   `__EVENTTARGET=ucFoundActsControl$LinkButton1` bilan POST (cookie'siz ishlaydi). Oxirgi sahifada havola yo'q.

SEARCH_NAT_URL = f"{BASE_URL}/uz/search/nat"
# Sayt formasidagi "Shakli" ro'yxatidan (form_1 select).
SEARCH_FORM_IDS = {
    "kodeks": "3964", "qonun": "3968", "farmon": "3973", "qaror": "3972", "farmoyish": "588",
    "nizom": "487", "tartib": "573", "qoidalar": "488", "reglament": "575", "yoriqnoma": "489",
}
SEARCH_STATUSES = frozenset({"Y", "R", "N"})  # Amaldagi / O'z kuchini yo'qotgan / Amalda emas
_SEARCH_DOC_RE = re.compile(r"/docs/(-?\d+)/?$")
_SEARCH_TOTAL_RE = re.compile(r"(\d[\d\s ]*)\s+hujjat topildi")
_POSTBACK_RE = re.compile(r"__doPostBack\('([^']+)'")
_APOS = "[‘'ʻ’`]"
_BADGE_NUMBER_RE = re.compile(r"^(?P<type>.+?),\s*(?P<date>\d{2}\.\d{2}\.\d{4})\s+yildagi\s+(?P<num>.+?)-son$")
_BADGE_REG_RE = re.compile(
    rf"^(?P<type>.+?),\s*(?P<date>\d{{2}}\.\d{{2}}\.\d{{4}})\s+yilda\s+ro{_APOS}yxatdan\s+o{_APOS}tgan,"
    rf"\s*ro{_APOS}yxat\s+raqami\s+(?P<reg>.+)$"
)
_NEXT_PAGE_ID = "ucFoundActsControl_LinkButton1"


@dataclass(frozen=True)
class SearchItem:
    lex_id: str
    title: str
    url: str  # canonical: https://lex.uz/docs/<id>
    doc_type: str | None
    adoption_date: date | None  # "yildagi" sanasi yoki ro'yxatdan o'tgan sana
    number: str | None  # "PF-140", "508"
    reg_number: str | None  # Adliya vazirligi ro'yxat raqami ("2822-1")
    site_status: str | None  # "y", "r", ... (qidiruv sahifasidagi belgi)
    badge: str


@dataclass(frozen=True)
class SearchPage:
    items: list[SearchItem]
    total: int | None
    next_url: str | None = None  # keyingi sahifa: shu URL'ga `next_data` bilan POST
    next_data: dict[str, str] | None = None


def search_url(*, title: str | None = None, text: str | None = None, status: str | None = "Y",
               form: str | None = None, lang: str = "4", exact: bool = False) -> str:
    """Qidiruv URL'i. `title` — hujjat nomida, `text` — matnida; `form` — `SEARCH_FORM_IDS` kaliti.

    Sayt cheklovlari: matn 3–100 belgi; kamida bitta shart.
    """
    from urllib.parse import urlencode

    params: dict[str, str] = {}
    for name, value in (("searchtitle", title), ("query", text)):
        if value is None:
            continue
        value = " ".join(value.split())
        if not 3 <= len(value) <= 100:
            raise ValueError(f"Qidiruv matni 3–100 belgi bo'lishi kerak: {value!r}")
        params[name] = value
        if exact:
            params["exact2" if name == "searchtitle" else "exact"] = "1"
    if form is not None:
        if form not in SEARCH_FORM_IDS:
            raise ValueError(f"Noma'lum hujjat shakli: {form!r}")
        params["form_id"] = SEARCH_FORM_IDS[form]
    if status is not None:
        if status not in SEARCH_STATUSES:
            raise ValueError(f"Noma'lum holat filtri: {status!r}")
        params["status"] = status
    if not params:
        raise ValueError("Qidiruv uchun kamida bitta shart kerak")
    params["lang"] = lang
    return f"{SEARCH_NAT_URL}?{urlencode(params)}"


def _parse_badge(badge: str) -> tuple[str | None, date | None, str | None, str | None]:
    m = _BADGE_NUMBER_RE.match(badge)
    if m:
        return m.group("type").strip(), _parse_date(m.group("date")), m.group("num").strip(), None
    m = _BADGE_REG_RE.match(badge)
    if m:
        return m.group("type").strip(), _parse_date(m.group("date")), None, m.group("reg").strip()
    head = _DATE_RE.split(badge, maxsplit=1)[0].strip(" ,")
    return head or None, _parse_date(badge), None, None


def parse_search(html: str, page_url: str) -> SearchPage:
    """Qidiruv natijalari sahifasi. `page_url` — shu sahifa URL'i (keyingi sahifa POST manzili uchun)."""
    if not html or not html.strip():
        raise LexUzError("Bo'sh qidiruv sahifasi")
    soup = BeautifulSoup(html, "lxml")
    items: list[SearchItem] = []
    for row in soup.select("tr.dd-table__main-item"):
        link = row.select_one(".dd-table__main-left-desc a[href]")
        if link is None:
            continue
        m = _SEARCH_DOC_RE.search(urlsplit(link["href"]).path)
        if not m:
            continue
        lex_id = m.group(1)
        badge_el = row.select_one(".dd-table__main-extra .badge")
        badge = _clean(badge_el.get_text(" ")) if badge_el else ""
        doc_type, adoption, number, reg = _parse_badge(badge) if badge else (None, None, None, None)
        site_status = None
        for icon in row.select("span.lx_act_state i"):
            for cls in icon.get("class", []):
                if cls.startswith("status_code_"):
                    site_status = cls.removeprefix("status_code_") or None
        items.append(SearchItem(
            lex_id=lex_id, title=_clean(link.get_text(" ")), url=doc_url(lex_id), doc_type=doc_type,
            adoption_date=adoption, number=number, reg_number=reg, site_status=site_status, badge=badge,
        ))

    total = None
    m = _SEARCH_TOTAL_RE.search(soup.get_text(" "))
    if m:
        total = int(re.sub(r"\D", "", m.group(1)))
    elif not items:
        total = 0

    next_url = next_data = None
    nxt = soup.find(id=_NEXT_PAGE_ID)
    form = soup.find("form", id="Form1")
    pb = _POSTBACK_RE.search(nxt.get("href", "")) if nxt is not None else None
    if pb and form is not None:
        next_data = {i["name"]: i.get("value", "") for i in form.find_all("input", type="hidden") if i.get("name")}
        next_data.update({"__EVENTTARGET": pb.group(1), "__EVENTARGUMENT": ""})
        next_url = urljoin(page_url, form.get("action") or page_url)
    return SearchPage(items=items, total=total, next_url=next_url, next_data=next_data)


def search(url: str, *, client: LexUzClient, max_pages: int = 50) -> tuple[list[SearchItem], int | None]:
    """Qidiruvning barcha sahifalari (ko'pi bilan `max_pages`). Natija: (hujjatlar, sayt aytgan jami soni)."""
    page = parse_search(client.fetch(url, use_cache=False), url)
    total = page.total
    items = list(page.items)
    seen = {i.lex_id for i in items}
    pages = 1
    while page.next_url and page.next_data and pages < max_pages:
        page_url = page.next_url
        page = parse_search(client.fetch(page_url, data=page.next_data), page_url)
        pages += 1
        new = [i for i in page.items if i.lex_id not in seen]
        if not new:  # sayt bir xil sahifani qaytarsa — cheksiz aylanishdan himoya
            break
        items.extend(new)
        seen.update(i.lex_id for i in new)
    if total is not None and len(items) < total and pages >= max_pages:
        log.warning("lexuz search truncated url=%s got=%d total=%d pages=%d", url, len(items), total, pages)
    return items, total
