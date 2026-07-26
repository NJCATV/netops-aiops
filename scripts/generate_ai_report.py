#!/usr/bin/env python3
"""Generate an AI Markdown report from Task 12 context.

Task 13 calls an OpenAI-compatible API, saves the generated Markdown report,
stores report metadata in MySQL, and indexes the report body into
Elasticsearch. It expects the AI API key to come from runtime environment
variables and never from committed files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in runtime
    load_dotenv = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import create_db_engine, make_session_factory, session_scope  # noqa: E402
from app.models import ReportRecord  # noqa: E402


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_env(path: Optional[str]) -> None:
    candidates = []
    if path:
        candidates.append(pathlib.Path(path))
    else:
        candidates.extend([ROOT / ".env", ROOT / "deploy" / ".env"])
    for candidate in candidates:
        if candidate.exists() and load_dotenv is not None:
            load_dotenv(candidate, override=False)


def es_request(es_url: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(es_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("Elasticsearch request failed: %s %s" % (exc.code, detail)) from exc
    return json.loads(payload) if payload else {}


def install_template(es_url: str, template_path: pathlib.Path) -> None:
    if not template_path.exists():
        return
    body = json.loads(template_path.read_text(encoding="utf-8"))
    es_request(es_url, "PUT", "/_index_template/jscn-aiops-ai-reports", body)


def compact_context(context: dict) -> dict:
    """Keep the prompt focused and bounded."""
    current = context.get("current_window", {})
    alarm_events = current.get("alarm_events", {})
    special = context.get("special_analysis", {})
    topology = context.get("topology_context", {})
    return {
        "metadata": context.get("metadata", {}),
        "window": context.get("window", {}),
        "syslog": current.get("syslog", {}),
        "trap": current.get("trap", {}),
        "alarm_events": {
            "total": alarm_events.get("total"),
            "compressed_raw_log_count": alarm_events.get("compressed_raw_log_count"),
            "top_event_type": alarm_events.get("top_event_type", []),
            "top_device_ip": alarm_events.get("top_device_ip", []),
            "top_device_name": alarm_events.get("top_device_name", []),
            "top_event_status": alarm_events.get("top_event_status", []),
            "open_events": alarm_events.get("open_events", [])[:20],
            "recovered_or_flapping_events": alarm_events.get("recovered_or_flapping_events", [])[:20],
            "key_event_samples": alarm_events.get("key_event_samples", [])[:20],
        },
        "baseline": context.get("baseline", {}),
        "special_analysis": special,
        "topology_context": {
            "enabled": topology.get("enabled"),
            "inventory_device_total": topology.get("inventory_device_total"),
            "inventory_link_total": topology.get("inventory_link_total"),
            "matched_device_count": topology.get("matched_device_count"),
            "related_link_count": topology.get("related_link_count"),
            "matched_devices": topology.get("matched_devices", [])[:30],
            "related_links": topology.get("related_links", [])[:50],
            "device_role_counts": topology.get("device_role_counts", []),
            "device_status_counts": topology.get("device_status_counts", []),
            "link_state_counts": topology.get("link_state_counts", []),
            "notes": topology.get("notes", []),
        },
    }


def build_messages(context: dict) -> list[dict]:
    compact = compact_context(context)
    system = (
        "你是城域网 AIOps 值班分析助手。必须只基于用户提供的 JSON context 分析，"
        "不要编造不存在的设备、链路或告警。输出中文 Markdown 报告，结论要具体、可处置。"
    )
    user = {
        "task": "根据 AIOps 上下文生成城域网告警分析报告。",
        "report_requirements": [
            "整体运行概况",
            "当前窗口与历史基线对比",
            "高频异常设备和设备角色/链路影响",
            "高频事件类型",
            "PPP 认证异常",
            "PTP 时钟抖动",
            "BFD 链路震荡",
            "Optical 光模块/光路异常",
            "Radius/QoS/Trap 重要信号",
            "可能原因",
            "处置建议",
            "后续关注项",
        ],
        "style_constraints": [
            "不要泛泛而谈，每条判断要引用 context 中的统计或样例。",
            "如果 topology_context.enabled=true，必须结合 networkDevice/networkLinks 信息说明影响面。",
            "如果数据不足，要明确说明不足，而不是猜测。",
            "不要输出 JSON，只输出 Markdown。",
        ],
        "context": compact,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def call_ai(context: dict, model: str, api_base: str, api_key: str, timeout: int, reasoning_effort: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)
    response = client.chat.completions.create(
        model=model,
        messages=build_messages(context),
        stream=False,
        reasoning_effort=reasoning_effort,
        extra_body={"thinking": {"type": "enabled"}},
    )
    return response.choices[0].message.content or ""


def report_title(context: dict) -> str:
    window = context.get("window", {})
    end = parse_time(window.get("end")) or utc_now()
    return "JSCN AIOps %s 告警分析报告" % end.strftime("%Y-%m-%d %H:%M")


def ensure_markdown_title(markdown: str, title: str) -> str:
    text = markdown.strip()
    if text.startswith("# "):
        return text + "\n"
    return "# %s\n\n%s\n" % (title, text)


def context_summary(context: dict) -> dict:
    current = context.get("current_window", {})
    events = current.get("alarm_events", {})
    topology = context.get("topology_context", {})
    return {
        "syslog_total": current.get("syslog", {}).get("total"),
        "trap_total": current.get("trap", {}).get("total"),
        "alarm_events_total": events.get("total"),
        "compressed_raw_log_count": events.get("compressed_raw_log_count"),
        "top_event_type": events.get("top_event_type", [])[:10],
        "top_device_ip": events.get("top_device_ip", [])[:10],
        "topology_enabled": topology.get("enabled"),
        "matched_device_count": topology.get("matched_device_count"),
        "related_link_count": topology.get("related_link_count"),
    }


def create_report_record(context: dict, title: str, status: str, file_path: Optional[str] = None, error: Optional[str] = None) -> int:
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    window = context.get("window", {})
    with session_scope(session_factory) as session:
        record = ReportRecord(
            report_title=title,
            time_window_start=parse_time(window.get("start")),
            time_window_end=parse_time(window.get("end")),
            hours=window.get("hours"),
            status=status,
            file_path=file_path,
            error_message=error,
            metrics=context_summary(context),
        )
        session.add(record)
        session.flush()
        return int(record.id)


def update_report_record(record_id: int, **values: Any) -> None:
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        record = session.get(ReportRecord, record_id)
        if not record:
            return
        for key, value in values.items():
            setattr(record, key, value)


def index_report(es_url: str, index_prefix: str, report_id: int, context: dict, markdown: str, model: str, api_base: str, report_path: str, template_path: pathlib.Path) -> tuple[str, str]:
    install_template(es_url, template_path)
    window = context.get("window", {})
    end = parse_time(window.get("end")) or utc_now()
    index = "%s-%s" % (index_prefix, end.strftime("%Y.%m.%d"))
    doc_id = "report-%s" % report_id
    now = iso_z(utc_now())
    doc = {
        "@timestamp": now,
        "report_id": str(report_id),
        "title": report_title(context),
        "status": "success",
        "model": model,
        "ai_api_base": api_base,
        "context_path": context.get("metadata", {}).get("context_path"),
        "report_path": report_path,
        "window_start": window.get("start"),
        "window_end": window.get("end"),
        "hours": window.get("hours"),
        "baseline_days": window.get("baseline_days"),
        "markdown": markdown,
        "context_summary": context_summary(context),
        "created_at": now,
        "updated_at": now,
    }
    es_request(es_url, "PUT", "/%s/_doc/%s?refresh=true" % (index, doc_id), doc)
    return index, doc_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE"))
    parser.add_argument("--context-json", default=os.getenv("AI_CONTEXT_JSON"))
    parser.add_argument("--hours", type=int, default=int(os.getenv("AI_REPORT_HOURS", "24")))
    parser.add_argument("--out-dir", default=os.getenv("AI_REPORT_OUT_DIR", "/data/jscn-aiops/reports"))
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--es-index-prefix", default=os.getenv("AI_REPORT_ES_INDEX_PREFIX", "jscn-aiops-ai-reports"))
    parser.add_argument("--template", default=os.getenv("AI_REPORT_ES_TEMPLATE", "deploy/elasticsearch/templates/ai_reports_template.json"))
    parser.add_argument("--api-base", default=os.getenv("AI_API_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--model", default=os.getenv("AI_MODEL", "deepseek-v4-pro"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "120")))
    parser.add_argument("--reasoning-effort", default=os.getenv("AI_REASONING_EFFORT", "high"))
    args = parser.parse_args()
    load_env(args.env_file)

    if not args.context_json:
        raise RuntimeError("--context-json is required")

    context_path = pathlib.Path(args.context_json)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context.setdefault("metadata", {})["context_path"] = str(context_path)
    title = report_title(context)
    record_id = create_report_record(context, title, "running")
    report_path = pathlib.Path(args.out_dir) / ("%s-aiops-report.md" % (parse_time(context.get("window", {}).get("end")) or utc_now()).strftime("%Y-%m-%d-%H"))

    try:
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY or AI_API_KEY is required")
        markdown = ensure_markdown_title(call_ai(context, args.model, args.api_base, api_key, args.timeout, args.reasoning_effort), title)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown, encoding="utf-8")
        es_index, es_doc_id = index_report(args.es_url, args.es_index_prefix, record_id, context, markdown, args.model, args.api_base, str(report_path), pathlib.Path(args.template))
        update_report_record(record_id, status="success", file_path=str(report_path), es_index=es_index, es_document_id=es_doc_id, summary=markdown[:4000])
        result = {"report_record_id": record_id, "report_path": str(report_path), "es_index": es_index, "es_document_id": es_doc_id, "status": "success"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        update_report_record(record_id, status="failed", error_message=str(exc), file_path=str(report_path))
        print(json.dumps({"report_record_id": record_id, "status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
