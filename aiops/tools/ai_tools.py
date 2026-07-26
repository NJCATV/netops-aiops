"""Controlled AI-callable tools for the lightweight AIOps Agent.

The functions in this module are the only investigation tools Task 16 should
expose to the AI loop. They accept constrained parameters, enforce limits,
return compact JSON-serializable results, and never accept raw ES DSL or SQL.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

from aiops.context.current_window_summary import (
    count_docs,
    event_source_fields,
    event_window_query,
    iso_z,
    parse_time,
    range_query,
    search_docs,
    utc_now,
)
from aiops.tools import investigation
from aiops.tools.investigation import (
    InvestigationConfig,
    InvestigationLimits,
    bool_query,
    build_baseline_snapshot,
    candidate_identity,
    compact_event,
    find_historical_events,
    find_related_current_events,
    historical_filters,
    investigate_candidates as build_investigation_context,
    load_env_file,
    load_topology,
    term_if_present,
)


LOGGER = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_DAYS = 30
MAX_CANDIDATES = 20
FAULT_KB_INDEX = "jscn-aiops-fault-kb-*"
DUTY_REPAIR_INDEX = "jscn-aiops-duty-repair-records-*"
FAULT_TOPIC_INDEX = "jscn-aiops-fault-topic-aggregates"


class ToolArgumentError(ValueError):
    pass


def clamp_limit(value: Any, default: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolArgumentError("limit must be an integer") from exc
    if limit < 1:
        raise ToolArgumentError("limit must be >= 1")
    return min(limit, max_limit)


def parse_days(value: Any, default: int = 7) -> int:
    if value is None:
        return default
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolArgumentError("days must be an integer") from exc
    if days < 1:
        raise ToolArgumentError("days must be >= 1")
    return min(days, MAX_DAYS)


def parse_tool_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def require_any(arguments: dict, fields: List[str]) -> None:
    if not any(arguments.get(field) for field in fields):
        raise ToolArgumentError("one of %s is required" % ", ".join(fields))


def parse_window(arguments: dict, default_hours: int = 24) -> tuple[dt.datetime, dt.datetime]:
    end = parse_time(arguments.get("window_end")) or utc_now()
    start = parse_time(arguments.get("window_start")) or (end - dt.timedelta(hours=default_hours))
    if start >= end:
        raise ToolArgumentError("window_start must be earlier than window_end")
    return start, end


def load_summary(arguments: dict) -> dict:
    if isinstance(arguments.get("summary"), dict):
        return arguments["summary"]
    summary_json = arguments.get("summary_json")
    if not summary_json:
        raise ToolArgumentError("summary_json or summary is required")
    with open(str(summary_json), encoding="utf-8") as handle:
        return json.load(handle)


def config_from_arguments(arguments: dict, *, limit: Optional[int] = None) -> InvestigationConfig:
    env_file = arguments.get("env_file")
    config = InvestigationConfig(
        es_url=arguments.get("es_url") or os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        syslog_index=arguments.get("syslog_index") or os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"),
        trap_index=arguments.get("trap_index") or os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"),
        event_index=arguments.get("event_index") or os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*"),
        allowed_device_ips=None if arguments.get("allowed_device_ips") is None else tuple(str(item) for item in arguments.get("allowed_device_ips") if str(item).strip()),
        baseline_days=parse_days(arguments.get("baseline_days"), 7),
        before_minutes=int(arguments.get("before_minutes") or 30),
        after_minutes=int(arguments.get("after_minutes") or 30),
        env_file=env_file,
    )
    if limit is not None:
        config.limits = InvestigationLimits(
            candidates=min(limit, MAX_CANDIDATES),
            related_current_events=limit,
            historical_events=limit,
            related_traps=limit,
            topology_links=limit,
            ai_memory=min(limit, 10),
        )
    load_env_file(env_file)
    return config


def compact_tool_result(tool_name: str, payload: Any) -> dict:
    return {"ok": True, "tool_name": tool_name, "result": payload}


def investigate_candidates(arguments: dict) -> dict:
    limit = clamp_limit(arguments.get("limit") or arguments.get("max_candidates"), default=10, max_limit=MAX_CANDIDATES)
    summary = load_summary(arguments)
    config = config_from_arguments(arguments, limit=limit)
    config.limits = replace(config.limits, candidates=limit)
    return build_investigation_context(summary, config)


def get_related_events(arguments: dict) -> dict:
    require_any(arguments, ["event_type", "device_ip", "object_key"])
    limit = clamp_limit(arguments.get("limit"))
    config = config_from_arguments(arguments, limit=limit)
    start, end = parse_window(arguments)
    filters = [event_window_query(start, end)]
    should = []
    for field in ["event_type", "device_ip", "object_key"]:
        term = term_if_present(field, arguments.get(field))
        if term:
            should.append(term)
    docs = search_docs(
        config.es_url,
        config.event_index,
        bool_query(filters, should, 1),
        limit,
        sort=[{"event_count": {"order": "desc", "unmapped_type": "long"}}, {"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )
    return {
        "window_start": iso_z(start),
        "window_end": iso_z(end),
        "events": [compact_event(item) for item in docs],
    }


def get_device_history(arguments: dict) -> dict:
    device_ip = arguments.get("device_ip")
    device_name = arguments.get("device_name")
    if not device_ip and not device_name:
        raise ToolArgumentError("device_ip or device_name is required")
    limit = clamp_limit(arguments.get("limit"))
    days = parse_days(arguments.get("days"), 7)
    config = config_from_arguments(arguments, limit=limit)
    end = parse_time(arguments.get("window_end")) or utc_now()
    start = end - dt.timedelta(days=days)
    filters = [event_window_query(start, end)]
    if device_ip:
        filters.append({"term": {"device_ip": str(device_ip)}})
    elif device_name:
        filters.append({"term": {"device_name": str(device_name)}})
    event_type = arguments.get("event_type")
    if event_type:
        filters.append({"term": {"event_type": str(event_type)}})
    docs = search_docs(
        config.es_url,
        config.event_index,
        bool_query(filters),
        limit,
        sort=[{"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )
    return {
        "device_ip": device_ip,
        "device_name": device_name,
        "days": days,
        "window_start": iso_z(start),
        "window_end": iso_z(end),
        "events": [compact_event(item) for item in docs],
    }


def get_object_history(arguments: dict) -> dict:
    require_any(arguments, ["object_key", "event_type", "device_ip"])
    limit = clamp_limit(arguments.get("limit"))
    days = parse_days(arguments.get("days"), 7)
    config = config_from_arguments(arguments, limit=limit)
    end = parse_time(arguments.get("window_end")) or utc_now()
    start = end - dt.timedelta(days=days)
    filters = [event_window_query(start, end)]
    for field in ["event_type", "device_ip", "object_key"]:
        term = term_if_present(field, arguments.get(field))
        if term:
            filters.append(term)
    docs = search_docs(
        config.es_url,
        config.event_index,
        bool_query(filters),
        limit,
        sort=[{"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )
    return {
        "days": days,
        "window_start": iso_z(start),
        "window_end": iso_z(end),
        "events": [compact_event(item) for item in docs],
    }


def get_topology_context(arguments: dict) -> dict:
    require_any(arguments, ["device_ip", "device_name"])
    limit = clamp_limit(arguments.get("limit"), default=30)
    config = config_from_arguments(arguments, limit=limit)
    identity = {
        "candidate_type": "tool_lookup",
        "device_ip": arguments.get("device_ip"),
        "device_name": arguments.get("device_name"),
    }
    candidate = {"device_ip": arguments.get("device_ip"), "device_name": arguments.get("device_name"), "devices": arguments.get("devices") or []}
    return load_topology(identity, candidate, config)


def get_baseline(arguments: dict) -> dict:
    require_any(arguments, ["event_type", "device_ip", "object_key"])
    days = parse_days(arguments.get("baseline_days"), 7)
    config = config_from_arguments(arguments, limit=clamp_limit(arguments.get("limit"), default=20))
    end = parse_time(arguments.get("window_end")) or utc_now()
    start = parse_time(arguments.get("window_start")) or (end - dt.timedelta(hours=24))
    if start >= end:
        raise ToolArgumentError("window_start must be earlier than window_end")
    baseline_start = start - dt.timedelta(days=days)
    filters = []
    for field in ["event_type", "device_ip", "object_key"]:
        term = term_if_present(field, arguments.get(field))
        if term:
            filters.append(term)
    current_count = count_docs(config.es_url, config.event_index, bool_query([event_window_query(start, end)] + filters))
    historical_count = count_docs(config.es_url, config.event_index, bool_query([event_window_query(baseline_start, start)] + filters))
    baseline_avg = round((historical_count / days) * ((end - start).total_seconds() / 86400), 2)
    return {
        "window_start": iso_z(start),
        "window_end": iso_z(end),
        "baseline_start": iso_z(baseline_start),
        "baseline_end": iso_z(start),
        "baseline_days": days,
        "current_count": current_count,
        "historical_count": historical_count,
        "baseline_avg_for_window": baseline_avg,
        "delta": round(current_count - baseline_avg, 2),
    }


def compact_fault_record(item: dict) -> dict:
    return {
        "record_id": item.get("record_id"),
        "source_type": item.get("source_type"),
        "knowledge_kind": item.get("knowledge_kind"),
        "source_file": item.get("source_file"),
        "report_file": item.get("report_file"),
        "occurred_date": item.get("occurred_date"),
        "service": item.get("service"),
        "area": item.get("area"),
        "canonical_symptom": item.get("canonical_symptom"),
        "canonical_symptom_label": item.get("canonical_symptom_label"),
        "knowledge_value": item.get("knowledge_value"),
        "knowledge_score": item.get("knowledge_score"),
        "title": item.get("knowledge_title") or item.get("title") or (item.get("knowledge_content") or item.get("fault_content") or "")[:80],
        "knowledge_content": (item.get("knowledge_content") or "")[:700],
        "fault_content": (item.get("fault_content") or item.get("knowledge_content") or "")[:500],
        "root_cause": (item.get("root_cause") or "")[:500],
        "investigation_steps": (item.get("investigation_steps") or "")[:800],
        "fix_method": (item.get("fix_method") or item.get("handling_result") or "")[:800],
        "prevention": (item.get("prevention") or "")[:500],
    }


def compact_fault_topic(item: dict) -> dict:
    return {
        "topic_key": item.get("topic_key"),
        "topic_label": item.get("topic_label"),
        "topic_source": item.get("topic_source"),
        "service": item.get("service"),
        "canonical_symptom": item.get("canonical_symptom"),
        "total_count": item.get("total_count"),
        "formal_count": item.get("formal_count"),
        "duty_count": item.get("duty_count"),
        "reference_count": item.get("reference_count"),
        "aggregate_only_count": item.get("aggregate_only_count"),
        "first_seen": item.get("first_seen"),
        "last_seen": item.get("last_seen"),
        "top_actions": item.get("top_actions") or [],
        "top_areas": item.get("top_areas") or [],
        "representative_cases": (item.get("representative_cases") or [])[:3],
    }


def infer_fault_kb_query_hints(query_text: str) -> dict[str, str]:
    text = query_text.lower()
    if any(key in text for key in ["测速", "带宽", "速率", "上行", "下行", "网速", "千兆", "百兆", "不达标"]):
        return {"service": "broadband", "canonical_symptom": "broadband_speed_issue"}
    if "点8" in text or "点 8" in text:
        return {"service": "tv", "canonical_symptom": "dot8_stutter_or_failure"}
    if any(key in text for key in ["回看", "回放"]):
        return {"service": "tv", "canonical_symptom": "replay_fault"}
    if "点播" in text or "vod" in text:
        return {"service": "tv", "canonical_symptom": "vod_fault"}
    if "黑屏" in text:
        return {"service": "tv"}
    if any(key in text for key in ["宽带", "拨号", "丢包", "掉线", "光猫", "路由器"]):
        return {"service": "broadband"}
    if any(key in text for key in ["机顶盒", "电视", "频道", "dvb", "ipqam", "olt", "eoc"]):
        return {"service": "tv"}
    return {}


def query_expansion_terms(query_text: str, canonical_symptom: str) -> str:
    text = query_text
    expansions = {
        "broadband_speed_issue": "测速 带宽 速率 上行 下行 网速 不达标 直连 光猫 路由器 网卡 千兆 百兆",
        "dot8_stutter_or_failure": "点8 卡顿 黑屏 加载 访问 OLT 策略 地址段 机顶盒",
        "replay_fault": "回看 回放 黑屏 卡顿 马赛克 无声音 CDN 录制",
        "vod_fault": "点播 VOD 卡顿 黑屏 加载 IPQAM 频点",
    }
    extra = expansions.get(canonical_symptom, "")
    return " ".join(f"{text} {extra}".split()) if extra else text


def search_fault_kb(arguments: dict) -> dict:
    query_text = str(arguments.get("query") or "").strip()
    if not query_text:
        raise ToolArgumentError("query is required")
    limit = clamp_limit(arguments.get("limit"), default=8, max_limit=20)
    es_url = arguments.get("es_url") or os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
    hints = infer_fault_kb_query_hints(query_text)
    service = str(arguments.get("service") or hints.get("service") or "").strip()
    explicit_canonical_symptom = str(arguments.get("canonical_symptom") or "").strip()
    canonical_symptom = explicit_canonical_symptom or str(hints.get("canonical_symptom") or "").strip()
    include_low_value = parse_tool_bool(arguments.get("include_low_value"))
    include_noise = parse_tool_bool(arguments.get("include_noise"))
    source_scope = str(arguments.get("source_scope") or "all").strip().lower()
    expanded_query = query_expansion_terms(query_text, canonical_symptom)

    filters = []
    if service:
        filters.append({"term": {"service": service}})
    if explicit_canonical_symptom:
        filters.append({"term": {"canonical_symptom": explicit_canonical_symptom}})
    value_terms = ["reference", "aggregate_only"]
    if include_low_value:
        value_terms.append("low_value")
    if include_noise:
        value_terms.append("noise")
    filters.append({"terms": {"knowledge_value": value_terms}})

    should = [
        {
            "multi_match": {
                "query": query_text,
                "fields": [
                    "title^4",
                    "knowledge_title^4",
                    "canonical_symptom_label^3",
                    "knowledge_content^4",
                    "fault_content^3",
                    "root_cause^3",
                    "fix_method^3",
                    "handling_result^2",
                    "investigation_steps^2",
                    "prevention",
                    "embedding_text^2",
                    "report_text",
                ],
                "type": "best_fields",
            }
        },
        {
            "multi_match": {
                "query": expanded_query,
                "fields": ["knowledge_content^3", "fault_content^2", "handling_result^2", "embedding_text^2", "knowledge_title^2", "title", "report_text"],
                "type": "best_fields",
            }
        },
    ]
    if canonical_symptom:
        should.append({"term": {"canonical_symptom": {"value": canonical_symptom, "boost": 8}}})
    if service:
        should.append({"term": {"service": {"value": service, "boost": 2}}})
    record_query = {"bool": {"filter": filters, "should": should, "minimum_should_match": 1}}
    record_source = [
        "record_id",
        "source_type",
        "knowledge_kind",
        "source_file",
        "report_file",
        "occurred_date",
        "service",
        "area",
        "canonical_symptom",
        "canonical_symptom_label",
        "knowledge_value",
        "knowledge_score",
        "knowledge_title",
        "knowledge_content",
        "title",
        "fault_content",
        "root_cause",
        "investigation_steps",
        "fix_method",
        "handling_result",
        "prevention",
    ]
    formal_index = arguments.get("formal_index") or os.getenv("FAULT_KB_INDEX", FAULT_KB_INDEX)
    duty_index = arguments.get("duty_index") or os.getenv("DUTY_REPAIR_INDEX", DUTY_REPAIR_INDEX)
    record_sort = [{"_score": {"order": "desc"}}, {"knowledge_score": {"order": "desc", "unmapped_type": "float"}}, {"occurred_time": {"order": "desc", "unmapped_type": "date"}}]

    def run_record_search(index: str, size: int) -> list[dict]:
        if size <= 0:
            return []
        return search_docs(es_url, index, record_query, size, sort=record_sort, source=record_source)

    if source_scope == "formal":
        raw_records = run_record_search(formal_index, limit)
    elif source_scope == "repair":
        raw_records = run_record_search(duty_index, limit)
    elif canonical_symptom == "broadband_speed_issue":
        raw_records = run_record_search(duty_index, limit)
    else:
        formal_records = run_record_search(formal_index, min(3, limit))
        duty_records = run_record_search(duty_index, limit - len(formal_records))
        raw_records = formal_records + duty_records

    topic_filters = []
    if service:
        topic_filters.append({"term": {"service": service}})
    if canonical_symptom:
        topic_filters.append({"term": {"canonical_symptom": canonical_symptom}})
    topic_query = {
        "bool": {
            "filter": topic_filters,
            "should": [
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": ["topic_label^4", "suggested_query^3", "representative_cases.title^2"],
                    }
                }
            ],
            "minimum_should_match": 1,
        }
    }
    topic_index = arguments.get("topic_index") or os.getenv("FAULT_KB_AGGREGATE_INDEX", FAULT_TOPIC_INDEX)
    raw_topics = search_docs(
        es_url,
        topic_index,
        topic_query,
        min(limit, 5),
        sort=[{"reference_count": {"order": "desc", "unmapped_type": "long"}}, {"total_count": {"order": "desc", "unmapped_type": "long"}}],
        source=[
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
    return {
        "query": query_text,
        "filters": {"service": service or None, "canonical_symptom": canonical_symptom or None, "knowledge_value": value_terms},
        "source_scope": source_scope,
        "records": [compact_fault_record(item) for item in raw_records],
        "topics": [compact_fault_topic(item) for item in raw_topics],
    }


AI_TOOLS: Dict[str, Callable[[dict], dict]] = {
    "investigate_candidates": investigate_candidates,
    "get_related_events": get_related_events,
    "get_device_history": get_device_history,
    "get_object_history": get_object_history,
    "get_topology_context": get_topology_context,
    "get_baseline": get_baseline,
    "search_fault_kb": search_fault_kb,
}


def object_schema(properties: dict, required: Optional[List[str]] = None) -> dict:
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def get_tool_schemas() -> List[dict]:
    shared_runtime = {
        "es_url": {"type": "string", "description": "Elasticsearch URL. Defaults to runtime ELASTICSEARCH_URL."},
        "env_file": {"type": "string", "description": "Optional runtime env file for MySQL topology and memory lookup."},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": "Maximum compact records to return."},
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "investigate_candidates",
                "description": "Primary bounded investigation tool. Expands current_window_summary candidates into compact evidence packages.",
                "parameters": object_schema(
                    {
                        "summary_json": {"type": "string", "description": "Path to current_window_summary JSON."},
                        "max_candidates": {"type": "integer", "minimum": 1, "maximum": MAX_CANDIDATES},
                        **shared_runtime,
                    },
                    ["summary_json"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_related_events",
                "description": "Get compact related alarm events by event_type, device_ip, or object_key within a bounded time window.",
                "parameters": object_schema({"event_type": {"type": "string"}, "device_ip": {"type": "string"}, "object_key": {"type": "string"}, "window_start": {"type": "string"}, "window_end": {"type": "string"}, **shared_runtime}),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_device_history",
                "description": "Get compact recent alarm event history for one device, optionally filtered by event_type.",
                "parameters": object_schema({"device_ip": {"type": "string"}, "device_name": {"type": "string"}, "event_type": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": MAX_DAYS}, "window_end": {"type": "string"}, **shared_runtime}),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_object_history",
                "description": "Get compact history for a bounded object/event/device combination.",
                "parameters": object_schema({"object_key": {"type": "string"}, "event_type": {"type": "string"}, "device_ip": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": MAX_DAYS}, "window_end": {"type": "string"}, **shared_runtime}),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_topology_context",
                "description": "Get compact topology context for one device from controlled MySQL metadata lookup.",
                "parameters": object_schema({"device_ip": {"type": "string"}, "device_name": {"type": "string"}, "devices": {"type": "array", "items": {"type": "string"}}, **shared_runtime}),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_baseline",
                "description": "Compare current count with bounded historical baseline for event_type, device_ip, and/or object_key.",
                "parameters": object_schema({"event_type": {"type": "string"}, "device_ip": {"type": "string"}, "object_key": {"type": "string"}, "window_start": {"type": "string"}, "window_end": {"type": "string"}, "baseline_days": {"type": "integer", "minimum": 1, "maximum": MAX_DAYS}, **shared_runtime}),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_fault_kb",
                "description": "Search formal fault reports, valuable duty repair records, and topic aggregates for fault knowledge-base Q&A.",
                "parameters": object_schema(
                    {
                        "query": {"type": "string", "description": "Natural language fault symptom, device/service, error, or handling question."},
                        "service": {"type": "string", "description": "Optional normalized service such as tv, broadband, or other."},
                        "canonical_symptom": {"type": "string", "description": "Optional normalized symptom key."},
                        "include_low_value": {"type": "boolean", "description": "Include weak single-row records in addition to reference and aggregate_only."},
                        "include_noise": {"type": "boolean", "description": "Include routine lookup/noise records when explicitly needed for statistics."},
                        "source_scope": {"type": "string", "description": "Record source scope: all, formal, or repair."},
                        "formal_index": {"type": "string", "description": "Optional formal report index override."},
                        "duty_index": {"type": "string", "description": "Optional duty repair index override."},
                        "topic_index": {"type": "string", "description": "Optional topic aggregate index override."},
                        **shared_runtime,
                    },
                    ["query"],
                ),
            },
        },
    ]


def execute_ai_tool(tool_name: str, arguments: dict) -> dict:
    LOGGER.info("Executing AI tool: %s", tool_name)
    if not isinstance(arguments, dict):
        return {"ok": False, "tool_name": tool_name, "error": {"type": "invalid_arguments", "message": "arguments must be an object"}}
    tool = AI_TOOLS.get(tool_name)
    if tool is None:
        LOGGER.warning("Unknown AI tool requested: %s", tool_name)
        return {"ok": False, "tool_name": tool_name, "error": {"type": "unknown_tool", "message": "unknown tool: %s" % tool_name}}
    try:
        result = tool(arguments)
        return compact_tool_result(tool_name, result)
    except ToolArgumentError as exc:
        LOGGER.warning("AI tool argument error for %s: %s", tool_name, exc)
        return {"ok": False, "tool_name": tool_name, "error": {"type": "invalid_arguments", "message": str(exc)}}
    except Exception as exc:  # pragma: no cover - defensive boundary for Agent calls
        LOGGER.exception("AI tool execution failed: %s", tool_name)
        return {"ok": False, "tool_name": tool_name, "error": {"type": "execution_error", "message": str(exc)}}
