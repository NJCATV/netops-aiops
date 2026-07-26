import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.kb.duty_repair_records import (
    infer_actions,
    infer_canonical_symptom,
    infer_knowledge_value,
    infer_noise_reasons,
    parse_datetime,
)
from aiops.kb.formal_fault_records import report_date_from_name, should_skip_report_file


def classify(content, handling="", report_type="查询/测试", province_support=None):
    symptom, _ = infer_canonical_symptom(content, handling, report_type)
    actions = infer_actions(handling)
    noise = infer_noise_reasons(report_type, content, handling, symptom)
    value, _ = infer_knowledge_value(report_type, province_support, symptom, actions, noise, content, handling)
    return symptom, actions, noise, value


def test_dot8_is_not_matched_inside_ip_address():
    symptom, actions, noise, value = classify("10.30.22.81访问慢", "切至丹凤街出口后恢复")
    assert symptom == "broadband_routing_or_export"
    assert "switch_route_or_export" in actions
    assert value == "aggregate_only"


def test_dot8_stutter_is_grouped():
    symptom, actions, noise, value = classify("点8里电视剧卡顿", "换机后恢复", "用户终端故障")
    assert symptom == "dot8_stutter_or_failure"
    assert "replace_device" in actions
    assert value in {"aggregate_only", "reference"}


def test_account_lookup_is_noise():
    symptom, actions, noise, value = classify("GDF2246269账号是否在线有无丢包", "在线，不丢包")
    assert symptom == "account_dialing_query"
    assert "account_or_dialing_lookup" in noise
    assert "routine_backend_check" in noise
    assert value == "noise"


def test_excel_serial_date_is_china_timezone():
    parsed = parse_datetime("46174")
    assert parsed is not None
    assert parsed.date().isoformat() == "2026-06-01"
    assert parsed.utcoffset().total_seconds() == 8 * 3600


def test_formal_report_template_is_skipped():
    assert should_skip_report_file(pathlib.Path("故障排查报告（模版）(2).docx"))
    assert not should_skip_report_file(pathlib.Path("2026年6月1日DVB机顶盒回看黑屏故障排查报告.docx"))
    assert report_date_from_name(pathlib.Path("2026年6月1日DVB机顶盒回看黑屏故障排查报告.docx")) == "2026-06-01"
