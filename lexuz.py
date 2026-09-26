"""Lex.uz fetch client va havola quruvchi.

Bu modul mustaqil (app/ ga bog'liq emas): sozlamalar konstruktor orqali beriladi.

Holat (PHASE 0):
- `fetch`, `doc_url`, `elem_link` — tayyor va testlangan.
- `parse_doc`, `load` — real Lex.uz HTML namunasi olingach yoziladi.
  HTML tuzilmasini taxmin qilib parser yozilmaydi (spec 36-bo'lim, 10-qoida).

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
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://lex.uz"
DEFAULT_USER_AGENT = "soliq-maslahatchi/0.1 (+https://github.com/ziyodbeksobirov535-dev/soliq-maslahatchi)"

_ID_RE = re.compile(r"^-?\d+$")
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


def _check_id(value: str, what: str) -> str:
    value = str(value).strip()
    if not _ID_RE.match(value):
        raise ValueError(f"Noto'g'ri Lex.uz {what}: {value!r}")
    return value


def doc_url(doc_id: str, on_date: date | None = None) -> str:
    """Hujjat URL'i. `on_date` berilsa — o'sha sana holatidagi tarixiy versiya (?ONDATE=DD.MM.YYYY)."""
    url = f"{BASE_URL}/docs/{_check_id(doc_id, 'hujjat ID')}"
    if on_date is not None:
        url += f"?ONDATE={on_date:%d.%m.%Y}"
    return url


def elem_link(doc_id: str, element_id: str) -> str:
    """Element uchun canonical havola, masalan https://lex.uz/docs/-4674902#-7966265."""
    return f"{doc_url(doc_id)}#{_check_id(element_id, 'element ID')}"


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

    def fetch(self, url: str, *, use_cache: bool = True) -> str:
        """URL matnini qaytaradi. Xatoda LexUzHTTPError / LexUzEmptyResponse / LexUzError."""
        if urlsplit(url).hostname not in {"lex.uz", "www.lex.uz"}:
            raise ValueError(f"Faqat lex.uz manzillari qabul qilinadi: {url!r}")

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
                try:
                    response = self._http.get(url, headers=self._headers)
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


def parse_doc(html: str):  # pragma: no cover - PHASE 0 davomida yoziladi
    raise NotImplementedError(
        "parse_doc real Lex.uz HTML namunasi bilan yoziladi (lex.uz hozir tarmoqdan bloklangan)"
    )


def load(doc_id: str, on_date: date | None = None, *, client: LexUzClient | None = None):  # pragma: no cover
    raise NotImplementedError("load parse_doc tayyor bo'lgach yoziladi")
