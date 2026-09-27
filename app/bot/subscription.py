"""Majburiy kanal a'zoligi: botdan foydalanish uchun REQUIRED_CHANNEL kanaliga a'zo bo'lish kerak.

- `.env`: REQUIRED_CHANNEL (`@kanal_nomi` yoki `-100...` id), REQUIRED_CHANNEL_URL (taklif havolasi; bo'sh bo'lsa
  `@nom` dan https://t.me/nom). REQUIRED_CHANNEL bo'sh — tekshiruv o'chiq.
- Tekshiruv Telegram `getChatMember` orqali — **bot kanalda admin bo'lishi shart** (aks holda Telegram a'zolikni
  aytmaydi). Tekshirib bo'lmasa (bot admin emas, kanal noto'g'ri) — foydalanuvchi to'xtatilmaydi, logda ogohlantirish:
  sozlama xatosi hamma foydalanuvchini botdan chiqarib yubormasin.
- Adminlar tekshirilmaydi. /start va "✅ A'zo bo'ldim" tugmasi doim ishlaydi.
- A'zolik natijasi 10 daqiqa keshlanadi (har xabarda Telegram'ga so'rov yubormaslik uchun); a'zo emaslik
  keshlanmaydi — foydalanuvchi a'zo bo'lishi bilan ishlay boshlaydi.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from app.config import Settings

log = logging.getLogger(__name__)

CHECK_CALLBACK = "sub:check"
MEMBER_CACHE_SECONDS = 600
_MEMBER_STATUSES = {"creator", "administrator", "member"}

GATE_TEXT = (
    "Botdan foydalanish uchun rasmiy kanalimizga a'zo bo'ling — u yerda soliq va qonunchilikdagi "
    "yangiliklarni birinchi bo'lib olasiz.\n\nA'zo bo'lgach, <b>✅ A'zo bo'ldim</b> tugmasini bosing."
)


def channel_url(settings: Settings) -> str | None:
    if settings.required_channel_url:
        return settings.required_channel_url
    channel = settings.required_channel or ""
    return f"https://t.me/{channel[1:]}" if channel.startswith("@") else None


def gate_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    url = channel_url(settings)
    if url:
        rows.append([InlineKeyboardButton(text="📢 Kanalga o'tish", url=url)])
    rows.append([InlineKeyboardButton(text="✅ A'zo bo'ldim", callback_data=CHECK_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class MembershipChecker:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._members: dict[int, float] = {}  # user_id → kesh muddati
        self._clock = clock

    async def is_member(self, bot: Bot, settings: Settings, user_id: int, *, fresh: bool = False) -> bool | None:
        """True/False — a'zo/a'zo emas; None — tekshirib bo'lmadi (sozlama yoki Telegram xatosi)."""
        now = self._clock()
        if not fresh and self._members.get(user_id, 0) > now:
            return True
        try:
            member = await bot.get_chat_member(settings.required_channel, user_id)
        except TelegramAPIError as exc:
            log.warning("kanal a'zoligi tekshirilmadi channel=%s error=%s — bot kanalda adminmi?",
                        settings.required_channel, type(exc).__name__)
            return None
        ok = member.status in _MEMBER_STATUSES or bool(getattr(member, "is_member", False))
        if ok:
            self._members[user_id] = now + MEMBER_CACHE_SECONDS
        else:
            self._members.pop(user_id, None)
        return ok


def _is_exempt(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        return bool(event.text) and event.text.split(maxsplit=1)[0].split("@")[0] == "/start"
    if isinstance(event, CallbackQuery):
        return event.data == CHECK_CALLBACK
    return False


class SubscriptionMiddleware(BaseMiddleware):
    """Kanal a'zosi bo'lmagan foydalanuvchining xabari/tugmasi handler'ga yetmaydi — o'rniga taklif."""

    def __init__(self, checker: MembershipChecker) -> None:
        self.checker = checker

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        settings: Settings = data["settings"]
        user = data.get("event_from_user")
        if not settings.required_channel or user is None or settings.is_admin(user.id) or _is_exempt(event):
            return await handler(event, data)
        if await self.checker.is_member(data["bot"], settings, user.id) is not False:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("Avval kanalga a'zo bo'ling", show_alert=True)
            return None
        if isinstance(event, Message):
            await event.answer(GATE_TEXT, parse_mode=ParseMode.HTML, reply_markup=gate_keyboard(settings))
        return None
