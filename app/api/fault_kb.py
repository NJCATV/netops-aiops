"""Fault knowledge-base query, import, and Q&A APIs."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from typing import Any, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import desc, func, select
from werkzeug.utils import secure_filename

from aiops.llm.client import call_llm, sanitize_error
from aiops.tools.ai_tools import search_fault_kb
from app.api.auth import admin_required, db_session_factory, login_required
from app.db import session_scope
from app.models import AiChatMessage, AiChatSession, User, utc_now


fault_kb_bp = Blueprint("fault_kb", __name__, url_prefix="/api/fault-kb")

DUTY_INDEX_PREFIX = "jscn-aiops-duty-repair-records"
FORMAL_INDEX_PREFIX = "jscn-aiops-fault-kb"
TOPIC_INDEX = "jscn-aiops-fault-topic-aggregates"


def es_url() -> str:
    return os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200").rstrip("/")


def es_request(method: str, path: str, body: Optional[dict] = None, ndjson: Optional[str] = None) -> dict:
    if ndjson is not None:
        data = ndjson.encode("utf-8")
        headers = {"Content-Type": "application/x-ndjson"}
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        data = None
        headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(es_url() + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    return json.loads(payload) if payload else {}


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def bool_param(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def compact_text(value: Any, max_length: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_length] + ("..." if len(text) > max_length else "")


def term_filter(field: str, value: Any) -> Optional[dict]:
    text = str(value or "").strip()
    return {"term": {field: text}} if text else None


def query_text_filter(query_text: str, fields: list[str]) -> Optional[dict]:
    text = str(query_text or "").strip()
    if not text:
        return None
    return {"multi_match": {"query": text, "fields": fields, "type": "best_fields"}}


def compact_knowledge_content(row: dict, max_length: int = 700) -> str:
    return compact_text(row.get("knowledge_content") or row.get("fault_content") or row.get("report_text"), max_length)


def search_with_total(index: str, query: dict, limit: int, offset: int, sort: list[dict], source: list[str]) -> tuple[list[dict], int]:
    body = {"from": offset, "size": limit, "track_total_hits": True, "query": query, "sort": sort, "_source": source}
    response = es_request("POST", f"/{index}/_search", body)
    hits = response.get("hits", {})
    total_raw = hits.get("total", 0)
    total = int(total_raw.get("value", 0) if isinstance(total_raw, dict) else total_raw)
    items = []
    for hit in hits.get("hits", []):
        source_doc = hit.get("_source") or {}
        source_doc["_index"] = hit.get("_index")
        source_doc["_id"] = hit.get("_id")
        source_doc["_score"] = hit.get("_score")
        items.append(source_doc)
    return items, total


def terms_agg(index: str, field: str, size: int = 20, query: Optional[dict] = None) -> list[dict]:
    body = {"size": 0, "query": query or {"match_all": {}}, "aggs": {"items": {"terms": {"field": field, "size": size, "missing": "__missing__"}}}}
    response = es_request("POST", f"/{index}/_search", body)
    buckets = response.get("aggregations", {}).get("items", {}).get("buckets", [])
    return [{"key": item.get("key"), "count": item.get("doc_count", 0)} for item in buckets]


def count_index(index: str, query: Optional[dict] = None) -> int:
    response = es_request("POST", f"/{index}/_count", {"query": query or {"match_all": {}}})
    return int(response.get("count", 0))


def knowledge_query(args: dict, *, default_values: list[str]) -> dict:
    filters: list[dict] = []
    for field in ["service", "canonical_symptom", "knowledge_value", "source_type"]:
        item = term_filter(field, args.get(field))
        if item:
            filters.append(item)
    if not args.get("knowledge_value") and default_values:
        filters.append({"terms": {"knowledge_value": default_values}})
    query_part = query_text_filter(
        args.get("q") or args.get("query") or "",
        [
            "title^4",
            "knowledge_title^4",
            "report_file^3",
            "source_file^3",
            "knowledge_content^4",
            "fault_content^3",
            "root_cause^3",
            "fix_method^3",
            "handling_result^3",
            "investigation_steps^2",
            "embedding_text^2",
            "report_text",
        ],
    )
    if query_part:
        filters.append(query_part)
    return {"bool": {"filter": filters}} if filters else {"match_all": {}}


def compact_repair(row: dict) -> dict:
    return {
        "id": row.get("_id") or row.get("record_id"),
        "record_id": row.get("record_id"),
        "source_file": row.get("source_file"),
        "source_sheet": row.get("source_sheet"),
        "source_row": row.get("source_row"),
        "occurred_date": row.get("occurred_date"),
        "service": row.get("service"),
        "area": row.get("area"),
        "report_type": row.get("report_type"),
        "canonical_symptom": row.get("canonical_symptom"),
        "canonical_symptom_label": row.get("canonical_symptom_label"),
        "knowledge_value": row.get("knowledge_value"),
        "knowledge_score": row.get("knowledge_score"),
        "fault_content": compact_text(row.get("fault_content"), 420),
        "handling_result": compact_text(row.get("handling_result"), 420),
        "embedding_status": row.get("embedding_status"),
    }


def compact_report(row: dict) -> dict:
    return {
        "id": row.get("_id") or row.get("record_id"),
        "record_id": row.get("record_id"),
        "source_type": row.get("source_type"),
        "knowledge_kind": row.get("knowledge_kind"),
        "knowledge_title": row.get("knowledge_title"),
        "knowledge_content": compact_knowledge_content(row),
        "source_file": row.get("source_file"),
        "report_file": row.get("report_file"),
        "occurred_date": row.get("occurred_date"),
        "service": row.get("service"),
        "area": row.get("area"),
        "canonical_symptom": row.get("canonical_symptom"),
        "canonical_symptom_label": row.get("canonical_symptom_label"),
        "knowledge_value": row.get("knowledge_value"),
        "knowledge_score": row.get("knowledge_score"),
        "title": row.get("title"),
        "fault_content": compact_text(row.get("fault_content"), 600),
        "root_cause": compact_text(row.get("root_cause"), 600),
        "investigation_steps": compact_text(row.get("investigation_steps"), 900),
        "fix_method": compact_text(row.get("fix_method"), 900),
        "prevention": compact_text(row.get("prevention"), 600),
        "embedding_status": row.get("embedding_status"),
    }


def compact_topic(row: dict) -> dict:
    return {
        "id": row.get("_id") or row.get("aggregate_id"),
        "topic_key": row.get("topic_key"),
        "topic_label": row.get("topic_label"),
        "topic_source": row.get("topic_source"),
        "service": row.get("service"),
        "canonical_symptom": row.get("canonical_symptom"),
        "total_count": row.get("total_count"),
        "formal_count": row.get("formal_count"),
        "duty_count": row.get("duty_count"),
        "reference_count": row.get("reference_count"),
        "aggregate_only_count": row.get("aggregate_only_count"),
        "first_seen": row.get("first_seen"),
        "last_seen": row.get("last_seen"),
        "top_actions": row.get("top_actions") or [],
        "top_areas": row.get("top_areas") or [],
        "representative_cases": row.get("representative_cases") or [],
    }


@fault_kb_bp.get("/summary")
@login_required
def kb_summary(current_user):
    try:
        with session_scope(db_session_factory()) as db:
            chat_session_count = db.execute(select(func.count(AiChatSession.id)).where(AiChatSession.status == "active")).scalar() or 0
            chat_message_count = db.execute(select(func.count(AiChatMessage.id))).scalar() or 0
        return jsonify(
            {
                "ok": True,
                "repair_count": count_index(f"{DUTY_INDEX_PREFIX}-*"),
                "formal_count": count_index(f"{FORMAL_INDEX_PREFIX}-*"),
                "formal_report_count": count_index(f"{FORMAL_INDEX_PREFIX}-*", {"term": {"source_type": "formal_fault_report"}}),
                "document_count": count_index(f"{FORMAL_INDEX_PREFIX}-*", {"term": {"source_type": "document_kb"}}),
                "topic_count": count_index(TOPIC_INDEX),
                "chat_session_count": int(chat_session_count),
                "chat_message_count": int(chat_message_count),
                "repair_source_files": terms_agg(f"{DUTY_INDEX_PREFIX}-*", "source_file", 10),
                "formal_report_files": terms_agg(f"{FORMAL_INDEX_PREFIX}-*", "report_file", 20),
                "knowledge_values": terms_agg(f"{DUTY_INDEX_PREFIX}-*", "knowledge_value", 10),
                "formal_symptoms": terms_agg(f"{FORMAL_INDEX_PREFIX}-*", "canonical_symptom", 20),
            }
        )
    except Exception as exc:
        return json_error(str(exc), 500)


@fault_kb_bp.get("/repairs")
@login_required
def list_repairs(current_user):
    try:
        limit = clamp_int(request.args.get("limit"), 20, 1, 100)
        offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
        include_noise = bool_param(request.args.get("include_noise"))
        values = [] if include_noise else ["reference", "aggregate_only", "low_value"]
        docs, total = search_with_total(
            f"{DUTY_INDEX_PREFIX}-*",
            knowledge_query(request.args, default_values=values),
            limit,
            offset,
            [{"occurred_time": {"order": "desc", "unmapped_type": "date"}}],
            [
                "record_id",
                "source_file",
                "source_sheet",
                "source_row",
                "occurred_date",
                "occurred_time",
                "service",
                "area",
                "report_type",
                "canonical_symptom",
                "canonical_symptom_label",
                "knowledge_value",
                "knowledge_score",
                "fault_content",
                "handling_result",
                "embedding_status",
            ],
        )
        return jsonify({"ok": True, "items": [compact_repair(row) for row in docs], "total": total, "limit": limit, "offset": offset})
    except Exception as exc:
        return json_error(str(exc), 500)


@fault_kb_bp.get("/reports")
@login_required
def list_reports(current_user):
    try:
        limit = clamp_int(request.args.get("limit"), 20, 1, 100)
        offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
        docs, total = search_with_total(
            f"{FORMAL_INDEX_PREFIX}-*",
            knowledge_query(request.args, default_values=["reference", "aggregate_only"]),
            limit,
            offset,
            [{"occurred_time": {"order": "desc", "unmapped_type": "date"}}],
            [
                "record_id",
                "source_type",
                "knowledge_kind",
                "knowledge_title",
                "knowledge_content",
                "source_file",
                "report_file",
                "occurred_date",
                "occurred_time",
                "service",
                "area",
                "canonical_symptom",
                "canonical_symptom_label",
                "knowledge_value",
                "knowledge_score",
                "title",
                "fault_content",
                "root_cause",
                "investigation_steps",
                "fix_method",
                "prevention",
                "embedding_status",
            ],
        )
        return jsonify({"ok": True, "items": [compact_report(row) for row in docs], "total": total, "limit": limit, "offset": offset})
    except Exception as exc:
        return json_error(str(exc), 500)


@fault_kb_bp.get("/topics")
@login_required
def list_topics(current_user):
    try:
        limit = clamp_int(request.args.get("limit"), 20, 1, 100)
        offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
        filters = []
        for field in ["service", "canonical_symptom", "topic_source"]:
            item = term_filter(field, request.args.get(field))
            if item:
                filters.append(item)
        query_part = query_text_filter(request.args.get("q") or "", ["topic_label^4", "suggested_query^3", "representative_cases.title^2"])
        if query_part:
            filters.append(query_part)
        docs, total = search_with_total(
            TOPIC_INDEX,
            {"bool": {"filter": filters}} if filters else {"match_all": {}},
            limit,
            offset,
            [{"reference_count": {"order": "desc", "unmapped_type": "long"}}, {"total_count": {"order": "desc", "unmapped_type": "long"}}],
            [
                "aggregate_id",
                "topic_key",
                "topic_label",
                "topic_source",
                "service",
                "canonical_symptom",
                "total_count",
                "formal_count",
                "duty_count",
                "reference_count",
                "aggregate_only_count",
                "first_seen",
                "last_seen",
                "top_actions",
                "top_areas",
                "representative_cases",
            ],
        )
        return jsonify({"ok": True, "items": [compact_topic(row) for row in docs], "total": total, "limit": limit, "offset": offset})
    except Exception as exc:
        return json_error(str(exc), 500)


def delete_index(pattern: str) -> None:
    try:
        es_request("DELETE", f"/{urllib.parse.quote(pattern, safe='*,')}")
    except RuntimeError as exc:
        if "Elasticsearch request failed: 404" not in str(exc):
            raise


def rebuild_topics() -> dict:
    from scripts.build_fault_kb_aggregates import main as _unused  # noqa: F401
    from scripts.build_fault_kb_aggregates import build_aggregates, bulk_replace, install_template, scroll_docs

    query = {"bool": {"must_not": [{"term": {"knowledge_value": "noise"}}]}}
    records = list(scroll_docs(es_url(), f"{FORMAL_INDEX_PREFIX}-*", query)) + list(scroll_docs(es_url(), f"{DUTY_INDEX_PREFIX}-*", query))
    aggregates = build_aggregates(records, int(os.getenv("FAULT_KB_AGGREGATE_MIN_COUNT", "2")))
    install_template(es_url(), pathlib.Path("deploy/elasticsearch/templates/fault_kb_aggregates_template.json"), "jscn-aiops-fault-kb-aggregates")
    delete_index(TOPIC_INDEX)
    result = bulk_replace(es_url(), TOPIC_INDEX, aggregates)
    return {"source_records": len(records), "aggregate_count": len(aggregates), **result}


def run_kb_import(kind: str, source_path: pathlib.Path, payload: dict[str, Any]) -> dict[str, Any]:
    rebuild = bool_param(payload.get("rebuild"))
    rebuild_aggregates = bool_param(payload.get("rebuild_aggregates", True))
    if kind == "repair":
        from scripts.import_duty_repair_excel import import_duty_repair_excel

        if rebuild:
            delete_index(f"{DUTY_INDEX_PREFIX}-*")
        report = import_duty_repair_excel(
            es_url(),
            source_path,
            DUTY_INDEX_PREFIX,
            pathlib.Path("deploy/elasticsearch/templates/duty_repair_records_template.json"),
            pathlib.Path("reports/fault_kb/duty_repair_import_report.md"),
            pathlib.Path("reports/fault_kb/duty_repair_records.json"),
            int(os.getenv("DUTY_REPAIR_BATCH_SIZE", "500")),
            False,
            True,
            bool_param(payload.get("drop_noise")),
            None,
        )
    else:
        from scripts.import_formal_fault_kb import import_formal_fault_kb

        if rebuild:
            delete_index(f"{FORMAL_INDEX_PREFIX}-*")
        report = import_formal_fault_kb(
            es_url(),
            source_path,
            FORMAL_INDEX_PREFIX,
            pathlib.Path("deploy/elasticsearch/templates/fault_kb_template.json"),
            pathlib.Path("reports/fault_kb/formal_fault_import_report.md"),
            pathlib.Path("reports/fault_kb/formal_fault_records.json"),
            int(os.getenv("FAULT_KB_BATCH_SIZE", "200")),
            False,
            True,
        )
    aggregate_report = rebuild_topics() if rebuild_aggregates else None
    return {"ok": True, "kind": kind, "report": report, "aggregates": aggregate_report}


@fault_kb_bp.post("/import")
@admin_required
def import_kb(current_user):
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "").strip()
    source_path = pathlib.Path(str(payload.get("path") or "")).expanduser()
    if kind not in {"repair", "formal"}:
        return json_error("kind must be repair or formal")
    if not source_path.exists():
        return json_error("source path does not exist", 404)
    try:
        return jsonify(run_kb_import(kind, source_path, payload))
    except Exception as exc:
        return json_error(str(exc), 500)


def upload_root() -> pathlib.Path:
    return pathlib.Path(os.getenv("FAULT_KB_UPLOAD_DIR", "/data/jscn-aiops/uploads/fault_kb")).expanduser()


def safe_extract_zip(zip_path: pathlib.Path, target_dir: pathlib.Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for item in archive.infolist():
            dest = (target_dir / item.filename).resolve()
            if not str(dest).startswith(str(target_dir.resolve())):
                raise ValueError("zip contains unsafe path")
        archive.extractall(target_dir)


def convert_legacy_doc_to_docx(path: pathlib.Path) -> pathlib.Path:
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise RuntimeError("legacy .doc import requires LibreOffice or soffice on the server; please upload .docx instead")
    output_path = path.with_suffix(".docx")
    subprocess.run(
        [converter, "--headless", "--convert-to", "docx", "--outdir", str(path.parent), str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    if not output_path.exists():
        raise RuntimeError(f"legacy .doc conversion did not create {output_path.name}")
    return output_path


def prepare_formal_upload_dir(source_path: pathlib.Path) -> None:
    for path in sorted(item for item in source_path.rglob("*") if item.is_file()):
        if path.suffix.lower() == ".doc":
            convert_legacy_doc_to_docx(path)


@fault_kb_bp.post("/import/upload")
@admin_required
def import_kb_upload(current_user):
    kind = str(request.form.get("kind") or "").strip()
    if kind not in {"repair", "formal"}:
        return json_error("kind must be repair or formal")
    files = request.files.getlist("files") or ([request.files["file"]] if "file" in request.files else [])
    files = [item for item in files if item and item.filename]
    if not files:
        return json_error("file is required")

    batch_dir = upload_root() / dt.datetime.now().strftime("%Y%m%d-%H%M%S") / uuid.uuid4().hex[:8]
    batch_dir.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "repair":
            if len(files) != 1:
                return json_error("repair import expects one Excel file")
            filename = secure_filename(files[0].filename) or "repair.xlsx"
            if not filename.lower().endswith((".xlsx", ".xls")):
                return json_error("repair import only accepts .xlsx or .xls")
            source_path = batch_dir / filename
            files[0].save(source_path)
        else:
            source_path = batch_dir / "formal_reports"
            source_path.mkdir(parents=True, exist_ok=True)
            for file_item in files:
                filename = secure_filename(file_item.filename) or f"upload-{uuid.uuid4().hex}"
                saved_path = batch_dir / filename
                file_item.save(saved_path)
                if filename.lower().endswith(".zip"):
                    safe_extract_zip(saved_path, source_path)
                elif filename.lower().endswith((".docx", ".doc", ".xlsx")):
                    shutil.copy2(saved_path, source_path / filename)
                else:
                    return json_error("formal import accepts .zip, .docx, .doc, or .xlsx")
            prepare_formal_upload_dir(source_path)
        payload = {
            "rebuild": request.form.get("rebuild"),
            "rebuild_aggregates": request.form.get("rebuild_aggregates", "true"),
            "drop_noise": request.form.get("drop_noise"),
        }
        result = run_kb_import(kind, source_path, payload)
        result["upload_dir"] = str(batch_dir)
        return jsonify(result)
    except Exception as exc:
        return json_error(str(exc), 500)


def clean_chat_query(message: str) -> str:
    text = message.strip()
    for prefix in ["/kb", "/report", "/repair", "#故障报告", "#故障", "#报修", "#知识库"]:
        if text.lower().startswith(prefix.lower()):
            return text[len(prefix) :].strip()
    return text


def should_search_kb(message: str) -> bool:
    text = message.strip().lower()
    ops_keywords = [
        "故障",
        "报修",
        "排查",
        "处理",
        "卡顿",
        "黑屏",
        "点8",
        "点播",
        "回看",
        "机顶盒",
        "宽带",
        "测速",
        "带宽",
        "网速",
        "掉线",
        "丢包",
        "拨号",
        "光猫",
        "路由器",
        "olt",
        "onu",
        "cm",
        "cmts",
        "ipqam",
        "eoc",
        "vlan",
        "出口",
        "信源",
        "频道",
    ]
    return any(item in text for item in ops_keywords)


def clean_model_answer(answer: str) -> str:
    text = (answer or "").strip()
    text = text.replace("**", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def build_evidence_fallback_answer(question: str, evidence: dict[str, Any]) -> str:
    records = evidence.get("records") or []
    topics = evidence.get("topics") or []
    formal = next((item for item in records if item.get("source_type") == "formal_fault_report"), None)
    document = next((item for item in records if item.get("source_type") == "document_kb"), None)
    duty = next((item for item in records if item.get("source_type") == "duty_repair_excel"), None)
    top = formal or document or duty
    if not top:
        return "模型暂时没有返回结果。可以先补充故障现象、影响范围、用户接入方式和最近变更，再继续排查。"

    title = first_non_empty(top.get("title"), top.get("fault_content"), "相关知识库记录")
    root = first_non_empty(top.get("root_cause"), top.get("fault_content"))
    fix = first_non_empty(top.get("fix_method"), top.get("handling_result"))
    topic = first_non_empty(*(item.get("topic_label") for item in topics[:1]))
    if top.get("source_type") == "formal_fault_report":
        source_name = "正式故障报告"
    elif top.get("source_type") == "document_kb":
        source_name = "运维文档"
    else:
        source_name = "报修流水"

    lines = [f"可以参考{source_name}《{title}》。"]
    if "点8" in question and ("olt" in question.lower() or "策略" in question or "配置" in question):
        lines[0] = f"会的。知识库里有一条高度相关的正式报告《{title}》。"
    if root:
        lines.append(f"这条记录里的关键原因是：{root}")
    if fix:
        lines.append(f"处理方向是：{fix}")
    if topic:
        lines.append(f"相关主题归到“{topic}”，所以如果现场表现为点8打不开、加载慢、黑屏或卡顿，都可以优先检查 OLT 策略、点8地址段访问权限，再结合机顶盒和链路质量排查。")
    lines.append("模型这次没有稳定返回，我先按已命中的知识库证据给出以上结论。")
    return "\n\n".join(lines)


def chat_time(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def serialize_chat_session(row: AiChatSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "source": row.source,
        "status": row.status,
        "message_count": row.message_count,
        "last_message_at": chat_time(row.last_message_at),
        "created_at": chat_time(row.created_at),
        "updated_at": chat_time(row.updated_at),
    }


def serialize_chat_log_session(row: AiChatSession, username: str | None = None) -> dict[str, Any]:
    payload = serialize_chat_session(row)
    payload["username"] = username or "-"
    payload["user_id"] = row.user_id
    return payload


def serialize_chat_message(row: AiChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "evidence": row.evidence,
        "model": row.model_name,
        "provider": row.provider_name,
        "model_error": row.model_error,
        "duration_ms": row.duration_ms,
        "created_at": chat_time(row.created_at),
    }


def chat_title(message: str) -> str:
    title = " ".join(str(message or "").split())
    return (title[:40] + "...") if len(title) > 40 else title or "新对话"


@fault_kb_bp.get("/chat/sessions")
@login_required
def list_chat_sessions(current_user):
    limit = clamp_int(request.args.get("limit"), 30, 1, 100)
    with session_scope(db_session_factory()) as db:
        rows = (
            db.execute(
                select(AiChatSession)
                .where(AiChatSession.user_id == current_user.id, AiChatSession.status == "active")
                .order_by(desc(AiChatSession.last_message_at))
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return jsonify({"ok": True, "items": [serialize_chat_session(row) for row in rows]})


@fault_kb_bp.get("/chat/sessions/<int:session_id>")
@login_required
def get_chat_session(session_id: int, current_user):
    with session_scope(db_session_factory()) as db:
        row = db.get(AiChatSession, session_id)
        if not row or row.user_id != current_user.id or row.status != "active":
            return json_error("chat session not found", 404)
        messages = (
            db.execute(select(AiChatMessage).where(AiChatMessage.session_id == row.id).order_by(AiChatMessage.created_at, AiChatMessage.id))
            .scalars()
            .all()
        )
        return jsonify({"ok": True, "session": serialize_chat_session(row), "messages": [serialize_chat_message(item) for item in messages]})


@fault_kb_bp.get("/chat/logs")
@admin_required
def list_chat_logs(current_user):
    limit = clamp_int(request.args.get("limit"), 50, 1, 200)
    offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
    with session_scope(db_session_factory()) as db:
        rows = (
            db.execute(
                select(AiChatSession, User.username)
                .join(User, User.id == AiChatSession.user_id)
                .where(AiChatSession.status == "active")
                .order_by(desc(AiChatSession.last_message_at))
                .limit(limit)
                .offset(offset)
            )
            .all()
        )
        items = []
        for session_row, username in rows:
            latest_messages = (
                db.execute(
                    select(AiChatMessage)
                    .where(AiChatMessage.session_id == session_row.id)
                    .order_by(desc(AiChatMessage.created_at), desc(AiChatMessage.id))
                    .limit(2)
                )
                .scalars()
                .all()
            )
            item = serialize_chat_log_session(session_row, username)
            item["latest_messages"] = [serialize_chat_message(message) for message in reversed(latest_messages)]
            items.append(item)
        return jsonify({"ok": True, "items": items, "limit": limit, "offset": offset})


@fault_kb_bp.get("/chat/logs/<int:session_id>")
@admin_required
def get_chat_log(session_id: int, current_user):
    with session_scope(db_session_factory()) as db:
        row = db.get(AiChatSession, session_id)
        if not row or row.status != "active":
            return json_error("chat session not found", 404)
        owner = db.get(User, row.user_id)
        messages = (
            db.execute(select(AiChatMessage).where(AiChatMessage.session_id == row.id).order_by(AiChatMessage.created_at, AiChatMessage.id))
            .scalars()
            .all()
        )
        return jsonify(
            {
                "ok": True,
                "session": serialize_chat_log_session(row, owner.username if owner else None),
                "messages": [serialize_chat_message(item) for item in messages],
            }
        )


@fault_kb_bp.delete("/chat/sessions/<int:session_id>")
@login_required
def delete_chat_session(session_id: int, current_user):
    with session_scope(db_session_factory()) as db:
        row = db.get(AiChatSession, session_id)
        if not row or row.user_id != current_user.id:
            return json_error("chat session not found", 404)
        row.status = "deleted"
        return jsonify({"ok": True, "deleted": session_id})


def persist_chat_turn(current_user, payload: dict[str, Any], question: str, answer_payload: dict[str, Any]) -> int:
    requested_session = payload.get("session_id")
    now = utc_now()
    with session_scope(db_session_factory()) as db:
        session_row = None
        if requested_session:
            try:
                session_id = int(requested_session)
            except (TypeError, ValueError):
                session_id = 0
            session_row = db.get(AiChatSession, session_id) if session_id else None
            if session_row and (session_row.user_id != current_user.id or session_row.status != "active"):
                session_row = None
        if not session_row:
            session_row = AiChatSession(user_id=current_user.id, title=chat_title(question), source="fault_kb_qa", status="active", message_count=0, last_message_at=now)
            db.add(session_row)
            db.flush()
        db.add(AiChatMessage(session_id=session_row.id, user_id=current_user.id, role="user", content=question))
        db.add(
            AiChatMessage(
                session_id=session_row.id,
                user_id=current_user.id,
                role="assistant",
                content=answer_payload.get("answer") or "",
                evidence=answer_payload.get("evidence"),
                model_name=answer_payload.get("model"),
                provider_name=answer_payload.get("provider"),
                model_error=answer_payload.get("model_error"),
                duration_ms=answer_payload.get("duration_ms"),
            )
        )
        session_row.message_count = (session_row.message_count or 0) + 2
        session_row.last_message_at = now
        if session_row.title == "新对话":
            session_row.title = chat_title(question)
        db.flush()
        return session_row.id


@fault_kb_bp.post("/chat")
@login_required
def kb_chat(current_user):
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    mode = "auto"
    if not message:
        return json_error("message is required")
    query = clean_chat_query(message)
    evidence: dict[str, Any] = {}
    use_kb = should_search_kb(query)
    if use_kb:
        evidence = search_fault_kb(
            {
                "query": query,
                "service": payload.get("service"),
                "canonical_symptom": payload.get("canonical_symptom"),
                "include_low_value": payload.get("include_low_value", False),
                "include_noise": False,
                "source_scope": "all",
                "es_url": es_url(),
                "limit": clamp_int(payload.get("limit"), 10, 1, 20),
            }
        )
    system_prompt = (
        "你是一个自然、可靠的 AI 助手，同时熟悉江苏有线南京分公司的宽带、电视和网络运维。"
        "用户问运维问题时，先用知识库证据辅助判断：正式故障报告可信度最高，报修流水只作为经验参考。"
        "不要暴露检索策略，不要说“知识库全部聚焦于某类业务”这类生硬的话。"
        "如果证据不足，就直接给通用排查路径，并用一句话说明还需要哪些关键信息。"
        "普通非运维问题正常回答；如果确实没有实时数据源，就温和说明限制并给可操作建议。"
        "回答要像值班工程师和同事说话：简短、清楚、自然。不要使用 Markdown 粗体，不要堆长篇。"
        "默认控制在 6 条以内，优先给结论和下一步动作。"
    )
    user_prompt = {
        "question": message,
        "knowledge_base_used": use_kb,
        "evidence": evidence,
    }
    try:
        result = call_llm(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)}],
            model=str(payload.get("llm_selector") or os.getenv("FAULT_KB_QA_LLM_SELECTOR") or "llm_usage:fault_kb_qa"),
            temperature=float(os.getenv("FAULT_KB_QA_TEMPERATURE", "0.2")),
            timeout=int(os.getenv("FAULT_KB_QA_TIMEOUT", "120")),
        )
        answer = clean_model_answer(result.response.choices[0].message.content or "")
        if not answer:
            answer = build_evidence_fallback_answer(message, evidence) if use_kb else "模型暂时没有返回结果，请稍后再试。"
        response_payload = {
            "ok": True,
            "answer": answer,
            "mode": mode,
            "knowledge_base_used": use_kb,
            "evidence": evidence,
            "model": result.model,
            "provider": result.provider,
            "duration_ms": result.duration_ms,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        response_payload["session_id"] = persist_chat_turn(current_user, payload, message, response_payload)
        return jsonify(response_payload)
    except Exception as exc:
        fallback = (
            build_evidence_fallback_answer(message, evidence)
            if use_kb
            else "模型暂时没有返回结果，请稍后再试。"
        )
        response_payload = {
            "ok": True,
            "answer": fallback,
            "mode": mode,
            "knowledge_base_used": use_kb,
            "evidence": evidence,
            "model_error": sanitize_error(exc),
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        response_payload["session_id"] = persist_chat_turn(current_user, payload, message, response_payload)
        return jsonify(response_payload)
