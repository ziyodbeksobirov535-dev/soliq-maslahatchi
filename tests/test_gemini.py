"""Gemini API (generateContent): kalit sarlavhasi, sxema, zaxira modellar, xatolar — soxta HTTP bilan."""

import json

import httpx
import pytest

from app.ai import gemini
from app.ai.client import LLMError, LLMRefusal, Usage
from app.ai.gemini import GeminiLLM
from app.config import Settings

ANSWER = {"answer_markdown": "Stavka 1 foiz.", "citations": [{"source_id": "EL-7", "claim": "1 foiz"}],
          "needs_more": [], "confidence": "high"}


def settings():
    return Settings(_env_file=None, llm_provider="gemini", llm_api_key="kalit",
                    llm_main_model="katta-flash,kichik-lite", llm_fast_model="kichik-lite")


def make(handler):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers.get("x-goog-api-key"), json.loads(request.content)))
        return handler(request, len(calls))

    client = httpx.Client(transport=httpx.MockTransport(wrapped), headers={"x-goog-api-key": "kalit"})
    return GeminiLLM(settings(), client=client), calls


def ok(content, reason="STOP", model="kichik-lite"):
    return httpx.Response(200, json={
        "modelVersion": model, "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 10,
                                                 "thoughtsTokenCount": 5},
        "candidates": [{"finishReason": reason, "content": {"parts": [
            {"text": "fikr", "thought": True}, {"text": content}]}}]})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)


def test_answer_request_shape_and_thought_parts_skipped():
    llm, calls = make(lambda req, n: ok(json.dumps(ANSWER)))
    usage = Usage()
    out = llm.answer("savol", usage)
    assert out.citations[0].source_id == "EL-7"
    path, key, body = calls[0]
    assert path.endswith("/models/katta-flash:generateContent") and key == "kalit"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "$ref" not in json.dumps(body["generationConfig"]["responseJsonSchema"])
    assert body["systemInstruction"]["parts"][0]["text"].startswith("Sen O'zbekiston")
    assert usage.input_tokens == 50 and usage.output_tokens == 15 and usage.model == "kichik-lite"


def test_busy_model_falls_back_to_next_without_retry():
    llm, calls = make(lambda req, n: httpx.Response(503, text="high demand") if "katta" in req.url.path
                      else ok(json.dumps(ANSWER)))
    assert llm.answer("savol", Usage()).confidence == "high"
    assert [c[0].split("/")[-1] for c in calls] == ["katta-flash:generateContent", "kichik-lite:generateContent"]


def test_last_model_busy_is_retried_then_error():
    llm, calls = make(lambda req, n: httpx.Response(503, text="high demand"))
    with pytest.raises(LLMError, match="band"):
        llm.rewrite_queries("savol", Usage())  # fast: bitta model — 3 urinish
    assert len(calls) == 3


def test_schema_rejected_goes_to_prompt_schema():
    def handler(req, n):
        if "responseJsonSchema" in json.loads(req.content)["generationConfig"]:
            return httpx.Response(400, text='{"error": {"message": "Invalid JSON schema"}}')
        return ok(json.dumps({"queries": ["aylanmadan olinadigan soliq stavkalari"]}))

    llm, calls = make(handler)
    assert llm.rewrite_queries("aborot soliq", Usage()) == ["aylanmadan olinadigan soliq stavkalari"]
    assert "JSON sxema" in calls[-1][2]["systemInstruction"]["parts"][0]["text"]


def test_blocked_and_truncated():
    llm, _ = make(lambda req, n: ok("{}", reason="SAFETY"))
    with pytest.raises(LLMRefusal):
        llm.answer("savol", Usage())
    llm, _ = make(lambda req, n: ok("{", reason="MAX_TOKENS"))
    with pytest.raises(LLMError, match="max_tokens"):
        llm.answer("savol", Usage())


def test_invalid_key():
    llm, _ = make(lambda req, n: httpx.Response(400, text='{"error": {"message": "API key not valid"}}'))
    with pytest.raises(LLMError, match="kaliti"):
        llm.answer("savol", Usage())


def test_make_llm_selects_gemini():
    from app.bot.app import make_llm

    assert isinstance(make_llm(settings()), GeminiLLM)
