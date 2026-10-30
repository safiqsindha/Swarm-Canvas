"""The only model seam. Nothing else imports a provider SDK."""

from __future__ import annotations

import copy
import os
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class ModelConfig:
    provider: str
    name: str = ""
    temperature: float = 0.7
    max_tokens: int = 600
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    reasoning_max_tokens: int | None = None
    reasoning_enabled: bool | None = None
    fake_responses: list[str] | None = None
    transport: httpx.BaseTransport | None = None
    usage: dict = field(
        default_factory=lambda: {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "retries": 0,
        }
    )
    calls_log: list[list[dict]] = field(default_factory=list)
    call_records: list[dict] = field(default_factory=list)
    paint_budget: int = 8
    output_kind: str = "painter"


_COLUMNS = [chr(ord("A") + i) for i in range(24)]
_PAINTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "scratchpad": {"type": "string"},
        "requests": {"type": "array", "items": {"type": "string"}},
        "messages": {"type": "array", "items": {"type": "string"}},
        "acks": {"type": "array", "items": {"type": "integer"}},
        "paints": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["column", "row", "color"],
                "properties": {
                    "column": {"type": "string", "enum": _COLUMNS},
                    "row": {"type": "integer", "minimum": 1, "maximum": 16},
                    "color": {"type": "string"},
                },
            },
        },
    },
}


def call_model(messages: list[dict], cfg: ModelConfig) -> str:
    """Call one model. Temperature and max_tokens come from cfg. At most 2 retries."""
    if cfg.provider == "fake":
        cfg.usage["calls"] += 1
        cfg.calls_log.append([dict(message) for message in messages])
        if not cfg.fake_responses:
            return ""
        return cfg.fake_responses.pop(0)

    validate_model_policy(cfg)

    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            text, usage = _request(messages, cfg)
        except Exception as exc:
            last_error = exc
            if attempt < 2 and _retryable(exc):
                cfg.usage["retries"] += 1
                continue
            break
        cfg.usage["calls"] += 1
        cfg.usage["input_tokens"] += int(usage.get("input", 0))
        cfg.usage["output_tokens"] += int(usage.get("output", 0))
        cfg.calls_log.append([dict(message) for message in messages])
        cfg.call_records.append(
            {
                "status": "ok",
                "requested_model": cfg.name,
                "served_model": usage.get("served_model"),
                "provider": usage.get("provider"),
                "response_id": usage.get("response_id"),
                "input_tokens": int(usage.get("input", 0)),
                "output_tokens": int(usage.get("output", 0)),
                "cost_usd": usage.get("cost"),
                "finish_reason": usage.get("finish_reason"),
                "reasoning_tokens": usage.get("reasoning_tokens"),
                "has_visible_content": usage.get("has_visible_content"),
                "elapsed_seconds": round(time.monotonic() - started, 4),
            }
        )
        return text
    status = (
        last_error.response.status_code
        if isinstance(last_error, httpx.HTTPStatusError)
        else None
    )
    cfg.call_records.append(
        {
            "status": "api_error",
            "requested_model": cfg.name,
            "error_type": type(last_error).__name__,
            "http_status": status,
            "elapsed_seconds": round(time.monotonic() - started, 4),
        }
    )
    raise ModelCallError(type(last_error).__name__, status) from last_error


class ModelCallError(RuntimeError):
    def __init__(self, error_type: str, http_status: int | None = None):
        self.error_type = error_type
        self.http_status = http_status
        super().__init__(f"{error_type}; HTTP status {http_status}")


