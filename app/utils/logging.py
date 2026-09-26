"""Logging: har bir yozuvda request_id, maxfiy qiymatlar avtomatik yashiriladi.

Qoida (spec 23-24): loglarga savol matni, ism, telefon kabi PII yozilmaydi —
faqat request_id, bosqich (stage), vaqt va identifikatorlar.
"""

from __future__ import annotations

import contextvars
import logging
import re
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Tokenlar .env da bo'lmasa ham tanib olinadigan umumiy shakllar.
_SECRET_PATTERNS = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic API key
    re.compile(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+(@)"),  # DB URL ichidagi parol
)
_REDACTED = "***"

LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


def get_request_id() -> str:
    return _request_id.get()


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Blok ichidagi barcha loglarga bitta request_id (UUID) biriktiradi."""
    rid = request_id or str(uuid.uuid4())
    token = _request_id.set(rid)
    try:
        yield rid
    finally:
        _request_id.reset(token)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class SecretRedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        # Qisqa qiymatlarni yashirish oddiy so'zlarni buzishi mumkin.
        self._secrets = sorted({s for s in secrets if len(s) >= 8}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, _REDACTED)
        for pattern in _SECRET_PATTERNS:
            if pattern.groups:
                text = pattern.sub(rf"\g<1>{_REDACTED}\g<2>", text)
            else:
                text = pattern.sub(_REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


def setup_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(RequestIdFilter())
    handler.addFilter(SecretRedactingFilter(secrets))

    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)

    # Kutubxonalar HTTP so'rovlarni (URL ichida token bilan) INFO darajada yozadi.
    for noisy in ("httpx", "httpcore", "aiogram.event"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
