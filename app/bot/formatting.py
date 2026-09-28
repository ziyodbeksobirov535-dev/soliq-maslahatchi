"""Telegram uchun formatlash: HTML parse_mode, xavfsiz escape, 4096 belgi chegarasi.

Model javobidagi oddiy markdown (**qalin**, *kursiv*, `kod`, "- " ro'yxat) HTML'ga o'giriladi;
qolgan hamma narsa escape qilinadi. Havolalar faqat backend tomonidan (bazadan) qo'shiladi.
"""

from __future__ import annotations

import html
import re

from app.ai.prompts import SourceArticle
from app.retrieval.articles import Article
from app.services.answer import SOURCES_ONLY_TEXT, FinalAnswer

TELEGRAM_LIMIT = 4096
SAFE_LIMIT = 3900

STATUS_UZ = {
    "amalda": "amalda",
    "kuchga_kirmagan": "kuchga kirmagan",
    "kuchini_yoqotgan": "kuchini yo'qotgan",
    "noma'lum": "holati noma'lum",
}


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def md_to_html(text: str) -> str:
    """Cheklangan markdown → Telegram HTML. Avval escape, keyin belgilangan shakllar."""
    out = esc(text)
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", out)
    out = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*[-*]\s+", "• ", out, flags=re.MULTILINE)
    return out


def split_message(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Xabarni satr chegarasida bo'ladi (HTML teglari satr ichida yopiladi deb hisoblanadi)."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # juda uzun satr — majburiy kesish (teglarsiz matn uchun)
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def link(url: str, title: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{esc(title)}</a>'


def format_notes(fa: FinalAnswer) -> list[str]:
    """Javob boshidagi izohlar: imlo tuzatishlari va ruscha savol."""
    notes = []
    if fa.followup_of:
        prev = fa.followup_of if len(fa.followup_of) <= 80 else fa.followup_of[:79] + "…"
        notes.append(f"🔗 Oldingi savolingiz bilan bog'lab qidirdim: «{esc(prev)}»")
    if fa.corrections:
        fixes = ", ".join(f"«{esc(a)}» → «{esc(b)}»" for a, b in fa.corrections.items())
        notes.append(f"✏️ Imlo tuzatildi: {fixes}")
    if fa.language == "ru":
        notes.append("🔤 Savol rus tilida — atamalarni o'zbekchaga o'girib qidirdim, javob o'zbek tilida.")
    return [*notes, ""] if notes else []


def format_sources_only(fa: FinalAnswer) -> str:
    lines = [esc(SOURCES_ONLY_TEXT), ""]
    for h in fa.hints:
        lines.append(f"📌 <b>{esc(h.document_name)}</b>, {link(h.link, h.title)}")
        if h.snippet:
            lines.append(f"<i>{esc(h.snippet)}</i>")
        lines.append("")
    lines.append("To'liq matnni ko'rish uchun quyidagi tugmani bosing.")
    return "\n".join(lines)


def format_final_answer(fa: FinalAnswer) -> str:
    """Izohlar + javob. answered — model javobi va bazadagi manbalar; sources_only — topilgan manbalar;
    boshqa holatlar — backend matni (escape)."""
    body = _format_body(fa)
    return "\n".join(format_notes(fa) + [body])


def _format_body(fa: FinalAnswer) -> str:
    if fa.status == "sources_only":
        return format_sources_only(fa)
    if fa.status != "answered":
        lines = []
        for line in fa.text.split("\n"):
            m = re.fullmatch(r"\s*(https://lex\.uz/\S+)", line)
            lines.append(f"  {link(m.group(1), 'Lex.uz')}" if m else esc(line))
        return "\n".join(lines)

    answer_part = fa.text.split("\n*Huquqiy asos:*")[0]
    lines = [md_to_html(answer_part.strip()), "", "<b>Huquqiy asos:</b>"]
    grouped: dict[str, list] = {}
    for c in fa.citations:
        grouped.setdefault(c.source.link, []).append(c)
    for url, cs in grouped.items():
        a: SourceArticle = cs[0].article
        claims = "; ".join(dict.fromkeys(c.claim for c in cs))
        status = "" if a.document_status == "amalda" else f" ({esc(STATUS_UZ.get(a.document_status, a.document_status))})"
        lines.append(f"• {esc(a.document_name)}, {link(url, a.title)}{status} — {esc(claims)}")
    return "\n".join(lines)


def format_article(article: Article, max_chars: int = 12000) -> str:
    """/modda javobi: hujjat, holat, sarlavha (havola), modda matni. Claude ishlatilmaydi."""
    status = STATUS_UZ.get(article.document_status, article.document_status)
    head = [
        f"<b>{esc(article.document_name)}</b>",
        f"Holati: {esc(status)}" + (f" · versiya {esc(article.current_version)}" if article.current_version else ""),
        "",
        f"<b>{link(article.heading.link, article.heading.text)}</b>",
    ]
    body, used = [], 0
    for e in article.body:
        piece = esc(e.text)
        if used + len(piece) > max_chars:
            body.append(f"… (davomi: {link(article.link, 'Lex.uzda to‘liq matn')})")
            break
        body.append(piece)
        used += len(piece)
    tail = []
    if article.has_future_changes:
        tail = ["", "⚠️ Bu moddaga kelajakda kuchga kiradigan o'zgarishlar bor — Lex.uzdagi tahrirni tekshiring."]
    return "\n".join(head + [""] + body + tail + ["", f"Manba: {link(article.link, 'Lex.uz')}"])


def format_news(entries) -> str:
    """/yangiliklar: oxirgi 7 kun, soliq/biznesga oid; metadata + qisqa faktik xulosa + Lex.uz havolasi."""
    lines = ["<b>Qonunchilikdagi yangiliklar (so'nggi 7 kun)</b>", ""]
    for e in entries:
        meta = ", ".join(p for p in [
            e.doc_type or "", f"№{e.number}" if e.number else "",
            f"qabul qilingan {e.adoption_date:%d.%m.%Y}" if e.adoption_date else "",
            f"kuchga kirish {e.effective_date:%d.%m.%Y}" if e.effective_date else "",
        ] if p)
        lines.append(f"• {link(e.url, e.title)}")
        if meta:
            lines.append(f"  {esc(meta)}")
        if e.status and e.status != "amalda":
            lines.append(f"  Holati: {esc(STATUS_UZ.get(e.status, e.status))}")
        if e.summary:
            lines.append(f"  {esc(e.summary)}")
        lines.append("")
    return "\n".join(lines).rstrip()