def validate_model_policy(cfg: ModelConfig) -> None:
    """Development lock: only fake responses or explicitly free OpenRouter models."""
    if cfg.reasoning_enabled is not None and not isinstance(
        cfg.reasoning_enabled, bool
    ):
        raise ValueError("reasoning_enabled must be a boolean or unset")
    if cfg.reasoning_enabled is False and cfg.reasoning_max_tokens is not None:
        raise ValueError(
            "Do not combine disabled reasoning with a reasoning token budget"
        )
    if cfg.provider == "fake":
        return
    if cfg.provider != "openrouter" or not (
        (cfg.name.endswith(":free") and cfg.name != ":free")
        or cfg.name == "openrouter/free"
    ):
        raise ValueError(
            "Development model policy permits only OpenRouter :free models or openrouter/free"
        )


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _api_key(cfg: ModelConfig) -> str:
    if cfg.api_key:
        return cfg.api_key
    if cfg.api_key_env:
        return os.environ.get(cfg.api_key_env, "")
    env = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "openai_compatible": "OPENAI_API_KEY",
    }[cfg.provider]
    return os.environ.get(env, "")


def _client(cfg: ModelConfig) -> httpx.Client:
    if cfg.transport is not None:
        return httpx.Client(transport=cfg.transport, timeout=60.0)
    return httpx.Client(timeout=60.0)


def _request(messages: list[dict], cfg: ModelConfig) -> tuple[str, dict]:
    if cfg.provider == "anthropic":
        return _anthropic(messages, cfg)
    return _openai_compatible(messages, cfg)


def _anthropic(messages: list[dict], cfg: ModelConfig) -> tuple[str, dict]:
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    chat = [m for m in messages if m.get("role") != "system"]
    payload = {
        "model": cfg.name,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "messages": chat,
    }
    if system:
        payload["system"] = system
    with _client(cfg) as client:
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _api_key(cfg),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    parts = body.get("content") or []
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    usage = body.get("usage") or {}
    return text, {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
    }


def _openai_compatible(messages: list[dict], cfg: ModelConfig) -> tuple[str, dict]:
    if cfg.provider == "openrouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
    else:
        base = (cfg.base_url or "http://127.0.0.1:8000/v1").rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    payload = {
        "model": cfg.name,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "messages": messages,
    }
    if cfg.provider == "openrouter":
        reasoning = {}
        if cfg.reasoning_enabled is not None:
            reasoning["enabled"] = cfg.reasoning_enabled
        if cfg.reasoning_max_tokens is not None:
            reasoning["max_tokens"] = int(cfg.reasoning_max_tokens)
        if reasoning:
            payload["reasoning"] = reasoning
    if cfg.provider == "openrouter":
        payload["provider"] = {
            "allow_fallbacks": False,
            "max_price": {"prompt": 0, "completion": 0, "request": 0},
        }
    if cfg.provider == "openrouter" and cfg.output_kind == "painter":
        schema = copy.deepcopy(_PAINTER_SCHEMA)
        schema["properties"]["paints"]["maxItems"] = cfg.paint_budget
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "painter_action",
                "strict": False,
                "schema": schema,
            },
        }
    try:
        return _post_chat(url, payload, cfg)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400 and "response_format" in payload:
            payload.pop("response_format")
            return _post_chat(url, payload, cfg)
        raise


def _post_chat(url: str, payload: dict, cfg: ModelConfig) -> tuple[str, dict]:
    with _client(cfg) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {_api_key(cfg)}",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    text = _message_text(body["choices"][0]["message"])
    usage = body.get("usage") or {}
    return text, {
        "input": usage.get("prompt_tokens", 0),
        "output": usage.get("completion_tokens", 0),
        "served_model": body.get("model"),
        "provider": body.get("provider"),
        "response_id": body.get("id"),
        "cost": usage.get("cost"),
        "finish_reason": body["choices"][0].get("finish_reason"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        ),
        "has_visible_content": bool(
            _parts(body["choices"][0]["message"].get("content")).strip()
        ),
    }


def _message_text(message: dict) -> str:
    text = _parts(message.get("content"))
    if text.strip():
        return text
    reasoning = message.get("reasoning")
    if isinstance(reasoning, str) and "{" in reasoning:
        return reasoning
    return text


def _parts(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                chunks.append(str(part.get("text") or ""))
        return "".join(chunks)
    return ""
