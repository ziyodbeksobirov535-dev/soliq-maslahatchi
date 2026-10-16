"""Takroriy savollar uchun javob keshi (jarayon xotirasida, 24 soat).

Bir xil savol (normallashtirilgan matn), bir xil profil va bir xil kun — AI qayta chaqirilmaydi: tezroq javob,
bepul tarif limitlari tejaladi. Savol baribir kunlik limitga sanaladi va `suhbatlar`ga yangi request_id bilan
yoziladi (baho, statistika alohida).

- Faqat `answered` javoblar; davomiy savollar (oldingi savolga bog'liq) keshlanmaydi.
- Kalitda sana bor: kun almashsa (kuchga kirish sanalari) — qaytadan hisoblanadi.
- 👎 baho — javob keshdan o'chiriladi; admin eslatma qo'shsa/o'chirsa — kesh tozalanadi.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date

from app.ai.client import Usage
from app.retrieval.query import normalize

TTL_SECONDS = 24 * 3600
MAX_ENTRIES = 500
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[?!.,;:«»\"“”()]+")


def question_key(question: str, profile: dict | None, today: date) -> str:
    text = _SPACE_RE.sub(" ", _PUNCT_RE.sub(" ", normalize(question).lower())).strip()
    return f"{today.isoformat()}|{json.dumps(profile or {}, sort_keys=True, ensure_ascii=False)}|{text}"


@dataclass
class _Entry:
    answer: object  # FinalAnswer
    stored: float
    request_ids: set[str] = field(default_factory=set)


class AnswerCache:
    def __init__(self, ttl: float = TTL_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self.ttl, self.max_entries = ttl, max_entries
        self._data: dict[str, _Entry] = {}

    def get(self, key: str, request_id: str):
        """Keshdagi javob nusxasi — yangi request_id bilan, tokenlar 0 (AI chaqirilmadi)."""
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.stored > self.ttl:
            del self._data[key]
            return None
        entry.request_ids.add(request_id)
        fa = entry.answer
        return replace(fa, request_id=request_id, usage=Usage(model=f"kesh:{fa.usage.model or ''}"), processing_ms=0)

    def put(self, key: str, fa) -> None:
        if fa.status != "answered" or fa.followup_of:
            return
        if len(self._data) >= self.max_entries:  # eng eskisi chiqadi
            del self._data[min(self._data, key=lambda k: self._data[k].stored)]
        self._data[key] = _Entry(fa, time.monotonic(), {fa.request_id})

    def forget(self, request_id: str) -> bool:
        """👎 bahosi: shu javob (asl yoki keshdan berilgan nusxasi) keshdan o'chiriladi."""
        for key, entry in list(self._data.items()):
            if request_id in entry.request_ids:
                del self._data[key]
                return True
        return False

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
