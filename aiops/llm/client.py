"""Unified OpenAI-compatible LLM client with internal-first fallback."""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Optional


LOGGER = logging.getLogger(__name__)

DEFAULT_INTERNAL_BASE_URL = "http://172.25.60.72:23000/v1"
DEFAULT_INTERNAL_MODEL = "deepseek-v4-pro"
DEFAULT_PUBLIC_BASE_URL = "https://api.deepseek.com"
DEFAULT_PUBLIC_MODEL = "deepseek-v4-pro"


@dataclass
class LLMProviderConfig:
    provider: str
    enabled: bool
    base_url: str
    model: str
    api_key: str
    timeout: int


@dataclass
class LLMCallResult:
    response: Any
    provider: str
    model: str
    base_url: str
    duration_ms: int


class LLMConfigError(RuntimeError):
    pass


class LLMCallError(RuntimeError):
    pass


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def pick_api_key(*names: str) -> str:
    values: list[str] = []
    for name in names:
        raw = os.getenv(name)
        if not raw:
            continue
        values.extend([item.strip() for item in raw.split(",") if item.strip()])
    return random.choice(values) if values else ""


def should_disable_thinking(config: LLMProviderConfig, messages: list[dict]) -> bool:
    mode = os.getenv(f"{config.provider.upper()}_LLM_THINKING") or os.getenv("LLM_THINKING")
    if mode:
        return str(mode).strip().lower() in {"0", "false", "no", "off", "disabled", "disable"}
    model_text = f"{config.base_url} {config.model}".lower()
    if "deepseek" not in model_text:
        return False
    for message in messages:
        if message.get("role") == "assistant" and message.get("tool_calls") and not message.get("reasoning_content"):
            return True
    return True


def flatten_tool_messages_for_fallback(messages: list[dict]) -> list[dict]:
    if not any(message.get("role") == "tool" for message in messages):
        return messages
    flattened: list[dict] = []
    tool_payloads: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            tool_payloads.append({"tool_call_id": str(message.get("tool_call_id") or ""), "content": str(message.get("content") or "")[:12000]})
            continue
        if role == "assistant" and message.get("tool_calls"):
            content = str(message.get("content") or "").strip()
            if content:
                flattened.append({"role": "assistant", "content": content})
            continue
        flattened.append({key: value for key, value in message.items() if key in {"role", "content", "name"}})
    if tool_payloads:
        flattened.append(
            {
                "role": "user",
                "content": "Provider fallback context: previous model already called tools. Use these tool results as evidence and return final JSON without requiring prior reasoning_content:\n"
                + "\n".join([f"tool_call_id={item['tool_call_id']} result={item['content']}" for item in tool_payloads]),
            }
        )
    return flattened


def sanitize_error(exc: Exception) -> str:
    text = str(exc)
    for key_name in ["INTERNAL_LLM_API_KEY", "INTERNAL_LLM_API_KEYS", "PUBLIC_LLM_API_KEY", "DEEPSEEK_API_KEY", "AI_API_KEY"]:
        key = os.getenv(key_name)
        if key:
            for part in key.split(","):
                part = part.strip()
                if part:
                    text = text.replace(part, "***")
    return text[:600]


def provider_configs(model: Optional[str] = None, timeout: Optional[int] = None) -> tuple[LLMProviderConfig, LLMProviderConfig]:
    internal_timeout = int(timeout or os.getenv("INTERNAL_LLM_TIMEOUT") or os.getenv("AI_REQUEST_TIMEOUT_SECONDS") or 30)
    public_timeout = int(timeout or os.getenv("PUBLIC_LLM_TIMEOUT") or os.getenv("AI_REQUEST_TIMEOUT_SECONDS") or 120)
    internal = LLMProviderConfig(
        provider="internal",
        enabled=env_bool("INTERNAL_LLM_ENABLED", False),
        base_url=first_env("INTERNAL_LLM_BASE_URL", default=DEFAULT_INTERNAL_BASE_URL),
        model=model or first_env("INTERNAL_LLM_MODEL", default=DEFAULT_INTERNAL_MODEL),
        api_key=pick_api_key("INTERNAL_LLM_API_KEYS", "INTERNAL_LLM_API_KEY"),
        timeout=internal_timeout,
    )
    public = LLMProviderConfig(
        provider="public",
        enabled=env_bool("PUBLIC_LLM_ENABLED", True),
        base_url=first_env("PUBLIC_LLM_BASE_URL", "DEEPSEEK_BASE_URL", "AI_API_BASE_URL", default=DEFAULT_PUBLIC_BASE_URL),
        model=model or first_env("PUBLIC_LLM_MODEL", "DEEPSEEK_MODEL", "AI_MODEL", default=DEFAULT_PUBLIC_MODEL),
        api_key=pick_api_key("PUBLIC_LLM_API_KEYS", "PUBLIC_LLM_API_KEY", "DEEPSEEK_API_KEY", "AI_API_KEY"),
        timeout=public_timeout,
    )
    return internal, public


