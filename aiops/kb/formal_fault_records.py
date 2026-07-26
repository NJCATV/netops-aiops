"""Parse formal fault ledgers and investigation reports for KB ingestion."""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import zipfile
from collections import Counter
from typing import Any, Iterable, Iterator, Optional
from xml.etree import ElementTree as ET

from aiops.kb.duty_repair_records import (
    CHINA_TZ,
    OOXML_NS,
    clean_text,
    compact_text,
    embedding_text,
    find_header,
    infer_actions,
    infer_area,
    infer_canonical_symptom,
    infer_knowledge_value,
    infer_noise_reasons,
    infer_service,
    iso_z,
    local_iso_date,
    parse_datetime,
    read_sheet_rows,
    row_dict,
    shared_strings,
    stable_id,
    unique_headers,
    workbook_sheets,
)


SECTION_NAMES = ["故障现象", "影响范围", "故障原因", "排查步骤", "修复方式", "处理结果", "预防措施", "防范措施"]
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
SKIP_REPORT_NAME_KEYWORDS = ("模板", "模版", "template")
GENERIC_DOC_CHUNK_SIZE = 1800
GENERIC_DOC_MIN_CHARS = 120
GENERIC_TABLE_MIN_CHARS = 30


def paragraph_text(paragraph: ET.Element) -> str:
    return clean_text("".join(node.text or "" for node in paragraph.findall(".//w:t", WORD_NS)))


def table_row_text(row: ET.Element) -> str:
    cells: list[str] = []
    for cell in row.findall("w:tc", WORD_NS):
        cell_text = clean_text(" ".join(paragraph_text(paragraph) for paragraph in cell.findall(".//w:p", WORD_NS)))
        if cell_text:
            cells.append(cell_text)
    return " | ".join(cells)


def read_docx_blocks(path: pathlib.Path) -> list[str]:
    if path.name.startswith(".~"):
        return []
    try:
        with zipfile.ZipFile(path) as zip_file:
            raw = zip_file.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        return []
    root = ET.fromstring(raw)
    body = root.find("w:body", WORD_NS)
    if body is None:
        return []
    blocks: list[str] = []
    for child in list(body):
        if child.tag == f"{{{WORD_NS['w']}}}p":
            text = paragraph_text(child)
            if text:
                blocks.append(text)
        elif child.tag == f"{{{WORD_NS['w']}}}tbl":
            for row in child.findall(".//w:tr", WORD_NS):
                text = clean_text(table_row_text(row))
                if text:
                    blocks.append(text)
    return blocks


def read_docx_text(path: pathlib.Path) -> str:
    return "\n".join(read_docx_blocks(path))


def split_sections(text: str) -> dict[str, str]:
    compact = clean_text(text)
    if not compact:
        return {}
    pattern = r"(?:^|[。；;\n ])(?:[一二三四五六七八九十]+、)?(%s)" % "|".join(map(re.escape, SECTION_NAMES))
    matches = list(re.finditer(pattern, compact))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compact)
        value = compact[start:end].strip(" ：:。；;\n")
        if value:
            sections[name] = value
    return sections


def report_date_from_name(path: pathlib.Path) -> str:
    match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", path.name)
    if not match:
        return ""
    year, month, day = (int(item) for item in match.groups())
    return dt.date(year, month, day).isoformat()


def report_title_from_name(path: pathlib.Path) -> str:
    title = re.sub(r"^20\d{2}年\d{1,2}月\d{1,2}日", "", path.stem)
    title = re.sub(r"^南京分公司", "", title)
    title = title.replace("故障排查报告", "").strip(" -_")
    return clean_text(title)


def should_skip_report_file(path: pathlib.Path) -> bool:
    name = clean_text(path.name).lower()
    return path.name.startswith(".~") or any(keyword in name for keyword in SKIP_REPORT_NAME_KEYWORDS)


