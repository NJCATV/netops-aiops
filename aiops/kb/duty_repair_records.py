"""Parse and normalize duty repair Excel workbooks for fault KB ingestion."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional
from xml.etree import ElementTree as ET


CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
OOXML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

NOISE_REPORT_TYPES = {"查询/测试", "咨询"}
PROVINCE_REPORT_TYPES = {"省互动/直播问题", "省DHCP系统问题"}
IMPORTANT_REPORT_TYPES = {
    "机房设备问题",
    "接入网故障",
    "出口切换",
    "优化路由",
    "网络设备问题",
    "出口方解决",
    "换NAT地址",
    "计划内调整",
}
DISTRICTS = [
    "鼓楼",
    "秦淮",
    "河西新城",
    "河西",
    "奥体",
    "玄武",
    "江宁",
    "雨花",
    "六合",
    "浦口",
    "溧水",
    "高淳",
    "栖霞",
    "城东",
    "城南",
    "城北",
    "南京",
]


@dataclass(frozen=True)
class WorksheetInfo:
    name: str
    path: str


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u200c", "").replace("\u200b", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", clean_text(value)).lower()


def stable_id(parts: Iterable[Any]) -> str:
    payload = "|".join(clean_text(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def local_iso_date(value: dt.datetime) -> str:
    return value.astimezone(CHINA_TZ).date().isoformat()


def parse_excel_serial(value: str) -> Optional[dt.datetime]:
    text = clean_text(value)
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    number = float(text)
    if number < 20000 or number > 80000:
        return None
    base = dt.datetime(1899, 12, 30, tzinfo=CHINA_TZ)
    return base + dt.timedelta(days=number)


def parse_datetime(value: Any) -> Optional[dt.datetime]:
    text = clean_text(value)
    if not text:
        return None
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed_iso = dt.datetime.fromisoformat(iso_text)
        if parsed_iso.tzinfo is None:
            parsed_iso = parsed_iso.replace(tzinfo=CHINA_TZ)
        return parsed_iso
    except ValueError:
        pass
    parsed = parse_excel_serial(text)
    if parsed is not None:
        return parsed
    normalized = text.replace("年", "-").replace("月", "-").replace("日", " ")
    normalized = normalized.replace("/", "-").replace(".", "-")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m"):
        try:
            parsed = dt.datetime.strptime(normalized, fmt)
            return parsed.replace(tzinfo=CHINA_TZ)
        except ValueError:
            continue
    return None


def column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", (cell_ref or "").upper())
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return max(0, value - 1)


def shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    try:
        raw = zip_file.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    values: list[str] = []
    for item in root.findall("a:si", OOXML_NS):
        text = "".join(node.text or "" for node in item.findall(".//a:t", OOXML_NS))
        values.append(text)
    return values


def workbook_sheets(zip_file: zipfile.ZipFile) -> list[WorksheetInfo]:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    rel_by_id = {rel.attrib.get("Id"): rel.attrib.get("Target", "") for rel in rels.findall("rel:Relationship", OOXML_NS)}
    sheets: list[WorksheetInfo] = []
    for sheet in workbook.findall(".//a:sheet", OOXML_NS):
        name = clean_text(sheet.attrib.get("name"))
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_by_id.get(rel_id, "")
        if not name or not target:
            continue
        path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        sheets.append(WorksheetInfo(name=name, path=path))
    return sheets


def cell_text(cell: ET.Element, strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return clean_text("".join(node.text or "" for node in cell.findall(".//a:t", OOXML_NS)))
    value = cell.find("a:v", OOXML_NS)
    raw = "" if value is None else value.text or ""
    if cell_type == "s" and raw:
        try:
            return clean_text(strings[int(raw)])
        except (ValueError, IndexError):
            return ""
    return clean_text(raw)


def read_sheet_rows(zip_file: zipfile.ZipFile, sheet: WorksheetInfo, strings: list[str]) -> Iterator[tuple[int, list[str]]]:
    root = ET.fromstring(zip_file.read(sheet.path))
    for row in root.findall(".//a:sheetData/a:row", OOXML_NS):
        row_number = int(float(row.attrib.get("r", "0") or 0))
        cells: dict[int, str] = {}
        max_index = -1
        for cell in row.findall("a:c", OOXML_NS):
            index = column_index(cell.attrib.get("r", ""))
            max_index = max(max_index, index)
            cells[index] = cell_text(cell, strings)
        yield row_number, [cells.get(index, "") for index in range(max_index + 1)]


def unique_headers(raw_headers: list[str]) -> list[str]:
    counts: Counter[str] = Counter()
    headers: list[str] = []
    for index, header in enumerate(raw_headers):
        name = clean_text(header) or f"unnamed_{index + 1}"
        counts[name] += 1
        if counts[name] > 1:
            name = f"{name}_{counts[name]}"
        headers.append(name)
    return headers


def find_header(rows: list[tuple[int, list[str]]]) -> Optional[tuple[int, int, list[str]]]:
    for offset, (row_number, values) in enumerate(rows[:12]):
        compact = {clean_text(value) for value in values}
        if {"序号", "日期", "故障内容"}.issubset(compact):
            return offset, row_number, unique_headers(values)
    return None


def row_dict(headers: list[str], values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, header in enumerate(headers):
        if index < len(values):
            result[header] = clean_text(values[index])
    return result


def first_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def parse_bool_zh(value: str) -> Optional[bool]:
    text = clean_text(value)
    if text in {"是", "Y", "Yes", "yes", "true", "True", "1"}:
        return True
    if text in {"否", "N", "No", "no", "false", "False", "0"}:
        return False
    return None


def infer_service(fault_category: str, content: str, handling: str) -> str:
    text = compact_text(f"{fault_category} {content} {handling}")
    if "宽带" in text or "gdf" in text or "gdc" in text or "拨号" in text or "丢包" in text or "路由" in text:
        return "broadband"
    if "电视" in text or "机顶盒" in text or "回看" in text or "点播" in text or "频道" in text or "点8" in text:
        return "tv"
    if "政企" in text or "大客户" in text:
        return "enterprise"
    return "other"


def infer_area(content: str) -> str:
    for district in DISTRICTS:
        if district in content:
            return district
    return ""


def infer_canonical_symptom(content: str, handling: str, report_type: str) -> tuple[str, str]:
    text = compact_text(f"{content} {handling} {report_type}")
    if "环路" in text or "广播风暴" in text or "mac地址漂移" in text or "mac漂移" in text:
        return "access_loop_broadcast_storm", "接入环路/广播风暴"
    if "ipqam" in text or "频点" in text or "erm" in text or "0x0019" in text:
        return "ipqam_frequency_or_capacity", "IPQAM频点/容量异常"
    if "olt" in text and re.search(r"(策略|acl|地址段|vlan|配置)", text):
        return "olt_policy_or_vlan", "OLT策略/VLAN配置异常"
    has_dot8 = bool(re.search(r"(点\s*8|点八|(?<!\d)\.8(?!\d))", text))
    if has_dot8 and re.search(r"(卡顿|转圈|黑屏|定住|加载|不能看|打不开|失败|无响应)", text):
        return "dot8_stutter_or_failure", "点8卡顿/黑屏/加载异常"
    if "回看" in text and re.search(r"(黑屏|无声音|没声音|不能|无法|失败|未录制|卡|快进|后退|弹窗)", text):
        return "replay_fault", "回看异常"
    if "点播" in text and re.search(r"(黑屏|不能|无法|失败|卡)", text):
        return "vod_fault", "点播异常"
    if re.search(r"(开机|首页|初始化|launcher)", text) and re.search(r"(卡|死机|进不去|无法进入)", text):
        return "stb_boot_or_launcher_stuck", "机顶盒开机/首页卡死"
    if re.search(r"(出口|路由|nat|vpn|dns|tracert|googlemail)", text):
        return "broadband_routing_or_export", "宽带出口/路由异常"
    if re.search(r"(账号|gdf|gdc|拨号|多终端|在线|掉线记录|拨号记录)", text):
        return "account_dialing_query", "账号/拨号查询"
    if "丢包" in text:
        return "packet_loss_query", "丢包查询"
    if re.search(r"(片源|节目|频道|epg|广告)", text):
        return "content_or_epg_issue", "片源/频道/EPG问题"
    if re.search(r"(测速|上行|下行|带宽)", text):
        return "broadband_speed_issue", "宽带测速/带宽问题"
    if "产品订购" in text or "订购" in text:
        return "product_ordering_issue", "产品订购问题"
    return "unknown", "未归类"


def infer_actions(handling: str) -> list[str]:
    text = compact_text(handling)
    rules = [
        ("contact_province", r"省公司|安播|省互动|反馈省"),
        ("tested_normal", r"测试正常|监控室测试正常|监控大厅测试正常"),
        ("reboot_device", r"重启|断电"),
        ("replace_device", r"换机|更换机顶盒|调换"),
        ("factory_reset", r"恢复出厂|复位"),
        ("adjust_config", r"配置|放开|添加|调整|acl|vlan|频点"),
        ("switch_route_or_export", r"切至|切换|出口|路由|nat"),
        ("collect_trace_or_packet", r"tracert|抓包|截图"),
        ("field_dispatch", r"上门|社区工程师|机房|属地"),
        ("remote_shutdown", r"远程关闭|关闭onu"),
        ("followup_recovered", r"回访已好|处理已好|恢复正常|已好"),
    ]
    return [name for name, pattern in rules if re.search(pattern, text)]


def infer_noise_reasons(report_type: str, content: str, handling: str, canonical_symptom: str) -> list[str]:
    text = compact_text(f"{content} {handling}")
    reasons: list[str] = []
    if report_type in NOISE_REPORT_TYPES and re.search(r"(账号|gdf|gdc|在线|拨号|多终端|掉线记录|拨号记录|有无丢包|是否丢包|查.*丢包)", text):
        reasons.append("account_or_dialing_lookup")
    if report_type in NOISE_REPORT_TYPES and re.search(r"(测试正常|无丢包|无掉线|没有掉线|只有一个终端|不在线|查不到拨号记录|后台查看)", text):
        reasons.append("routine_backend_check")
    if report_type == "咨询" and canonical_symptom not in {"dot8_stutter_or_failure", "replay_fault", "vod_fault"}:
        reasons.append("general_consultation")
    if "是否在线" in text or "帮忙查" in text:
        reasons.append("operator_lookup_request")
    return sorted(set(reasons))


def infer_knowledge_value(
    report_type: str,
    province_support: Optional[bool],
    canonical_symptom: str,
    actions: list[str],
    noise_reasons: list[str],
    content: str,
    handling: str,
) -> tuple[str, float]:
    text = compact_text(f"{content} {handling}")
    important = (
        province_support is True
        or report_type in PROVINCE_REPORT_TYPES
        or report_type in IMPORTANT_REPORT_TYPES
        or canonical_symptom
        in {
            "dot8_stutter_or_failure",
            "replay_fault",
            "vod_fault",
            "ipqam_frequency_or_capacity",
            "olt_policy_or_vlan",
            "access_loop_broadcast_storm",
            "stb_boot_or_launcher_stuck",
            "broadband_routing_or_export",
        }
        or bool({"adjust_config", "switch_route_or_export", "remote_shutdown"} & set(actions))
    )
    if noise_reasons and not important:
        return "noise", 0.1
    if important and len(text) >= 40:
        return "reference", 0.85
    if canonical_symptom != "unknown":
        return "aggregate_only", 0.55
    return "low_value", 0.25


def embedding_text(record: dict[str, Any]) -> str:
    fields = [
        f"业务: {record.get('service')}",
        f"主题: {record.get('canonical_symptom_label')}",
        f"报修类型: {record.get('report_type')}",
        f"故障内容: {record.get('fault_content')}",
        f"处理情况: {record.get('handling_result')}",
        f"动作: {','.join(record.get('normalized_actions') or [])}",
    ]
    return "\n".join(item for item in fields if item and not item.endswith(": "))


def normalize_record(source_file: pathlib.Path, sheet_name: str, source_row: int, row: dict[str, str]) -> Optional[dict[str, Any]]:
    seq = first_value(row, "序号")
    occurred_raw = first_value(row, "日期")
    recovery_raw = first_value(row, "恢复时间")
    content = first_value(row, "故障内容")
    handling = first_value(row, "处理情况", "拨号错误 678 表示远程计算机无响应，即网络物理链路不通")
    if not content and not handling:
        return None
    fault_category = first_value(row, "故障分类")
    report_type = first_value(row, "报修类型", "EPG调整")
    fault_type = first_value(row, "故障类型")
    province_support_raw = first_value(row, "是否需要省公司协查")
    province_support = parse_bool_zh(province_support_raw)
    occurred_at = parse_datetime(occurred_raw)
    recovery_at = parse_datetime(recovery_raw)
    service = infer_service(fault_category, content, handling)
    canonical_symptom, canonical_label = infer_canonical_symptom(content, handling, report_type)
    actions = infer_actions(handling)
    noise_reasons = infer_noise_reasons(report_type, content, handling, canonical_symptom)
    knowledge_value, knowledge_score = infer_knowledge_value(
        report_type,
        province_support,
        canonical_symptom,
        actions,
        noise_reasons,
        content,
        handling,
    )
    area = infer_area(content)
    doc_id = stable_id([sheet_name, seq, occurred_raw, fault_category, report_type, fault_type, content, handling])
    event_time = occurred_at or dt.datetime.now(CHINA_TZ)
    handlers = [first_value(row, "后续处理人"), first_value(row, "后续处理人_2")]
    handlers = [handler for handler in handlers if handler]
    record: dict[str, Any] = {
        "record_id": doc_id,
        "source_type": "duty_repair_excel",
        "source_file": source_file.name,
        "source_path": str(source_file),
        "source_sheet": sheet_name,
        "source_row": source_row,
        "source_seq": seq,
        "@timestamp": iso_z(event_time),
        "occurred_date": local_iso_date(event_time),
        "occurred_time": iso_z(event_time),
        "occurred_raw": occurred_raw,
        "recovery_time": iso_z(recovery_at) if recovery_at else None,
        "recovery_raw": recovery_raw,
        "fault_category": fault_category,
        "report_type": report_type,
        "fault_type": fault_type,
        "service": service,
        "area": area,
        "fault_content": content,
        "handling_result": handling,
        "province_support_required": province_support,
        "province_support_raw": province_support_raw,
        "same_day_recovered": first_value(row, "当日是否恢复"),
        "discovered_raw": first_value(row, "发现时间"),
        "first_receiver": first_value(row, "第一接报人"),
        "followup_handlers": handlers,
        "remark": first_value(row, "备注", "1.14故障回溯追踪备注"),
        "canonical_symptom": canonical_symptom,
        "canonical_symptom_label": canonical_label,
        "normalized_actions": actions,
        "noise_reasons": noise_reasons,
        "knowledge_value": knowledge_value,
        "knowledge_score": knowledge_score,
        "aggregation_key": "|".join([service, canonical_symptom, area or "all"]),
        "embedding_candidate": knowledge_value in {"reference", "aggregate_only"},
        "embedding_status": "pending" if knowledge_value in {"reference", "aggregate_only"} else "not_needed",
        "raw_row": row,
    }
    record["embedding_text"] = embedding_text(record)
    return record


def iter_duty_repair_records(source_file: pathlib.Path, sheet_names: Optional[set[str]] = None) -> Iterator[dict[str, Any]]:
    with zipfile.ZipFile(source_file) as zip_file:
        strings = shared_strings(zip_file)
        for sheet in workbook_sheets(zip_file):
            if sheet_names and sheet.name not in sheet_names:
                continue
            rows = list(read_sheet_rows(zip_file, sheet, strings))
            header = find_header(rows)
            if not header:
                continue
            header_offset, _, headers = header
            for source_row, values in rows[header_offset + 1 :]:
                row = row_dict(headers, values)
                record = normalize_record(source_file, sheet.name, source_row, row)
                if record:
                    yield record


def index_date(record: dict[str, Any]) -> str:
    parsed = parse_datetime(record.get("occurred_time") or record.get("@timestamp"))
    if parsed is None:
        return dt.datetime.now(CHINA_TZ).strftime("%Y.%m")
    return parsed.astimezone(CHINA_TZ).strftime("%Y.%m")


def summarize_records(records: list[dict[str, Any]], sample_size: int = 5) -> dict[str, Any]:
    def top(field: str, limit: int = 20) -> list[dict[str, Any]]:
        counter = Counter(clean_text(item.get(field)) or "__missing__" for item in records)
        return [{"key": key, "count": count} for key, count in counter.most_common(limit)]

    noise_counter: Counter[str] = Counter()
    action_counter: Counter[str] = Counter()
    for record in records:
        noise_counter.update(record.get("noise_reasons") or [])
        action_counter.update(record.get("normalized_actions") or [])
    valuable = [item for item in records if item.get("knowledge_value") in {"reference", "aggregate_only"}]
    noise = [item for item in records if item.get("knowledge_value") == "noise"]
    return {
        "total_records": len(records),
        "embedding_candidates": sum(1 for item in records if item.get("embedding_candidate")),
        "top_knowledge_value": top("knowledge_value"),
        "top_service": top("service"),
        "top_report_type": top("report_type"),
        "top_canonical_symptom": top("canonical_symptom"),
        "top_aggregation_key": top("aggregation_key"),
        "top_noise_reasons": [{"key": key, "count": count} for key, count in noise_counter.most_common(20)],
        "top_actions": [{"key": key, "count": count} for key, count in action_counter.most_common(20)],
        "valuable_samples": valuable[:sample_size],
        "noise_samples": noise[:sample_size],
    }


def records_to_json(records: list[dict[str, Any]]) -> str:
    return json.dumps({"records": records, "summary": summarize_records(records)}, ensure_ascii=False, indent=2, default=str)
