"""
AEGIS Multi-Provider LLM Client Factory
Supports local Ollama, OpenAI (GPT-4o), Google Gemini, Anthropic Claude, and DeepSeek.
Provides a unified OpenAI-compatible chat.completions.create(...) interface.
"""

import os
import json
from typing import List, Dict, Any, Optional
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


def get_llm_client(model_name: str) -> tuple[Any, str]:
    """
    Returns a configured client instance and the normalized model identifier.
    Raises ValueError with a helpful message if required API keys are missing.
    """
    model_lower = model_name.lower().strip()

    # 1. Google Gemini models
    if "gemini" in model_lower:
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not gemini_key:
            raise ValueError(
                f"Cannot use '{model_name}': GEMINI_API_KEY environment variable is not configured. "
                "Set GEMINI_API_KEY in your .env or environment, or select an Ollama local model."
            )
        # Use Google's OpenAI-compatible endpoint
        client = OpenAI(
            api_key=gemini_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        # Normalize model name
        if "flash" in model_lower:
            resolved_model = "gemini-1.5-flash"
        elif "pro" in model_lower:
            resolved_model = "gemini-1.5-pro"
        else:
            resolved_model = model_name
        return client, resolved_model

    # 2. OpenAI ChatGPT models
    elif "gpt" in model_lower or model_lower.startswith("o1") or model_lower.startswith("o3"):
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError(
                f"Cannot use '{model_name}': OPENAI_API_KEY environment variable is not configured. "
                "Set OPENAI_API_KEY in your .env or environment, or select an Ollama local model."
            )
        client = OpenAI(api_key=openai_key)
        return client, model_name

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
        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com/v1")
        return client, "deepseek-coder"

    # 5. Default: Local Ollama
    else:
        client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
        return client, model_name