def iter_paths(root: pathlib.Path, suffixes: Iterable[str]) -> Iterator[pathlib.Path]:
    suffix_set = {suffix.lower() for suffix in suffixes}
    if root.is_file():
        if root.suffix.lower() in suffix_set:
            yield root
        return
    yield from sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffix_set)


def load_reports(root: pathlib.Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for path in iter_paths(root, {".docx"}):
        if should_skip_report_file(path):
            continue
        date = report_date_from_name(path)
        if not date:
            continue
        text = read_docx_text(path)
        if not text:
            continue
        title = report_title_from_name(path)
        sections = split_sections(text)
        reports[date] = {
            "report_file": path.name,
            "report_path": str(path),
            "report_date": date,
            "report_title": title,
            "report_text": text,
            "report_sections": sections,
        }
    return reports


def looks_like_heading(text: str) -> bool:
    value = clean_text(text)
    if not value or len(value) > 80:
        return False
    if re.match(r"^(?:第[一二三四五六七八九十\d]+[章节]|[一二三四五六七八九十]+[、.．]\s*|\d+(?:\.\d+)+\s*)", value):
        return True
    return bool(re.search(r"(问题|故障|处理|解决|排查|配置|维护|操作|使用|开通|割接|告警|错误码|备份|查看|统计|信息|路径|流量|带宽|扩容|下发|FAQ|Q&A)$", value, re.IGNORECASE))


def is_low_value_document_chunk(title: str, text: str) -> bool:
    compact = clean_text(f"{title} {text}")
    if not compact:
        return True
    if "修订记录" in compact and ("编制单位" in compact or "版本" in compact):
        return True
    if re.fullmatch(r"(目\s*录|目录)", compact):
        return True
    return False


def generic_doc_chunks(blocks: list[str], max_chars: int = GENERIC_DOC_CHUNK_SIZE) -> Iterator[tuple[str, str]]:
    title = ""
    current: list[str] = []

    def flush() -> tuple[str, str] | None:
        if not current:
            return None
        text = clean_text("\n".join(current))
        if len(text) < GENERIC_DOC_MIN_CHARS:
            return None
        return title, text

    for block in blocks:
        if looks_like_heading(block):
            item = flush()
            if item:
                yield item
            title = block
            current = [block]
            continue
        if sum(len(item) for item in current) + len(block) > max_chars:
            item = flush()
            if item:
                yield item
            current = [title, block] if title else [block]
        else:
            current.append(block)
    item = flush()
    if item:
        yield item


def document_embedding_text(record: dict[str, Any]) -> str:
    fields = [
        f"知识类型: {record.get('knowledge_kind')}",
        f"来源文件: {record.get('source_file')}",
        f"标题: {record.get('knowledge_title') or record.get('title')}",
        f"内容: {record.get('knowledge_content') or record.get('fault_content')}",
    ]
    return "\n".join(item for item in fields if item and not item.endswith(": "))


def iter_generic_doc_records(root: pathlib.Path) -> Iterator[dict[str, Any]]:
    for path in iter_paths(root, {".docx"}):
        if should_skip_report_file(path) or report_date_from_name(path):
            continue
        blocks = read_docx_blocks(path)
        if not blocks:
            continue
        modified_at = dt.datetime.fromtimestamp(path.stat().st_mtime, CHINA_TZ)
        for index, (chunk_title, chunk_text) in enumerate(generic_doc_chunks(blocks), start=1):
            title = clean_text(chunk_title) or path.stem
            if is_low_value_document_chunk(title, chunk_text):
                continue
            combined = f"{path.stem}\n{title}\n{chunk_text}"
            service = infer_service("", combined, chunk_text)
            area = infer_area(combined)
            record_id = stable_id(["document_kb", str(path), index, title, chunk_text])
            record = {
                "record_id": record_id,
                "source_type": "document_kb",
                "knowledge_kind": "document",
                "knowledge_title": title,
                "knowledge_content": chunk_text,
                "source_file": path.name,
                "source_path": str(path),
                "source_sheet": "docx_chunk",
                "source_row": index,
                "@timestamp": iso_z(modified_at),
                "occurred_date": local_iso_date(modified_at),
                "occurred_time": iso_z(modified_at),
                "title": title,
                "fault_content": chunk_text,
                "impact_scope": "",
                "root_cause": "",
                "investigation_steps": "",
                "fix_method": "",
                "prevention": "",
                "service": service,
                "area": area,
                "canonical_symptom": "general_knowledge",
                "canonical_symptom_label": "通用知识",
                "normalized_actions": [],
                "noise_reasons": [],
                "knowledge_value": "reference",
                "knowledge_score": 0.8,
                "aggregation_key": "|".join([service, "general_knowledge", area or "all"]),
                "embedding_candidate": True,
                "embedding_status": "pending",
                "report_file": path.name,
                "report_path": str(path),
                "report_text": chunk_text,
                "raw_row": {"chunk_index": index, "document_title": path.stem, "chunk_title": title},
            }
            record["embedding_text"] = document_embedding_text(record)
            yield record


def first_row_title(row: dict[str, str], fallback: str) -> str:
    preferred = [name for name in row if re.search(r"(错误|代码|问题|故障|名称|标题|现象)", name)]
    for name in preferred + list(row):
        value = clean_text(row.get(name))
        if value:
            return value[:80]
    return fallback


def generic_xlsx_header(rows: list[tuple[int, list[str]]]) -> Optional[tuple[int, list[str]]]:
    for offset, (_, values) in enumerate(rows[:10]):
        non_empty = [clean_text(value) for value in values if clean_text(value)]
        if len(non_empty) >= 2:
            return offset, unique_headers(values)
    return None


def iter_generic_xlsx_records(root: pathlib.Path) -> Iterator[dict[str, Any]]:
    for path in iter_paths(root, {".xlsx"}):
        if "故障台账" in path.name or "故障汇总" in path.name:
            continue
        try:
            zip_file = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            continue
        with zip_file:
            strings = shared_strings(zip_file)
            modified_at = dt.datetime.fromtimestamp(path.stat().st_mtime, CHINA_TZ)
            for sheet in workbook_sheets(zip_file):
                rows = list(read_sheet_rows(zip_file, sheet, strings))
                header = generic_xlsx_header(rows)
                if not header:
                    continue
                header_offset, headers = header
                for source_row, values in rows[header_offset + 1 :]:
                    row = row_dict(headers, values)
                    pairs = [(key, clean_text(value)) for key, value in row.items() if clean_text(value)]
                    if len(pairs) < 2:
                        continue
                    row_text = "；".join(f"{key}: {value}" for key, value in pairs)
                    if len(row_text) < GENERIC_TABLE_MIN_CHARS:
                        continue
                    title = first_row_title(row, f"{path.stem} {sheet.name} 第{source_row}行")
                    combined = f"{path.stem}\n{sheet.name}\n{title}\n{row_text}"
                    service = infer_service("", combined, row_text)
                    area = infer_area(combined)
                    record_id = stable_id(["document_kb_xlsx", str(path), sheet.name, source_row, row_text])
                    record = {
                        "record_id": record_id,
                        "source_type": "document_kb",
                        "knowledge_kind": "table_row",
                        "knowledge_title": title,
                        "knowledge_content": row_text,
                        "source_file": path.name,
                        "source_path": str(path),
                        "source_sheet": sheet.name,
                        "source_row": source_row,
                        "@timestamp": iso_z(modified_at),
                        "occurred_date": local_iso_date(modified_at),
                        "occurred_time": iso_z(modified_at),
                        "title": title,
                        "fault_content": row_text,
                        "impact_scope": "",
                        "root_cause": "",
                        "investigation_steps": "",
                        "fix_method": "",
                        "prevention": "",
                        "service": service,
                        "area": area,
                        "canonical_symptom": "general_knowledge",
                        "canonical_symptom_label": "通用知识",
                        "normalized_actions": [],
                        "noise_reasons": [],
                        "knowledge_value": "reference",
                        "knowledge_score": 0.8,
                        "aggregation_key": "|".join([service, "general_knowledge", area or "all"]),
                        "embedding_candidate": True,
                        "embedding_status": "pending",
                        "report_file": path.name,
                        "report_path": str(path),
                        "report_text": row_text,
                        "raw_row": row,
                    }
                    record["embedding_text"] = document_embedding_text(record)
                    yield record


def iter_ledger_rows(path: pathlib.Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as zip_file:
        strings = shared_strings(zip_file)
        for sheet in workbook_sheets(zip_file):
            rows = list(read_sheet_rows(zip_file, sheet, strings))
            header = find_header(rows)
            if header:
                header_offset, _, headers = header
            else:
                header_offset = -1
                headers = []
                for offset, (_, values) in enumerate(rows[:12]):
                    compact = {clean_text(value) for value in values}
                    if "序号" in compact and "日期" in compact and ("故障现象" in compact or "故障原因" in compact):
                        from aiops.kb.duty_repair_records import unique_headers

                        header_offset = offset
                        headers = unique_headers(values)
                        break
                if header_offset < 0:
                    continue
            for source_row, values in rows[header_offset + 1 :]:
                row = row_dict(headers, values)
                if row.get("故障内容") or row.get("故障现象"):
                    row["_source_sheet"] = sheet.name
                    row["_source_row"] = str(source_row)
                    yield row


def row_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def record_embedding_text(record: dict[str, Any]) -> str:
    fields = [
        f"业务: {record.get('service')}",
        f"主题: {record.get('canonical_symptom_label')}",
        f"故障标题: {record.get('title')}",
        f"故障现象: {record.get('fault_content')}",
        f"影响范围: {record.get('impact_scope')}",
        f"故障原因: {record.get('root_cause')}",
        f"排查步骤: {record.get('investigation_steps')}",
        f"修复方式: {record.get('fix_method')}",
        f"预防措施: {record.get('prevention')}",
    ]
    return "\n".join(item for item in fields if item and not item.endswith(": "))


def normalize_formal_record(source_file: pathlib.Path, row: dict[str, str], report: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    date_raw = row_value(row, "日期")
    occurred_at = parse_datetime(date_raw)
    if occurred_at is None:
        occurred_at = dt.datetime.now(CHINA_TZ)
    report_sections = (report or {}).get("report_sections") or {}
    title = (report or {}).get("report_title") or row_value(row, "故障标题")
    fault_content = row_value(row, "故障现象", "故障内容") or report_sections.get("故障现象", "")
    impact_scope = row_value(row, "影响范围") or report_sections.get("影响范围", "")
    root_cause = row_value(row, "故障原因") or report_sections.get("故障原因", "")
    investigation_steps = row_value(row, "排查步骤") or report_sections.get("排查步骤", "")
    fix_method = row_value(row, "修复方式", "处理结果") or report_sections.get("修复方式", "") or report_sections.get("处理结果", "")
    prevention = row_value(row, "预防措施") or report_sections.get("预防措施", "") or report_sections.get("防范措施", "")
    combined = "\n".join([title, fault_content, impact_scope, root_cause, investigation_steps, fix_method, prevention])
    if not clean_text(combined):
        return None
    service = infer_service(row_value(row, "故障分类"), combined, fix_method)
    canonical_symptom, canonical_label = infer_canonical_symptom(combined, fix_method, row_value(row, "报修类型"))
    actions = infer_actions(f"{investigation_steps} {fix_method} {prevention}")
    noise_reasons = infer_noise_reasons("", combined, fix_method, canonical_symptom)
    knowledge_value, knowledge_score = infer_knowledge_value(
        "正式故障报告",
        True,
        canonical_symptom,
        actions,
        noise_reasons,
        combined,
        fix_method,
    )
    area = infer_area(combined)
    record_id = stable_id(["formal_fault", source_file.name, row.get("_source_sheet"), row.get("_source_row"), date_raw, combined])
    record: dict[str, Any] = {
        "record_id": record_id,
        "source_type": "formal_fault_report",
        "source_file": source_file.name,
        "source_path": str(source_file),
        "source_sheet": row.get("_source_sheet"),
        "source_row": int(row.get("_source_row") or 0),
        "@timestamp": iso_z(occurred_at),
        "occurred_date": local_iso_date(occurred_at),
        "occurred_time": iso_z(occurred_at),
        "occurred_raw": date_raw,
        "title": title,
        "fault_content": fault_content,
        "impact_scope": impact_scope,
        "root_cause": root_cause,
        "investigation_steps": investigation_steps,
        "fix_method": fix_method,
        "prevention": prevention,
        "service": service,
        "area": area,
        "canonical_symptom": canonical_symptom,
        "canonical_symptom_label": canonical_label,
        "normalized_actions": actions,
        "noise_reasons": noise_reasons,
        "knowledge_value": "reference" if knowledge_value != "noise" else "aggregate_only",
        "knowledge_score": max(knowledge_score, 0.9),
        "aggregation_key": "|".join([service, canonical_symptom, area or "all"]),
        "embedding_candidate": True,
        "embedding_status": "pending",
        "raw_row": row,
    }
    if report:
        record.update(
            {
                "report_file": report.get("report_file"),
                "report_path": report.get("report_path"),
                "report_text": report.get("report_text"),
                "report_sections": report_sections,
            }
        )
    record["embedding_text"] = record_embedding_text(record)
    return record


def iter_formal_fault_records(root: pathlib.Path) -> Iterator[dict[str, Any]]:
    reports = load_reports(root)
    ledger_paths = [path for path in iter_paths(root, {".xlsx"}) if "故障台账" in path.name or "故障汇总" in path.name]
    matched_dates: set[str] = set()
    for ledger_path in ledger_paths:
        for row in iter_ledger_rows(ledger_path):
            occurred_at = parse_datetime(row_value(row, "日期"))
            date_key = occurred_at.date().isoformat() if occurred_at else ""
            report = reports.get(date_key)
            if report:
                matched_dates.add(date_key)
            record = normalize_formal_record(ledger_path, row, report)
            if record:
                yield record
    for date_key, report in reports.items():
        if date_key in matched_dates:
            continue
        fake_row = {
            "日期": date_key,
            "故障内容": report.get("report_sections", {}).get("故障现象", ""),
            "影响范围": report.get("report_sections", {}).get("影响范围", ""),
            "故障原因": report.get("report_sections", {}).get("故障原因", ""),
            "排查步骤": report.get("report_sections", {}).get("排查步骤", ""),
            "修复方式": report.get("report_sections", {}).get("修复方式", "") or report.get("report_sections", {}).get("处理结果", ""),
            "预防措施": report.get("report_sections", {}).get("预防措施", "") or report.get("report_sections", {}).get("防范措施", ""),
            "_source_sheet": "docx_only",
            "_source_row": "0",
        }
        record = normalize_formal_record(pathlib.Path(report["report_path"]), fake_row, report)
        if record:
            yield record
    yield from iter_generic_doc_records(root)
    yield from iter_generic_xlsx_records(root)


def index_date(record: dict[str, Any]) -> str:
    parsed = parse_datetime(record.get("occurred_time") or record.get("@timestamp"))
    if parsed is None:
        return dt.datetime.now(CHINA_TZ).strftime("%Y.%m")
    return parsed.astimezone(CHINA_TZ).strftime("%Y.%m")


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    def top(field: str, limit: int = 20) -> list[dict[str, Any]]:
        counter = Counter(clean_text(item.get(field)) or "__missing__" for item in records)
        return [{"key": key, "count": count} for key, count in counter.most_common(limit)]

    return {
        "total_records": len(records),
        "embedding_candidates": sum(1 for item in records if item.get("embedding_candidate")),
        "top_service": top("service"),
        "top_canonical_symptom": top("canonical_symptom"),
        "top_aggregation_key": top("aggregation_key"),
        "source_files": top("source_file", 50),
        "report_files": top("report_file", 50),
        "samples": records[:10],
    }
