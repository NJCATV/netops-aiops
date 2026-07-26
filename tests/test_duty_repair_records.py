import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.kb.duty_repair_records import (
    infer_actions,
    infer_canonical_symptom,
    infer_knowledge_value,
    infer_noise_reasons,
    parse_datetime,
)
from aiops.kb.formal_fault_records import iter_formal_fault_records, report_date_from_name, should_skip_report_file


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


def write_minimal_docx(path, paragraphs):
    def paragraph_xml(text):
        return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + "".join(paragraph_xml(item) for item in paragraphs)
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def test_generic_docx_manual_is_chunked_into_document_kb(tmp_path):
    docx_path = tmp_path / "南京分公司明厨亮灶项目运维常见问题及解决办法.docx"
    write_minimal_docx(
        docx_path,
        [
            "一、平台登录故障",
            "现象：明厨亮灶平台登录失败，提示账号或网络异常，门店侧浏览器无法稳定打开平台页面，值班人员需要先区分账号权限、专线网络、平台服务和本地缓存问题。",
            "处理：先检查专线连通性，再确认平台账号权限和浏览器缓存；如果多门店同时异常，应联系平台侧确认服务状态，并保留 traceroute、浏览器报错截图和门店编码。",
            "二、摄像头离线处理",
            "现象：门店摄像头离线或画面黑屏。",
            "处理：检查摄像头供电、交换机端口、专线链路和平台绑定关系。",
        ],
    )

    records = list(iter_formal_fault_records(tmp_path))

    assert records
    assert {item["source_type"] for item in records} == {"document_kb"}
    assert records[0]["report_file"] == docx_path.name
    assert records[0]["canonical_symptom"] == "general_knowledge"
    assert "平台登录故障" in records[0]["knowledge_title"]
    assert "明厨亮灶" in records[0]["embedding_text"]
