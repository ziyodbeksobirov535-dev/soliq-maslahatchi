"""Google Gemini API (generateContent) orqali LLM — Google AI Studio kaliti bilan (bepul tarif).

    LLM_PROVIDER=gemini
    LLM_API_KEY=...                      # aistudio.google.com/apikey
    LLM_MAIN_MODEL=gemini-2.5-flash      LLM_FAST_MODEL=gemini-2.5-flash-lite
    LLM_BASE_URL=                        # bo'sh — https://generativelanguage.googleapis.com/v1beta

- Kalit `x-goog-api-key` sarlavhasida. Yangi formatdagi AI Studio kalitlarini OpenAI-mos manzil
  (`Authorization: Bearer`) qabul qilmaydi — 2026-10-13 sinov ("Missing or invalid Authorization header").
- Structured output: `responseMimeType=application/json` + `responseJsonSchema`; rad etilsa — sxema promptda.
  Javob Pydantic bilan, iqtiboslar `validate_answer` bilan tekshiriladi.
- Ulanish IPv4 orqali: IPv6 ishlamaydigan tarmoqda httpx IPv6 da ~45 s kutib qoladi (shu Mac'da o'lchangan).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.ai.client import LLMError, LLMRefusal, Usage
from app.ai.openai_compat import RETRIES, RETRY_STATUSES, TIMEOUT_SECONDS, inline_schema, parse_json
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

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
FALLBACK_TIMEOUT_SECONDS = 45.0  # zaxirasi bor model uchun (asosiy Flash band paytda qotib qoladi)
BLOCKED = frozenset({"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"})


class GeminiLLM:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        settings.require("llm_api_key", "llm_main_model", "llm_fast_model")
        self.base_url = (settings.llm_base_url or DEFAULT_BASE_URL).rstrip("/")
        # "model1,model2" — asosiy va zaxira modellar
        self.main_models = [m.strip() for m in settings.llm_main_model.split(",") if m.strip()]
        self.fast_models = [m.strip() for m in settings.llm_fast_model.split(",") if m.strip()]
        self.max_tokens = settings.anthropic_max_tokens
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=15.0),
            transport=httpx.HTTPTransport(local_address="0.0.0.0", retries=1),  # IPv4
            headers={"x-goog-api-key": settings.llm_api_key.get_secret_value()},
        )
        self._json_schema_ok = True

    def _post_one(self, model: str, payload: dict[str, Any], retries: int,
                  timeout: float = TIMEOUT_SECONDS) -> httpx.Response:
        url = f"{self.base_url}/models/{model}:generateContent"
        for attempt in range(retries):
            try:
                response = self._client.post(url, json=payload, timeout=httpx.Timeout(timeout, connect=15.0))
            except httpx.HTTPError as exc:
                if attempt == retries - 1:
                    raise LLMError("AI API'ga ulanib bo'lmadi") from exc
            else:
                if response.status_code not in RETRY_STATUSES or attempt == retries - 1:
                    return response
                log.warning("gemini retry model=%s status=%s attempt=%d", model, response.status_code, attempt + 1)
            time.sleep(2 * (attempt + 1))
        raise LLMError("AI API'ga ulanib bo'lmadi")

    def _post(self, models: list[str], payload: dict[str, Any]) -> tuple[str, httpx.Response]:
        """Modellar navbat bilan: band (503) yoki limit (429) bo'lsa — keyingisi (bepul tarifda Flash modellari
        tez-tez "high demand" qaytaradi). Zaxira bor bo'lsa, har model bir marta qayta urinadi."""
        for i, model in enumerate(models):
            last = i == len(models) - 1
            try:  # zaxirasi bor model qotib qolsa — uzoq kutmasdan keyingisiga
                response = self._post_one(model, payload, RETRIES if last else 1,
                                          TIMEOUT_SECONDS if last else FALLBACK_TIMEOUT_SECONDS)
            except LLMError:
                if last:
                    raise
                log.warning("gemini model=%s javob bermadi — zaxira modelga o'tiladi", model)
                continue
            if last or response.status_code not in RETRY_STATUSES:
                return model, response
            log.warning("gemini model=%s status=%s — zaxira modelga o'tiladi", model, response.status_code)
        raise LLMError("AI API'ga ulanib bo'lmadi")

    def _parse(self, *, models: list[str], system: str, user: str, output_format: type[BaseModel], max_tokens: int,
               usage: Usage) -> Any:
        schema = inline_schema(output_format)
        config: dict[str, Any] = {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        response = None
        if self._json_schema_ok:
            config["responseJsonSchema"] = schema
            model, response = self._post(models, payload)
            if response.status_code == 400 and "schema" in response.text.lower():
                log.warning("gemini responseJsonSchema rad etildi — sxema promptda")
                self._json_schema_ok = False
                config.pop("responseJsonSchema")
                response = None
        if response is None:
            payload["systemInstruction"]["parts"][0]["text"] = (
                f"{system}\n\nJavobni faqat shu JSON sxemaga mos JSON obyekt sifatida qaytar:\n"
                f"{json.dumps(schema, ensure_ascii=False)}")
            model, response = self._post(models, payload)

        if response.status_code in (401, 403) or "API key" in response.text and response.status_code == 400:
            raise LLMError("AI API kaliti noto'g'ri yoki ruxsat yo'q")
        if response.status_code == 404:
            raise LLMError(f"Model topilmadi: {model}")
        if response.status_code in (429, 503):
            raise LLMError("AI API band yoki limiti tugadi, keyinroq urinib ko'ring")
        if response.status_code >= 400:
            raise LLMError(f"AI API xatosi ({response.status_code})")

        data = response.json()
        usage.model = data.get("modelVersion") or model
        meta = data.get("usageMetadata") or {}
        usage.input_tokens += meta.get("promptTokenCount") or 0
        usage.output_tokens += (meta.get("candidatesTokenCount") or 0) + (meta.get("thoughtsTokenCount") or 0)
        if (data.get("promptFeedback") or {}).get("blockReason"):
            raise LLMRefusal(f"Model javob berishdan bosh tortdi: {data['promptFeedback']['blockReason']}")
        candidate = (data.get("candidates") or [{}])[0]
        reason = candidate.get("finishReason")
        if reason in BLOCKED:
            raise LLMRefusal(f"Model javob berishdan bosh tortdi: {reason}")
        if reason == "MAX_TOKENS":
            raise LLMError("Javob max_tokens chegarasida kesildi")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return parse_json(text, output_format)

    def rewrite_queries(self, question: str, usage: Usage) -> list[str]:
        parsed: QueryRewrite = self._parse(
            models=self.fast_models, system=REWRITE_SYSTEM_PROMPT, user=render_rewrite_message(question),
            output_format=QueryRewrite, max_tokens=2048, usage=usage,
        )
        return [q.strip() for q in parsed.queries if q.strip()][:4]

    def answer(self, user_message: str, usage: Usage) -> AnswerOutput:
        return self._parse(models=self.main_models, system=SYSTEM_PROMPT, user=user_message,
                           output_format=AnswerOutput, max_tokens=self.max_tokens, usage=usage)

    def classify_news(self, title: str, meta: str, excerpt: str, usage: Usage) -> NewsClassification:
        return self._parse(models=self.fast_models, system=NEWS_SYSTEM_PROMPT,
                           user=render_news_message(title, meta, excerpt), output_format=NewsClassification,
                           max_tokens=2048, usage=usage)

    def news_digest(self, title: str, meta: str, elements: list[tuple[str, str]], usage: Usage) -> NewsDigest:
        return self._parse(models=self.fast_models, system=NEWS_DIGEST_PROMPT,
                           user=render_digest_message(title, meta, elements), output_format=NewsDigest,
                           max_tokens=4096, usage=usage)
