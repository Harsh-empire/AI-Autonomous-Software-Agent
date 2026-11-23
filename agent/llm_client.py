"""
AEGIS Multi-Provider LLM Client Factory
Supports local Ollama (default), OpenRouter, Google Gemini, OpenAI, Anthropic Claude and DeepSeek.
Provides a unified OpenAI-compatible chat.completions.create(...) interface.

Cloud providers are wrapped with retry/backoff on rate limits (HTTP 429) and optional pacing.
Select a provider with the model name (AEGIS_MODEL / UI):
  qwen2.5-coder:7b                  local Ollama (default, offline)
  gemini-2.5-flash                  Google Gemini (GEMINI_API_KEY), use an exact id from AI Studio
  openrouter:<model id>             OpenRouter (OPENROUTER_API_KEY), e.g. openrouter:<vendor/model>:free
  gpt-4o / claude-... / deepseek-cloud   OpenAI / Anthropic / DeepSeek (paid keys)
"""

import os
import json
import random
import time
import types
from typing import List, Dict, Any, Optional, Callable
import requests
from openai import OpenAI

# Try loading .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")


class AnthropicMessageWrapper:
    """Wraps Anthropic API responses to match OpenAI's choices[0].message.content structure."""
    def __init__(self, content: str):
        self.content = content


class AnthropicChoiceWrapper:
    def __init__(self, message: AnthropicMessageWrapper):
        self.message = message


class AnthropicResponseWrapper:
    def __init__(self, text: str):
        self.choices = [AnthropicChoiceWrapper(AnthropicMessageWrapper(text))]


