import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.agent.light_agent import api_config
from aiops.agent.light_agent import assistant_reasoning_content, truncate_tool_result


def test_api_config_keeps_registry_selector_for_llm_call(monkeypatch):
    monkeypatch.setattr(
        "aiops.agent.light_agent.preferred_model",
        lambda model: "deepseek-v4-pro-tencent -> deepseek-v4-pro",
    )

    _api_key, _base_url, call_model, display_model, _timeout = api_config("llm_usage:aiops_manual_analysis")

    assert call_model == "llm_usage:aiops_manual_analysis"
    assert display_model == "deepseek-v4-pro-tencent -> deepseek-v4-pro"


def test_api_config_uses_plain_model_for_display_and_call(monkeypatch):
    monkeypatch.setattr("aiops.agent.light_agent.preferred_model", lambda model: model)

    _api_key, _base_url, call_model, display_model, _timeout = api_config("deepseek-v4-pro")

    assert call_model == "deepseek-v4-pro"
    assert display_model == "deepseek-v4-pro"


def test_truncate_tool_result_compacts_large_investigations():
    large_text = "x" * 6000
    result = {
        "ok": True,
        "tool_name": "investigate_candidates",
        "result": {
            "metadata": {"window": large_text},
            "investigations": [
                {
                    "candidate_type": "critical_alarm_candidates",
                    "candidate": {"device_name": "D1", "event_summary": large_text},
                    "identity": {"device_name": "D1", "device_identity_source": "device_name_lookup"},
                    "related_current_events": [{"event_summary": large_text, "event_count": 5}],
                    "related_alarm_events": [{"event_summary": large_text, "event_count": 2}],
                    "related_traps": [{"alarm_name": "Trap", "managed_object_name": large_text}],
                }
            ],
        },
    }

    compact = truncate_tool_result(result)

    assert compact["truncated"] is True
    assert len(str(compact)) < 12000
    assert compact["result"]["investigations"][0]["candidate"]["device_name"] == "D1"


def test_assistant_reasoning_content_reads_model_extra():
    class Message:
        model_extra = {"reasoning_content": "hidden reasoning"}

    assert assistant_reasoning_content(Message()) == "hidden reasoning"
