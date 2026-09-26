import logging

import pytest
from pydantic import ValidationError

from app.config import MissingSettingError, Settings
from app.utils.logging import RequestIdFilter, SecretRedactingFilter, get_request_id, request_context


def settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


def test_defaults():
    s = settings()
    assert s.timezone == "Asia/Tashkent"
    assert s.daily_question_limit == 20
    assert s.lexuz_delay_seconds == 1.5
    assert s.lexuz_max_retries == 5
    assert s.anthropic_main_model is None  # model ID kodda yo'q


def test_admin_ids_parsed_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", " 123, 456 ,")
    s = Settings(_env_file=None)
    assert s.admin_telegram_ids == frozenset({123, 456})
    assert s.is_admin(123) and not s.is_admin(789)


def test_admin_ids_invalid(monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "123,abc")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_timezone():
    with pytest.raises(ValidationError):
        settings(timezone="Mars/Olympus")


def test_empty_string_is_missing_and_require_lists_all(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    s = Settings(_env_file=None)
    with pytest.raises(MissingSettingError) as exc:
        s.require("telegram_bot_token", "anthropic_api_key")
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_secrets_hidden_in_repr():
    s = settings(anthropic_api_key="sk-ant-supersecretvalue123")
    assert "supersecret" not in repr(s)
    assert s.secret_values() == ["sk-ant-supersecretvalue123"]


def test_request_context_sets_uuid():
    assert get_request_id() == "-"
    with request_context() as rid:
        assert get_request_id() == rid
        assert len(rid) == 36
    assert get_request_id() == "-"


def _record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_redacts_known_and_pattern_secrets():
    f = SecretRedactingFilter(["my-custom-secret-xyz"])
    rec = _record(
        "k=%s tg=%s db=%s ant=%s",
        "my-custom-secret-xyz",
        "1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ",
        "postgresql://user:p4ssw0rd@db.example.com:5432/postgres",
        "sk-ant-api03-abcdefghijklmnop",
    )
    f.filter(rec)
    text = rec.getMessage()
    for leaked in ("my-custom-secret-xyz", "AAHdqTcv", "p4ssw0rd", "abcdefghijklmnop"):
        assert leaked not in text
    assert "postgresql://user:***@db.example.com" in text


def test_request_id_filter():
    rec = _record("x")
    with request_context("abc"):
        RequestIdFilter().filter(rec)
    assert rec.request_id == "abc"
