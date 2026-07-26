import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.rules.analysis_rules import parse_ai_rule


@pytest.mark.parametrize(
    ("raw_text", "rule_type", "action"),
    [
        ("RADIUS所有信息都不管，忽视", "noise_reduction", "downgrade_or_suppress"),
        ("radius故障不用管", "noise_reduction", "downgrade_or_suppress"),
        ("RADIUS认证失败不关注", "noise_reduction", "downgrade_or_suppress"),
        ("必须关注RADIUS故障", "attention", "boost_priority"),
        ("不能忽略RADIUS故障", "attention", "boost_priority"),
        ("光模块故障必须关注", "attention", "boost_priority"),
        ("伪造模块告警忽略", "noise_reduction", "downgrade_or_suppress"),
        ("PPP认证失败超过100次才关注", "threshold", "threshold_control"),
    ],
)
def test_parse_ai_rule_intent(monkeypatch, raw_text, rule_type, action):
    monkeypatch.setenv("AI_RULE_LLM_ENABLED", "false")
    parsed = parse_ai_rule(raw_text)
    assert parsed["rule_type"] == rule_type
    assert parsed["action"] == action


def test_radius_noise_rule_has_safety_exceptions(monkeypatch):
    monkeypatch.setenv("AI_RULE_LLM_ENABLED", "false")
    parsed = parse_ai_rule("RADIUS所有信息都不管，忽视")
    assert parsed["safety_exceptions"]
    assert "RADIUS_ACCOUNTING_FAILURE" in parsed["target_event_families"]
    assert "RADIUS_AUTH_FAILURE" in parsed["target_event_families"]
    assert "RADIUS_SERVER_ABNORMAL" in parsed["target_event_families"]


def test_ppp_threshold(monkeypatch):
    monkeypatch.setenv("AI_RULE_LLM_ENABLED", "false")
    parsed = parse_ai_rule("PPP认证失败超过100次才关注")
    assert parsed["threshold_count"] == 100
    assert "PPP_AUTH_FAILURE" in parsed["target_event_families"]
