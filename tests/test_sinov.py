"""app/ai/sinov.py: prompt yig'ish va qo'lda olingan model javobini tekshirish (bazasiz)."""

import json

from app.ai.prompts import SYSTEM_PROMPT, SourceArticle, SourceElement
from app.ai.sinov import articles_from_json, articles_to_json, build_prompt, check, extract_json, slug


def el(n, kind="text", text="Matn"):
    return SourceElement(source_id=f"EL-{n}", element_id=f"e{n}", kind=kind, text=text,
                         link=f"https://lex.uz/docs/-1#e{n}")


ARTICLES = [SourceArticle(lex_id="-1", document_name="Soliq kodeksi", document_status="amalda",
                          current_version=None, modda_raqami="461",
                          heading=el(1, "heading", "461-modda. Stavkalar"), elements=[el(2, text="Stavka 12 foiz.")])]


def answer(citations, needs_more=()):
    return json.dumps({"answer_markdown": "Stavka 12 foiz. https://lex.uz/x", "confidence": "high",
                       "citations": [{"source_id": s, "claim": "stavka"} for s in citations],
                       "needs_more": list(needs_more)})


def test_articles_json_roundtrip():
    assert articles_from_json(json.loads(json.dumps(articles_to_json(ARTICLES)))) == ARTICLES


def test_prompt_contains_system_schema_and_user_message():
    p = build_prompt("<savol>QQS?</savol>")
    assert SYSTEM_PROMPT.strip() in p and '"answer_markdown"' in p and p.rstrip().endswith("</savol>")


def test_extract_json_from_fenced_and_surrounding_text():
    assert extract_json('Mana:\n```json\n{"a": 1}\n```\nTayyor.') == {"a": 1}
    assert extract_json('oldin {"a": {"b": 2}} keyin') == {"a": {"b": 2}}


def test_check_valid_answer_uses_db_link_and_strips_model_url():
    text, notes = check(answer(["EL-2"]), ARTICLES)
    assert "holat: answered" in notes[0]
    assert "https://lex.uz/docs/-1#e2" in text and "lex.uz/x" not in text


def test_check_rejects_invented_source_id():
    text, notes = check(answer(["EL-999"]), ARTICLES)
    assert "insufficient" in notes[0] and any("EL-999" in n for n in notes)


def test_check_needs_more():
    _, notes = check(answer([], ["QQS chegarasi"]), ARTICLES)
    assert "insufficient" in notes[0] and "needs_more: QQS chegarasi" in notes


def test_slug():
    assert slug("Aylanma solig'idan QQSga qachon o'tish kerak?") == "aylanma-soligidan-qqsga-qachon-otish-ker"
