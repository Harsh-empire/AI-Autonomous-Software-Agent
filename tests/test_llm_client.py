"""
Tests for provider selection and the retry/throttle wrapper in agent/llm_client.py.
No network access: cloud clients are constructed but never called; retries use a fake clock.
"""

import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from agent.llm_client import (  # noqa: E402
    LLMQuotaError,
    ThrottledClient,
    get_llm_client,
    provider_for,
)

KEYS = ["OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]


@pytest.fixture(autouse=True)
def _clean_keys(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------- provider selection
@pytest.mark.parametrize("name,expected", [
    ("qwen2.5-coder:7b", "ollama"),
    ("gpt-oss:20b", "ollama"),                       # open-weight model served by Ollama
    ("gpt-4o", "openai"),
    ("gemini-2.5-flash", "gemini"),
    ("openrouter:google/gemini-2.0-flash:free", "openrouter"),  # not "gemini"
    ("claude-3-5-sonnet", "anthropic"),
    ("deepseek-cloud", "deepseek"),
])
def test_provider_for(name, expected):
    assert provider_for(name) == expected


def test_openrouter_requires_key_and_strips_prefix(monkeypatch):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_llm_client("openrouter:vendor/some-model:free")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client, model = get_llm_client("openrouter:vendor/some-model:free")
    assert model == "vendor/some-model:free"
    assert str(client._inner.base_url).startswith("https://openrouter.ai/api/v1")
    assert isinstance(client, ThrottledClient)


def test_openrouter_needs_a_model_id(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with pytest.raises(ValueError, match="openrouter:<model id>"):
        get_llm_client("openrouter:")


def test_gemini_passes_the_exact_model_id_through(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client, model = get_llm_client("gemini-2.5-flash")
    assert model == "gemini-2.5-flash"  # never rewritten to a deprecated 1.5 model
    assert "generativelanguage.googleapis.com" in str(client._inner.base_url)


def test_gemini_bare_alias_is_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with pytest.raises(ValueError, match="exact model id"):
        get_llm_client("gemini-flash")


def test_gemini_requires_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        get_llm_client("gemini-2.5-flash")


def test_local_gpt_oss_does_not_need_an_openai_key():
    client, model = get_llm_client("gpt-oss:20b")  # must NOT raise about OPENAI_API_KEY
    assert model == "gpt-oss:20b"
    assert not isinstance(client, ThrottledClient)  # local Ollama is not throttled


# ---------------------------------------------------------------- retry / throttle
class _HttpError(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"http {status}")
        self.status_code = status
        self.response = type("R", (), {"headers": {"retry-after": str(retry_after)} if retry_after else {}})()


class _FakeInner:
    """Fails with the given errors in order, then succeeds."""

    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def _client(errors, **kw):
    sleeps = []
    inner = _FakeInner(errors)
    c = ThrottledClient(inner, sleep=sleeps.append, **kw)
    return c, inner, sleeps


def test_retries_on_429_and_honours_retry_after():
    c, inner, sleeps = _client([_HttpError(429, retry_after=7)], max_retries=3, min_interval=0)
    assert c.chat.completions.create(model="m", messages=[]) == "ok"
    assert inner.calls == 2
    assert 7 <= sleeps[0] < 8.5  # Retry-After (+ small jitter)


def test_exponential_backoff_without_retry_after():
    c, inner, sleeps = _client([_HttpError(503), _HttpError(429)], max_retries=3, min_interval=0)
    assert c.chat.completions.create(model="m", messages=[]) == "ok"
    assert inner.calls == 3
    assert 2 <= sleeps[0] < 3.5 and 4 <= sleeps[1] < 5.5


def test_gives_up_with_clear_quota_error():
    c, inner, _ = _client([_HttpError(429)] * 10, max_retries=2, min_interval=0)
    with pytest.raises(LLMQuotaError, match="Rate limit"):
        c.chat.completions.create(model="m", messages=[])
    assert inner.calls == 3  # first try + 2 retries


def test_non_retryable_errors_are_raised_immediately():
    c, inner, sleeps = _client([_HttpError(400)], max_retries=5, min_interval=0)
    with pytest.raises(_HttpError):
        c.chat.completions.create(model="m", messages=[])
    assert inner.calls == 1 and not sleeps


def test_server_errors_are_retried_but_not_reported_as_quota():
    c, inner, _ = _client([_HttpError(500)] * 5, max_retries=1, min_interval=0)
    with pytest.raises(_HttpError):  # the original error, not LLMQuotaError
        c.chat.completions.create(model="m", messages=[])
    assert inner.calls == 2


def test_min_interval_paces_calls():
    now = [100.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    inner = _FakeInner([])
    c = ThrottledClient(inner, max_retries=1, min_interval=6.0, sleep=sleep, clock=lambda: now[0])
    c.chat.completions.create(model="m", messages=[])      # first call: no wait
    now[0] += 2.0                                           # 2 s of other work
    c.chat.completions.create(model="m", messages=[])      # must wait the remaining 4 s
    assert sleeps == [pytest.approx(4.0)]


def test_env_configuration(monkeypatch):
    monkeypatch.setenv("AEGIS_LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("AEGIS_LLM_MIN_INTERVAL", "0")
    c, inner, _ = _client([_HttpError(429)] * 3)  # uses env defaults
    with pytest.raises(LLMQuotaError):
        c.chat.completions.create(model="m", messages=[])
    assert inner.calls == 2
