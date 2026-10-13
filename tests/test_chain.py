"""Provayderlar zanjiri: band/xato bo'lsa navbatdagisi, rad etish o'tkazilmaydi, sozlamalardan qurish."""

import pytest
from pydantic import SecretStr

from app.ai.chain import ChainLLM
from app.ai.client import LLMError, LLMRefusal, Usage
from app.config import Settings


class Stub:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def _go(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def rewrite_queries(self, question, usage):
        return self._go()

    def answer(self, message, usage):
        return self._go()


def test_busy_provider_falls_through_to_next():
    gemini, groq = Stub(error=LLMError("AI API band")), Stub(result=["qqs stavkalari"])
    chain = ChainLLM([("gemini", gemini), ("groq", groq)])
    assert chain.rewrite_queries("NDS", Usage()) == ["qqs stavkalari"]
    assert gemini.calls == 1 and groq.calls == 1


def test_first_success_stops_chain():
    gemini, groq = Stub(result="javob"), Stub(result="boshqa")
    assert ChainLLM([("gemini", gemini), ("groq", groq)]).answer("savol", Usage()) == "javob"
    assert groq.calls == 0


def test_refusal_is_not_passed_to_other_providers():
    gemini, groq = Stub(error=LLMRefusal("SAFETY")), Stub(result="javob")
    with pytest.raises(LLMRefusal):
        ChainLLM([("gemini", gemini), ("groq", groq)]).answer("savol", Usage())
    assert groq.calls == 0


def test_all_failed_reports_each_provider():
    chain = ChainLLM([("gemini", Stub(error=LLMError("band"))), ("groq", Stub(error=LLMError("limit")))])
    with pytest.raises(LLMError, match="gemini: band; groq: limit"):
        chain.answer("savol", Usage())


def test_make_llm_builds_chain_from_settings():
    from app.ai.gemini import GeminiLLM
    from app.ai.openai_compat import OpenAICompatLLM
    from app.bot.app import make_llm

    base = dict(_env_file=None, llm_provider="gemini", llm_api_key="g", llm_main_model="m", llm_fast_model="f")
    llm = make_llm(Settings(**base, llm_fallbacks="groq, openrouter", groq_api_key=SecretStr("q"),
                            openrouter_api_key="o", openrouter_main_model="x/y:free"))
    assert isinstance(llm, ChainLLM)
    assert [n for n, _ in llm.providers] == ["gemini", "groq", "openrouter"]
    assert isinstance(llm.providers[1][1], OpenAICompatLLM) and llm.providers[1][1].main_model == "openai/gpt-oss-120b"
    assert llm.providers[2][1].fast_model == "x/y:free"  # fast berilmasa — main
    # zaxira kaliti yo'q — o'tkazib yuboriladi, bitta provayder bo'lsa zanjir emas
    assert isinstance(make_llm(Settings(**base, llm_fallbacks="groq")), GeminiLLM)
    # asosiy yo'q, zaxira bor — zaxira ishlaydi
    only = make_llm(Settings(_env_file=None, llm_provider="gemini", llm_fallbacks="groq", groq_api_key="q"))
    assert isinstance(only, OpenAICompatLLM) and only.name == "groq"
