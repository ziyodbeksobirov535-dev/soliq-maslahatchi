"""Provayderlar zanjiri: asosiy provayder band, limiti tugagan yoki xato bersa — navbatdagisi.

    LLM_PROVIDER=gemini            # asosiy
    LLM_FALLBACKS=groq,openrouter  # zaxira, tartib bo'yicha

Bepul tariflarda model tez-tez "band" (503) yoki daqiqalik limitga (429) tushadi — zanjir bilan javob kuchsizroq
modelga yoki faqat manbalar ro'yxatiga tushib qolmaydi. Model javob berishdan bosh tortsa (LLMRefusal — xavfsizlik)
— savol boshqa provayderga yuborilmaydi. Har bir provayderning javobi bir xil tekshiruvdan o'tadi
(sxema — Pydantic, iqtiboslar — `validate_answer`).
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.client import LLMError, LLMRefusal, Usage
from app.ai.schemas import AnswerOutput, NewsClassification, NewsDigest

log = logging.getLogger(__name__)


# Qisqa so'rovli vazifalar (`:fast` belgili zaxira faqat shularda ishlatiladi): savolni rasmiy so'rovlarga
# aylantirish, yangilikni saralash va xabar tayyorlash. Javob (`answer`) — katta kontekst (Lex.uz moddalari):
# Groq bepul tarifida daqiqasiga 8 000 token, javob so'rovi esa ~12 000 (413); OpenRouter bepul modellaridan biri
# kontekstdagi PF-100 ni e'tiborsiz qoldirib xato javob berdi — xato javob "faqat manbalar" dan yomonroq
# (2026-10-14 sinov).
FAST_METHODS = frozenset({"rewrite_queries", "classify_news", "news_digest"})


class ChainLLM:
    def __init__(self, providers: list[tuple[str, Any]], fast_only: set[str] | None = None) -> None:
        """providers: [(nomi, LLM)]; fast_only: faqat FAST_METHODS uchun ishlatiladigan provayder nomlari."""
        if not providers:
            raise ValueError("ChainLLM: kamida bitta provayder kerak")
        self.providers = providers
        self.fast_only = fast_only or set()

    def _call(self, method: str, *args: Any) -> Any:
        errors = []
        usable = [(n, llm) for n, llm in self.providers if n not in self.fast_only or method in FAST_METHODS]
        if not usable:
            raise LLMError(f"'{method}' uchun AI provayder yo'q")
        for name, llm in usable:
            try:
                return getattr(llm, method)(*args)
            except LLMRefusal:
                raise
            except LLMError as exc:
                errors.append(f"{name}: {exc}")
                log.warning("llm chain provider=%s method=%s xato=%s — navbatdagisi", name, method, exc)
        raise LLMError("Barcha AI provayderlar javob bermadi (" + "; ".join(errors) + ")")

    def rewrite_queries(self, question: str, usage: Usage) -> list[str]:
        return self._call("rewrite_queries", question, usage)

    def answer(self, user_message: str, usage: Usage) -> AnswerOutput:
        return self._call("answer", user_message, usage)

    def classify_news(self, title: str, meta: str, excerpt: str, usage: Usage) -> NewsClassification:
        return self._call("classify_news", title, meta, excerpt, usage)

    def news_digest(self, title: str, meta: str, elements: list[tuple[str, str]], usage: Usage) -> NewsDigest:
        return self._call("news_digest", title, meta, elements, usage)
