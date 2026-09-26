from datetime import date

import httpx
import pytest

import lexuz
from lexuz import LexUzClient, LexUzEmptyResponse, LexUzError, LexUzHTTPError

URL = "https://lex.uz/docs/-4674902"


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(responses, tmp_path=None, **kwargs):
    """responses: navbatdagi javoblar ro'yxati (httpx.Response yoki Exception)."""
    calls: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    fake = FakeTime()
    client = LexUzClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=fake.sleep,
        clock=fake.clock,
        wall_clock=fake.clock,
        cache_dir=tmp_path,
        **kwargs,
    )
    return client, calls, fake


def html(body: str = "<html><body>ok</body></html>", status: int = 200, **headers) -> httpx.Response:
    return httpx.Response(status, text=body, headers=headers)


# --- havolalar ---------------------------------------------------------


def test_doc_url_current_and_historical():
    assert lexuz.doc_url("-4674902") == "https://lex.uz/docs/-4674902"
    assert lexuz.doc_url("-4674902", date(2024, 12, 1)) == "https://lex.uz/docs/-4674902?ONDATE=01.12.2024"


def test_elem_link_canonical():
    assert lexuz.elem_link("-4674902", "-7966265") == "https://lex.uz/docs/-4674902#-7966265"


@pytest.mark.parametrize("bad", ["", "abc", "123456789/../x", "-12a", "https://lex.uz/docs/1"])
def test_invalid_ids_rejected(bad):
    with pytest.raises(ValueError):
        lexuz.elem_link("-4674902", bad)
    with pytest.raises(ValueError):
        lexuz.doc_url(bad)


# --- fetch -------------------------------------------------------------


def test_fetch_success():
    client, calls, _ = make_client([html("<p>salom</p>")])
    assert client.fetch(URL) == "<p>salom</p>"
    assert len(calls) == 1
    assert "soliq-maslahatchi" in calls[0].headers["User-Agent"]


def test_cookies_are_not_sent_between_requests():
    client, calls, _ = make_client(
        [httpx.Response(200, text="<p>1</p>", headers={"Set-Cookie": "ui=oz; Path=/"}), html()]
    )
    client.fetch(URL, use_cache=False)
    client.fetch(URL, use_cache=False)
    assert "cookie" not in {k.lower() for k in calls[1].headers}


def test_rejects_non_lexuz_host():
    client, calls, _ = make_client([])
    with pytest.raises(ValueError):
        client.fetch("https://example.com/docs/1")
    assert calls == []


def test_retries_on_server_error_with_exponential_backoff():
    client, calls, fake = make_client(
        [html(status=500), html(status=503), html("<p>ok</p>")], backoff_base_seconds=2.0
    )
    assert client.fetch(URL) == "<p>ok</p>"
    assert len(calls) == 3
    backoffs = [s for s in fake.sleeps if s in (2.0, 4.0)]
    assert backoffs == [2.0, 4.0]


def test_retry_after_header_is_respected():
    client, _, fake = make_client([html(status=429, **{"Retry-After": "7"}), html()])
    client.fetch(URL)
    assert 7.0 in fake.sleeps


def test_client_error_is_not_retried():
    client, calls, _ = make_client([html(status=404)])
    with pytest.raises(LexUzHTTPError) as exc:
        client.fetch(URL)
    assert exc.value.status_code == 404
    assert len(calls) == 1


def test_gives_up_after_max_retries():
    client, calls, _ = make_client([html(status=502)] * 3, max_retries=2)
    with pytest.raises(LexUzHTTPError):
        client.fetch(URL)
    assert len(calls) == 3


def test_network_error_is_retried_then_raised():
    err = httpx.ConnectError("boom")
    client, calls, _ = make_client([err, err], max_retries=1)
    with pytest.raises(LexUzError):
        client.fetch(URL)
    assert len(calls) == 2


@pytest.mark.parametrize("body", ["", "   \n\t "])
def test_empty_response_raises(body):
    client, _, _ = make_client([html(body)])
    with pytest.raises(LexUzEmptyResponse):
        client.fetch(URL)


def test_delay_between_requests():
    client, _, fake = make_client([html(), html()], delay_seconds=1.5)
    client.fetch(URL, use_cache=False)
    client.fetch(URL + "?ONDATE=01.01.2024", use_cache=False)
    assert fake.sleeps == [1.5]


def test_cache_hit_skips_network(tmp_path):
    client, calls, _ = make_client([html("<p>v1</p>")], tmp_path=tmp_path)
    assert client.fetch(URL) == "<p>v1</p>"
    assert client.fetch(URL) == "<p>v1</p>"
    assert len(calls) == 1


def test_cache_expires(tmp_path):
    client, calls, fake = make_client(
        [html("<p>v1</p>"), html("<p>v2</p>")], tmp_path=tmp_path, cache_ttl_seconds=60
    )
    client.fetch(URL)
    # Fayl mtime haqiqiy vaqtda; soxta soatni undan ancha oldinga suramiz.
    import time

    fake.now = time.time() + 3600
    assert client.fetch(URL) == "<p>v2</p>"
    assert len(calls) == 2


def test_errors_are_not_cached(tmp_path):
    client, calls, _ = make_client([html(status=404), html("<p>ok</p>")], tmp_path=tmp_path)
    with pytest.raises(LexUzHTTPError):
        client.fetch(URL)
    assert client.fetch(URL) == "<p>ok</p>"
    assert len(calls) == 2
