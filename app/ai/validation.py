"""Citation security (spec 10, 28): model javobini backend tekshiradi.

1. Faqat shu so'rovning kontekstidagi `source_id` lar qabul qilinadi; noma'lumlari rad etiladi va log qilinadi.
2. Havola faqat bazadan (SourceElement.link) — model yozgan URL ishlatilmaydi.
3. Javob matnidagi har qanday URL olib tashlanadi (Telegram'dagi havolalarni backend qo'shadi).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.ai.prompts import SourceArticle, SourceElement
from app.ai.schemas import AnswerOutput

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s)\]>\"']+|\blex\.uz/[^\s)\]>\"']*", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", re.IGNORECASE)


@dataclass(frozen=True)
class ValidCitation:
    source: SourceElement
    article: SourceArticle
    claim: str


@dataclass
class ValidatedAnswer:
    answer_markdown: str
    citations: list[ValidCitation]
    needs_more: list[str]
    confidence: str
    rejected_source_ids: list[str] = field(default_factory=list)
    removed_urls: list[str] = field(default_factory=list)

    @property
    def has_valid_citations(self) -> bool:
        return bool(self.citations)


def build_source_index(articles: list[SourceArticle]) -> dict[str, tuple[SourceElement, SourceArticle]]:
    return {el.source_id: (el, a) for a in articles for el in a.all_elements()}


def strip_urls(text: str) -> tuple[str, list[str]]:
    removed: list[str] = []

    def md(m: re.Match[str]) -> str:
        removed.append(m.group(0))
        return m.group(1)

    text = _MD_LINK_RE.sub(md, text)

    def bare(m: re.Match[str]) -> str:
        removed.append(m.group(0))
        return ""

    text = _URL_RE.sub(bare, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\(\s*\)", "", text)
    return text.strip(), removed


def validate_answer(output: AnswerOutput, articles: list[SourceArticle]) -> ValidatedAnswer:
    index = build_source_index(articles)
    citations: list[ValidCitation] = []
    rejected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for c in output.citations:
        sid = c.source_id.strip()
        hit = index.get(sid)
        if hit is None:
            rejected.append(sid)
            continue
        key = (sid, c.claim.strip())
        if key in seen:
            continue
        seen.add(key)
        el, art = hit
        citations.append(ValidCitation(source=el, article=art, claim=c.claim.strip()))

    answer, removed = strip_urls(output.answer_markdown)
    if rejected:
        log.warning("citation rejected unknown_source_ids=%s", rejected)
    if removed:
        log.warning("citation removed_urls count=%d", len(removed))
    return ValidatedAnswer(
        answer_markdown=answer,
        citations=citations,
        needs_more=[q.strip() for q in output.needs_more if q.strip()],
        confidence=output.confidence,
        rejected_source_ids=rejected,
        removed_urls=removed,
    )
