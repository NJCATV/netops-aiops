import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.llm.client import LLMProviderConfig, flatten_tool_messages_for_fallback, should_disable_thinking


def public_config(base_url="https://api.deepseek.com", model="deepseek-v4-pro"):
    return LLMProviderConfig(
        provider="public",
        enabled=True,
        base_url=base_url,
        model=model,
        api_key="test",
        timeout=30,
    )


def test_deepseek_model_disables_thinking_by_default(monkeypatch):
    monkeypatch.delenv("INTERNAL_LLM_THINKING", raising=False)
    config = LLMProviderConfig(
        provider="internal",
        enabled=True,
        base_url="http://172.25.60.72:23000/v1",
        model="deepseek-v4-pro",
        api_key="test",
        timeout=30,
    )

    assert should_disable_thinking(config, [{"role": "user", "content": "hello"}]) is True


def test_public_deepseek_disables_thinking_when_tool_reasoning_is_missing(monkeypatch):
    monkeypatch.delenv("PUBLIC_LLM_THINKING", raising=False)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
    ]

    assert should_disable_thinking(public_config(), messages) is True


def test_public_thinking_can_be_forced_enabled(monkeypatch):
    monkeypatch.setenv("PUBLIC_LLM_THINKING", "enabled")
    messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]}]

    assert should_disable_thinking(public_config(), messages) is False


def test_public_non_deepseek_does_not_auto_disable(monkeypatch):
    monkeypatch.delenv("PUBLIC_LLM_THINKING", raising=False)
    messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]}]

    assert should_disable_thinking(public_config("https://example.invalid/v1", model="qwen2.5-32b"), messages) is False


def test_flatten_tool_messages_for_provider_fallback():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "input"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true}'},
    ]

    flattened = flatten_tool_messages_for_fallback(messages)

    assert all(item["role"] != "tool" for item in flattened)
    assert all("tool_calls" not in item for item in flattened)
    assert "previous model already called tools" in flattened[-1]["content"]
