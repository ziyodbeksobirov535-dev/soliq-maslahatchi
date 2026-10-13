"""OpenAI-mos provayder (Gemini, Groq, OpenRouter): so'rov shakli, sxema, zaxira rejim, xatolar — soxta HTTP bilan."""

import json

import httpx
import pytest

from app.ai import openai_compat
from app.ai.client import LLMError, Usage
from app.ai.openai_compat import OpenAICompatLLM, inline_schema
from app.ai.schemas import AnswerOutput
from app.config import Settings

ANSWER = {"answer_markdown": "QQS stavkasi 12 foiz.", "citations": [{"source_id": "EL-1", "claim": "12 foiz"}],
          "needs_more": [], "confidence": "high"}


def settings():
    return Settings(_env_file=None, llm_provider="openai_compat", llm_base_url="https://api.test/v1/",
                    llm_api_key="kalit", llm_main_model="katta", llm_fast_model="kichik")


def make(handler):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return handler(request, len(calls))

    client = httpx.Client(transport=httpx.MockTransport(wrapped), headers={"Authorization": "Bearer kalit"})
    return OpenAICompatLLM(settings(), client=client), calls


def ok(content, model="katta"):
    return httpx.Response(200, json={"model": model, "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                                     "choices": [{"finish_reason": "stop", "message": {"content": content}}]})


def test_inline_schema_has_no_refs():
    schema = inline_schema(AnswerOutput)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"title"' not in text
    assert schema["properties"]["citations"]["items"]["properties"]["source_id"]["type"] == "string"


def test_answer_uses_json_schema_and_counts_usage():
    llm, calls = make(lambda req, n: ok(json.dumps(ANSWER)))
    usage = Usage()
    out = llm.answer("savol", usage)
    assert out.answer_markdown.startswith("QQS") and out.citations[0].source_id == "EL-1"
    assert calls[0]["model"] == "katta" and calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["messages"][0]["role"] == "system"
    assert usage.input_tokens == 100 and usage.output_tokens == 20


def test_fenced_json_and_rewrite_uses_fast_model():
    llm, calls = make(lambda req, n: ok('```json\n{"queries": ["qqs stavkalari", " ", "qqs to\'lovchilar"]}\n```'))
    assert llm.rewrite_queries("NDS qancha", Usage()) == ["qqs stavkalari", "qqs to'lovchilar"]
    assert calls[0]["model"] == "kichik"


def test_json_schema_rejected_falls_back_to_json_object():
    def handler(req, n):
        if n == 1:
            return httpx.Response(400, text='{"error": "response_format json_schema is not supported"}')
        return ok(json.dumps(ANSWER))

    llm, calls = make(handler)
    assert llm.answer("savol", Usage()).confidence == "high"
    assert calls[1]["response_format"] == {"type": "json_object"}
    assert "JSON sxema" in calls[1]["messages"][0]["content"]
    llm.answer("yana", Usage())
    assert calls[2]["response_format"] == {"type": "json_object"}  # keyingi so'rovlar ham to'g'ridan-to'g'ri


def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(openai_compat.time, "sleep", lambda s: None)
    llm, calls = make(lambda req, n: httpx.Response(429, text="limit") if n < 3 else ok(json.dumps(ANSWER)))
    assert llm.answer("savol", Usage()).answer_markdown
    assert len(calls) == 3


@pytest.mark.parametrize("status,message", [(401, "kaliti"), (404, "Model topilmadi"), (500, "xatosi")])
def test_errors_become_llm_error(monkeypatch, status, message):
    monkeypatch.setattr(openai_compat.time, "sleep", lambda s: None)
    llm, _ = make(lambda req, n: httpx.Response(status, text="x"))
    with pytest.raises(LLMError, match=message):
        llm.answer("savol", Usage())


def test_invalid_json_and_truncation():
    llm, _ = make(lambda req, n: ok("bu json emas"))
    with pytest.raises(LLMError, match="sxemaga mos emas"):
        llm.answer("savol", Usage())
    llm, _ = make(lambda req, n: httpx.Response(200, json={"choices": [{"finish_reason": "length",
                                                                       "message": {"content": "{"}}]}))
    with pytest.raises(LLMError, match="max_tokens"):
        llm.answer("savol", Usage())


def test_make_llm_selects_provider():
    from app.bot.app import make_llm

    assert isinstance(make_llm(settings()), OpenAICompatLLM)
    assert make_llm(Settings(_env_file=None, llm_provider="openai_compat")) is None  # to'liq emas
