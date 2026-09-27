"""Claude API bilan ishlash (spec 22) — Anthropic Python SDK 1.x.

- Structured output: `client.beta.messages.parse(output_format=<Pydantic>)` — javob sxemaga
  mos kelishi kafolatlanadi (`parsed_output`).
- Model ID'lari faqat sozlamalardan (ANTHROPIC_MAIN_MODEL / ANTHROPIC_FAST_MODEL).
- Prompt caching: o'zgarmas system prompt `cache_control` bilan; savol va manbalar keshlanmaydi.
  (Juda qisqa prefiks keshlanmasligi mumkin — `usage.cache_read_input_tokens` bilan tekshiriladi.)
- Refusal: `stop_reason == "refusal"` tekshiriladi; server-side fallback sozlama orqali yoqiladi.
- Retry: SDK o'zi 408/409/429/5xx va tarmoq xatolarini qayta urinadi (max_retries).
- Thinking: yangi modellarda sukut bo'yicha adaptiv; `budget_tokens` ishlatilmaydi. Chuqurlik —
  ixtiyoriy `ANTHROPIC_EFFORT` (output_config.effort).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.ai.prompts import (
    NEWS_DIGEST_PROMPT,
    NEWS_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    render_digest_message,
    render_news_message,
    render_rewrite_message,
)
from app.ai.schemas import AnswerOutput, NewsClassification, NewsDigest, QueryRewrite
from app.config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Foydalanuvchiga sodda xabar ko'rsatiladigan LLM xatosi."""


class LLMRefusal(LLMError):
    pass


@dataclass
class Usage:
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    request_ids: list[str] | None = None

    def add(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        self.model = getattr(response, "model", None) or self.model
        if u is not None:
            self.input_tokens += getattr(u, "input_tokens", 0) or 0
            self.output_tokens += getattr(u, "output_tokens", 0) or 0
            self.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
            self.cache_creation_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        rid = getattr(response, "_request_id", None)
        if rid:
            self.request_ids = [*(self.request_ids or []), rid]


class LLM(Protocol):
    def rewrite_queries(self, question: str, usage: Usage) -> list[str]: ...

    def answer(self, user_message: str, usage: Usage) -> AnswerOutput: ...


class ClaudeLLM:
    """Haqiqiy Claude client'i. Testlarda o'rniga soxta LLM ishlatiladi."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        settings.require("anthropic_main_model", "anthropic_fast_model")
        self.main_model = settings.anthropic_main_model
        self.fast_model = settings.anthropic_fast_model
        self.max_tokens = settings.anthropic_max_tokens
        self.effort = settings.anthropic_effort
        self.fallback = settings.anthropic_refusal_fallback.strip().lower() != "off"
        if client is None:
            import anthropic

            settings.require("anthropic_api_key")
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value(), max_retries=3)
        self._client = client

    def _parse(self, *, model: str, system: str, user: str, output_format: type, max_tokens: int,
               fallback: bool, effort: str | None, usage: Usage) -> Any:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_format": output_format,
        }
        if effort:
            kwargs["output_config"] = {"effort": effort}
        if fallback:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            response = self._client.beta.messages.parse(**kwargs)
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Claude so'rovi rad etildi (400): {exc.message}") from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMError("Anthropic API kaliti noto'g'ri yoki ruxsat yo'q") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Model topilmadi: {model}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic API limiti tugadi, keyinroq urinib ko'ring") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API xatosi ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Anthropic API'ga ulanib bo'lmadi") from exc
        usage.add(response)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(f"Model javob berishdan bosh tortdi: {getattr(details, 'category', None)}")
        if response.stop_reason == "max_tokens":
            raise LLMError("Javob max_tokens chegarasida kesildi")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("Structured output olinmadi")
        return parsed

    def rewrite_queries(self, question: str, usage: Usage) -> list[str]:
        parsed: QueryRewrite = self._parse(
            model=self.fast_model, system=REWRITE_SYSTEM_PROMPT, user=render_rewrite_message(question),
            output_format=QueryRewrite, max_tokens=1024, fallback=False, effort=None, usage=usage,
        )
        return [q.strip() for q in parsed.queries if q.strip()][:4]

    def answer(self, user_message: str, usage: Usage) -> AnswerOutput:
        return self._parse(
            model=self.main_model, system=SYSTEM_PROMPT, user=user_message, output_format=AnswerOutput,
            max_tokens=self.max_tokens, fallback=self.fallback, effort=self.effort, usage=usage,
        )

    def classify_news(self, title: str, meta: str, excerpt: str, usage: Usage) -> NewsClassification:
        """Fast model: yangilik relevantligi va qisqa faktik xulosa (spec 17: faqat relevance classification)."""
        return self._parse(
            model=self.fast_model, system=NEWS_SYSTEM_PROMPT, user=render_news_message(title, meta, excerpt),
            output_format=NewsClassification, max_tokens=1024, fallback=False, effort=None, usage=usage,
        )

    def news_digest(self, title: str, meta: str, elements: list[tuple[str, str]], usage: Usage) -> NewsDigest:
        """Fast model: hujjatdan yangilik xabari (bandlar manba elementiga bog'langan, backend tekshiradi)."""
        return self._parse(
            model=self.fast_model, system=NEWS_DIGEST_PROMPT, user=render_digest_message(title, meta, elements),
            output_format=NewsDigest, max_tokens=2048, fallback=False, effort=None, usage=usage,
        )
