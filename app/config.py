"""Ilova sozlamalari: faqat environment / `.env` dan o'qiladi.

Model ID'lari, tokenlar va kalitlar source code'ga yozilmaydi (spec 21-bo'lim).
Har bir komponent o'ziga kerakli qiymatlarni `Settings.require()` bilan
ishga tushishda tekshiradi — masalan collector Telegram tokensiz ham ishlay oladi.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class MissingSettingError(RuntimeError):
    """Majburiy sozlama berilmagan."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_main_model: str | None = None
    anthropic_fast_model: str | None = None
    # Ixtiyoriy: "low" | "medium" | "high" | "xhigh" | "max" (bo'sh = model sukuti).
    anthropic_effort: str | None = None
    anthropic_max_tokens: int = Field(default=16000, gt=0)
    # Server-side refusal fallback: "default" yoki "off" (model qo'llamasa "off" qiling).
    anthropic_refusal_fallback: str = "default"

    supabase_url: str | None = None
    supabase_db_url: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None

    admin_telegram_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    daily_question_limit: int = Field(default=20, ge=0)
    timezone: str = "Asia/Tashkent"

    lexuz_delay_seconds: float = Field(default=1.5, ge=0)
    lexuz_max_retries: int = Field(default=5, ge=0)
    lexuz_timeout_seconds: float = Field(default=30.0, gt=0)
    lexuz_cache_dir: str = ".cache/lexuz"
    lexuz_cache_ttl_hours: float = Field(default=24.0, ge=0)

    log_level: str = "INFO"

    @field_validator(
        "telegram_bot_token",
        "anthropic_api_key",
        "anthropic_main_model",
        "anthropic_fast_model",
        "anthropic_effort",
        "supabase_url",
        "supabase_db_url",
        "supabase_service_role_key",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            try:
                return frozenset(int(p) for p in parts)
            except ValueError as exc:
                raise ValueError(
                    "ADMIN_TELEGRAM_IDS vergul bilan ajratilgan butun sonlar bo'lishi kerak"
                ) from exc
        return value

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Noma'lum timezone: {value!r}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Noto'g'ri LOG_LEVEL: {value!r}")
        return level

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_telegram_ids

    def require(self, *names: str) -> None:
        """Berilgan maydonlar to'ldirilganini tekshiradi, aks holda hammasini bir xabarda aytadi."""
        missing = [name.upper() for name in names if getattr(self, name) is None]
        if missing:
            raise MissingSettingError(
                "Quyidagi sozlamalar .env da berilmagan: " + ", ".join(missing)
            )

    def secret_values(self) -> list[str]:
        """Loglardan tozalash uchun barcha maxfiy qiymatlar."""
        secrets = (
            self.telegram_bot_token,
            self.anthropic_api_key,
            self.supabase_db_url,
            self.supabase_service_role_key,
        )
        return [s.get_secret_value() for s in secrets if s is not None]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