def preferred_model(model: Optional[str] = None) -> str:
    if model and str(model).startswith(("llm_model:", "llm_models:", "llm_usage:")):
        try:
            from aiops.llm.registry import display_name_for_selector

            return display_name_for_selector(str(model))
        except Exception:
            return str(model)
    internal, public = provider_configs(model=model)
    if internal.enabled:
        return internal.model
    return public.model


def call_provider(config: LLMProviderConfig, messages: list[dict], *, temperature: float = 0.1, tools: Optional[list[dict]] = None, stream: bool = False, response_format: Optional[dict] = None) -> LLMCallResult:
    if not config.enabled:
        raise LLMConfigError(f"{config.provider}_llm_disabled")
    if not config.api_key:
        raise LLMConfigError(f"{config.provider}_llm_api_key_missing")
    from openai import OpenAI

    client = OpenAI(api_key=config.api_key, base_url=config.base_url, timeout=config.timeout)
    kwargs: dict[str, Any] = {"model": config.model, "messages": messages, "stream": stream, "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if response_format:
        kwargs["response_format"] = response_format
    start = time.monotonic()
    try:
        response = client.chat.completions.create(**kwargs)
    except TypeError:
        kwargs.pop("tools", None)
        kwargs.pop("tool_choice", None)
        kwargs.pop("response_format", None)
        response = client.chat.completions.create(**kwargs)
    duration_ms = int((time.monotonic() - start) * 1000)
    LOGGER.info("LLM call success: provider=%s model=%s duration_ms=%s", config.provider, config.model, duration_ms)
    return LLMCallResult(response=response, provider=config.provider, model=config.model, base_url=config.base_url, duration_ms=duration_ms)


def call_llm(messages: list[dict], *, model: Optional[str] = None, temperature: float = 0.1, timeout: Optional[int] = None, tools: Optional[list[dict]] = None, response_format: Optional[dict] = None) -> LLMCallResult:
    if model and str(model).startswith(("llm_model:", "llm_models:", "llm_usage:")):
        try:
            from aiops.llm.registry import configs_for_selector

            configs = configs_for_selector(str(model))
        except Exception as exc:
            configs = []
            LOGGER.warning("LLM registry selector failed: %s", sanitize_error(exc))
        errors: list[str] = []
        for index, config in enumerate(configs):
            if timeout:
                config.timeout = int(timeout)
            try:
                LOGGER.info("Registry LLM candidate: provider=%s model=%s base_url=%s", config.provider, config.model, config.base_url)
                candidate_messages = flatten_tool_messages_for_fallback(messages) if index > 0 and errors else messages
                return call_provider(config, candidate_messages, temperature=temperature, tools=tools, response_format=response_format)
            except Exception as exc:
                message = sanitize_error(exc)
                errors.append(f"{config.provider}/{config.model}: {message}")
                LOGGER.warning("Registry LLM candidate failed: provider=%s model=%s error=%s", config.provider, config.model, message)
        if configs:
            raise LLMCallError("; ".join(errors) or "registry_llm_candidates_failed")

    internal, public = provider_configs(model=model, timeout=timeout)
    errors: list[str] = []
    if internal.enabled:
        try:
            LOGGER.info("Internal LLM enabled: model=%s base_url=%s", internal.model, internal.base_url)
            return call_provider(internal, messages, temperature=temperature, tools=tools, response_format=response_format)
        except Exception as exc:
            message = sanitize_error(exc)
            errors.append(f"internal: {message}")
            LOGGER.warning("Internal LLM failed, fallback to public LLM: %s", message)
    if public.enabled:
        try:
            return call_provider(public, messages, temperature=temperature, tools=tools, response_format=response_format)
        except Exception as exc:
            message = sanitize_error(exc)
            errors.append(f"public: {message}")
            LOGGER.warning("Public LLM failed: %s", message)
    raise LLMCallError("; ".join(errors) or "no_llm_provider_available")


def check_internal_llm_available(timeout: int = 10) -> dict:
    internal, _ = provider_configs(timeout=timeout)
    if not internal.enabled:
        return {"ok": False, "provider": "internal", "error": "internal_llm_disabled"}
    start = time.monotonic()
    try:
        result = call_provider(
            internal,
            [{"role": "system", "content": "你只需要按要求简短回答。"}, {"role": "user", "content": "请回复 OK"}],
            temperature=0,
            tools=None,
        )
        content = getattr(result.response.choices[0].message, "content", "") or ""
        ok = bool(content.strip())
        return {"ok": ok, "provider": "internal", "model": result.model, "duration_ms": int((time.monotonic() - start) * 1000), "content_preview": content.strip()[:40]}
    except Exception as exc:
        return {"ok": False, "provider": "internal", "model": internal.model, "duration_ms": int((time.monotonic() - start) * 1000), "error": sanitize_error(exc)}
