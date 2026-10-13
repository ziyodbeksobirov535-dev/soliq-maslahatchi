"""OpenAI-mos API orqali LLM (sinov uchun bepul tariflar): Google Gemini, Groq, OpenRouter.

    LLM_PROVIDER=openai_compat
    LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai   # Gemini (Google AI Studio kaliti)
    LLM_API_KEY=...
    LLM_MAIN_MODEL=... / LLM_FAST_MODEL=...

- `ClaudeLLM` bilan bir xil interfeys va promptlar: rewrite_queries, answer, classify_news, news_digest.
- Structured output: `response_format` json_schema (Pydantic sxemasi, $ref'lar ochilgan); provayder rad etsa —
  json_object rejimi va sxema system promptda. Javob baribir Pydantic bilan tekshiriladi (iqtiboslar — backend
  `validate_answer` da, provayderdan qat'i nazar).
- 429 va 5xx — qayta urinish (bepul tariflarda daqiqalik limit tez-tez uchraydi).
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.client import LLMError, Usage
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

RETRIES = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
TIMEOUT_SECONDS = 120.0
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON sxemasi: $ref'lar ochilgan, "title"/"default" olib tashlangan (ayrim provayderlar
    ularni qabul qilmaydi)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def parse_json(text: str, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate(json.loads(_FENCE_RE.sub("", (text or "").strip())))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"Model javobi sxemaga mos emas: {type(exc).__name__}") from exc


class OpenAICompatLLM:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        settings.require("llm_base_url", "llm_api_key", "llm_main_model", "llm_fast_model")
        self.base_url = settings.llm_base_url.rstrip("/")
        self.main_model = settings.llm_main_model
        self.fast_model = settings.llm_fast_model
        self.max_tokens = settings.anthropic_max_tokens
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
        )
        self._json_schema_ok = True  # provayder json_schema'ni rad etsa — json_object rejimiga o'tiladi

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        for attempt in range(RETRIES):
            try:
                response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                if attempt == RETRIES - 1:
                    raise LLMError("AI API'ga ulanib bo'lmadi") from exc
            else:
                if response.status_code not in RETRY_STATUSES or attempt == RETRIES - 1:
                    return response
                log.warning("llm retry status=%s attempt=%d", response.status_code, attempt + 1)
            time.sleep(2 * (attempt + 1))
        raise LLMError("AI API'ga ulanib bo'lmadi")

    def _parse(self, *, model: str, system: str, user: str, output_format: type[BaseModel], max_tokens: int,
               usage: Usage) -> Any:
        schema = inline_schema(output_format)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._json_schema_ok:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": output_format.__name__, "schema": schema}}
            response = self._post(payload)
            if response.status_code == 400 and "response_format" in response.text:
                log.warning("llm json_schema rad etildi — json_object rejimi")
                self._json_schema_ok = False
        if not self._json_schema_ok:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] = (
                f"{system}\n\nJavobni faqat shu JSON sxemaga mos JSON obyekt sifatida qaytar:\n"
                f"{json.dumps(schema, ensure_ascii=False)}")
            response = self._post(payload)

        if response.status_code in (401, 403):
            raise LLMError("AI API kaliti noto'g'ri yoki ruxsat yo'q")
        if response.status_code == 404:
            raise LLMError(f"Model topilmadi: {model}")
        if response.status_code == 429:
            raise LLMError("AI API limiti tugadi, keyinroq urinib ko'ring")
        if response.status_code >= 400:
            raise LLMError(f"AI API xatosi ({response.status_code})")

        data = response.json()
        usage.model = data.get("model") or model
        u = data.get("usage") or {}
        usage.input_tokens += u.get("prompt_tokens") or 0
        usage.output_tokens += u.get("completion_tokens") or 0
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("Javob max_tokens chegarasida kesildi")
        return parse_json((choice.get("message") or {}).get("content") or "", output_format)

    def rewrite_queries(self, question: str, usage: Usage) -> list[str]:
        parsed: QueryRewrite = self._parse(
            model=self.fast_model, system=REWRITE_SYSTEM_PROMPT, user=render_rewrite_message(question),
            output_format=QueryRewrite, max_tokens=1024, usage=usage,
        )
        return [q.strip() for q in parsed.queries if q.strip()][:4]

    def answer(self, user_message: str, usage: Usage) -> AnswerOutput:
        return self._parse(model=self.main_model, system=SYSTEM_PROMPT, user=user_message,
                           output_format=AnswerOutput, max_tokens=self.max_tokens, usage=usage)

    def classify_news(self, title: str, meta: str, excerpt: str, usage: Usage) -> NewsClassification:
        return self._parse(model=self.fast_model, system=NEWS_SYSTEM_PROMPT,
                           user=render_news_message(title, meta, excerpt), output_format=NewsClassification,
                           max_tokens=1024, usage=usage)

    def news_digest(self, title: str, meta: str, elements: list[tuple[str, str]], usage: Usage) -> NewsDigest:
        return self._parse(model=self.fast_model, system=NEWS_DIGEST_PROMPT,
                           user=render_digest_message(title, meta, elements), output_format=NewsDigest,
                           max_tokens=2048, usage=usage)
