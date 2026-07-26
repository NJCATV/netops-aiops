import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.agent.light_agent import (
    append_standard_tool_messages,
    assistant_reasoning_content,
    call_chat,
)


def test_assistant_reasoning_content_reads_model_extra():
    message = SimpleNamespace(content="", model_extra={"reasoning_content": "hidden reasoning"})

    assert assistant_reasoning_content(message) == "hidden reasoning"


def test_append_standard_tool_messages_preserves_reasoning_content_from_model_extra():
    function = SimpleNamespace(name="investigate_candidates", arguments="{}")
    tool_call = SimpleNamespace(id="call-1", function=function)
    assistant = SimpleNamespace(
        content="",
        tool_calls=[tool_call],
        model_extra={"reasoning_content": "hidden reasoning"},
    )
    messages = []

    append_standard_tool_messages(messages, assistant, [(tool_call, {"ok": True})])

    assert messages[0]["reasoning_content"] == "hidden reasoning"
    assert messages[0]["tool_calls"][0]["function"]["name"] == "investigate_candidates"
    assert messages[1]["role"] == "tool"


def test_call_chat_lets_provider_specific_timeout_win(monkeypatch):
    captured = {}

    def fake_call_llm(messages, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]),
            provider="internal",
            model="deepseek-v4-pro",
            duration_ms=1,
        )

    monkeypatch.setenv("INTERNAL_LLM_TIMEOUT", "30")
    monkeypatch.setattr("aiops.agent.light_agent.call_llm", fake_call_llm)

    call_chat([], "deepseek-v4-pro", "", "", 180, 0.1, None)

    assert captured["timeout"] is None