class AnthropicChatCompletions:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.anthropic.com/v1/messages"

    def create(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.7, **kwargs) -> AnthropicResponseWrapper:
        # Separate system messages from conversational messages
        system_text = ""
        user_assistant_messages = []

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                system_text += f"{content}\n"
            elif role in ("user", "assistant"):
                user_assistant_messages.append({"role": role, "content": content})

        if not user_assistant_messages:
            user_assistant_messages.append({"role": "user", "content": "Hello"})

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Normalize model name if alias given
        anthropic_model = model
        if model in ("claude-3-5-sonnet", "claude-3.5-sonnet"):
            anthropic_model = "claude-3-5-sonnet-20241022"
        elif model in ("claude-3-5-haiku", "claude-3.5-haiku"):
            anthropic_model = "claude-3-5-haiku-20241022"

        payload = {
            "model": anthropic_model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": user_assistant_messages,
            "temperature": min(max(temperature, 0.0), 1.0)
        }
        if system_text:
            payload["system"] = system_text.strip()

        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API error (status {resp.status_code}): {resp.text}")

        data = resp.json()
        text_blocks = [item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"]
        result_text = "".join(text_blocks)
        return AnthropicResponseWrapper(result_text)


class AnthropicClientWrapper:
    """Exposes client.chat.completions.create for Anthropic Claude."""
    def __init__(self, api_key: str):
        self.chat = type("Chat", (), {"completions": AnthropicChatCompletions(api_key)})()


class LLMQuotaError(RuntimeError):
    """A provider kept answering "rate limited / quota exhausted" after all retries."""


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_rate_limit(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or "ratelimit" in type(exc).__name__.lower()


def _is_retryable(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) in (408, 409, 429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__.lower()
    return any(k in name for k in ("ratelimit", "timeout", "connection"))


class _ThrottledCompletions:
    """chat.completions with retry/backoff (and optional pacing) for cloud providers."""

    def __init__(self, inner: Any, max_retries: int, min_interval: float,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self._inner = inner
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_call: Optional[float] = None

    def _pace(self) -> None:
        if self._min_interval > 0 and self._last_call is not None:
            wait = self._min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def create(self, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(self._max_retries + 1):
            self._pace()
            try:
                return self._inner.create(*args, **kwargs)
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                if attempt == self._max_retries:
                    if _is_rate_limit(exc):
                        raise LLMQuotaError(
                            f"Rate limit / quota still exceeded after {self._max_retries} retries "
                            f"({type(exc).__name__}). Free tiers have per-minute and per-day limits: wait for "
                            "the reset, lower the request rate (AEGIS_LLM_MIN_INTERVAL) or use a local model."
                        ) from exc
                    raise
                delay = _retry_after_seconds(exc)
                if delay is None:
                    delay = min(60.0, 2.0 ** (attempt + 1))
                self._sleep(delay + random.uniform(0, 1.0))
        raise RuntimeError("unreachable")  # pragma: no cover


class ThrottledClient:
    """Wraps an OpenAI-compatible client; only chat.completions.create is retried/paced."""

    def __init__(self, inner: Any, max_retries: Optional[int] = None, min_interval: Optional[float] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self._inner = inner
        if max_retries is None:
            max_retries = int(os.environ.get("AEGIS_LLM_MAX_RETRIES", "5"))
        if min_interval is None:
            min_interval = float(os.environ.get("AEGIS_LLM_MIN_INTERVAL", "0"))
        self.chat = types.SimpleNamespace(
            completions=_ThrottledCompletions(inner.chat.completions, max_retries, min_interval, sleep, clock)
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _is_openai_model(model_lower: str) -> bool:
    # "gpt-oss" is an open-weight model served by Ollama, not an OpenAI cloud model.
    if model_lower.startswith("gpt-oss"):
        return False
    return model_lower.startswith(("gpt-", "chatgpt", "o1", "o3", "o4"))


def provider_for(model_name: str) -> str:
    """Which provider get_llm_client() will use for this model name."""
    m = model_name.lower().strip()
    if m.startswith("openrouter:"):
        return "openrouter"
    if "gemini" in m:
        return "gemini"
    if _is_openai_model(m):
        return "openai"
    if "claude" in m:
        return "anthropic"
    if m.startswith("deepseek-cloud"):
        return "deepseek"
    return "ollama"


def get_llm_client(model_name: str) -> tuple[Any, str]:
    """
    Returns a configured client instance and the normalized model identifier.
    Raises ValueError with a helpful message if required API keys are missing.
    """
    model_lower = model_name.lower().strip()

    # 0. OpenRouter: "openrouter:<model id>" (checked first, the model id may contain e.g. "gemini")
    if model_lower.startswith("openrouter:"):
        or_key = os.environ.get("OPENROUTER_API_KEY")
        if not or_key:
            raise ValueError(
                f"Cannot use '{model_name}': OPENROUTER_API_KEY environment variable is not configured. "
                "Set OPENROUTER_API_KEY in your environment (never commit it), or select an Ollama local model."
            )
        model_id = model_name.split(":", 1)[1].strip()
        if not model_id:
            raise ValueError("Use the form openrouter:<model id>, e.g. openrouter:<vendor/model>:free")
        client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1", max_retries=0)
        return ThrottledClient(client), model_id

    # 1. Google Gemini models
    if "gemini" in model_lower:
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not gemini_key:
            raise ValueError(
                f"Cannot use '{model_name}': GEMINI_API_KEY environment variable is not configured. "
                "Set GEMINI_API_KEY in your .env or environment, or select an Ollama local model."
            )
        if model_lower in ("gemini", "gemini-flash", "gemini-pro"):
            raise ValueError(
                f"'{model_name}' is not an exact model id. Use an exact Gemini model id from Google AI Studio "
                "(for example gemini-2.5-flash) and check which models your free tier allows; the older "
                "gemini-1.5-* models are deprecated."
            )
        # Google's OpenAI-compatible endpoint; the model id is passed through unchanged.
        client = OpenAI(
            api_key=gemini_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            max_retries=0,
        )
        return ThrottledClient(client), model_name

    # 2. OpenAI ChatGPT models
    elif _is_openai_model(model_lower):
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError(
                f"Cannot use '{model_name}': OPENAI_API_KEY environment variable is not configured. "
                "Set OPENAI_API_KEY in your .env or environment, or select an Ollama local model."
            )
        client = OpenAI(api_key=openai_key, max_retries=0)
        return ThrottledClient(client), model_name

    # 3. Anthropic Claude models
    elif "claude" in model_lower:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if not anthropic_key:
            raise ValueError(
                f"Cannot use '{model_name}': ANTHROPIC_API_KEY environment variable is not configured. "
                "Set ANTHROPIC_API_KEY in your .env or environment, or select an Ollama local model."
            )
        client = AnthropicClientWrapper(anthropic_key)
        resolved_model = "claude-3-5-sonnet-20241022" if "sonnet" in model_lower else model_name
        return client, resolved_model

    # 4. DeepSeek Cloud
    elif model_lower.startswith("deepseek-cloud"):
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
        if not deepseek_key:
            raise ValueError(
                "DEEPSEEK_API_KEY environment variable is not configured. "
                "For local DeepSeek, pull 'deepseek-coder' into Ollama."
            )
        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com/v1", max_retries=0)
        return ThrottledClient(client), "deepseek-coder"

    # 5. Default: Local Ollama
    else:
        timeout_val = float(os.environ.get("AEGIS_LLM_TIMEOUT", "300.0"))
        client = OpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key="ollama",
            timeout=timeout_val,
            max_retries=0
        )
        return client, model_name


def format_llm_error(exc: Exception, model_name: str, base_url: str = OLLAMA_BASE_URL) -> str:
    """Formats an exception from an LLM call into a clear, actionable user message."""
    err_str = str(exc)
    err_type = type(exc).__name__
    clean_url = base_url.replace("/v1", "").rstrip("/")

    # Timeout
    if "timeout" in err_str.lower() or "timed out" in err_str.lower() or "Timeout" in err_type:
        return (
            f"LLM request timed out while generating with model '{model_name}'. "
            "Local CPU inference can be very slow; try a smaller/quantized model or increase AEGIS_LLM_TIMEOUT."
        )

    # Unreachable / Connection error
    if (
        "connection" in err_str.lower()
        or "connect" in err_str.lower()
        or "APIConnectionError" in err_type
        or "failed to establish" in err_str.lower()
    ):
        return f"Ollama unreachable at {clean_url}. Ensure the Ollama daemon is running ('ollama serve')."

    # Model not pulled / 404
    if "404" in err_str or "not found" in err_str.lower():
        return f"Model '{model_name}' not pulled: run `ollama pull {model_name}` in your terminal."

    # Invalid JSON / schema error
    if "invalid json" in err_str.lower() or "json" in err_str.lower():
        return f"Model returned invalid JSON after 3 attempts: {err_str}"

    return f"Model error ({err_type}): {err_str}"

