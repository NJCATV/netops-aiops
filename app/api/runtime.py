"""Realtime runtime data APIs backed by Elasticsearch."""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterable, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from aiops.mib.trap_enrichment import enrich_traps
from app.api.auth import db_session_factory, login_required
from app.db import session_scope
from app.models import PlatformDeviceScope


runtime_bp = Blueprint("runtime", __name__, url_prefix="/api")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def es_url() -> str:
    return os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200").rstrip("/")


def es_request(method: str, path: str, body: Optional[dict] = None) -> dict:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(es_url() + path, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("Elasticsearch request failed: %s %s" % (exc.code, detail)) from exc
    return json.loads(payload) if payload else {}


def clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(number, max_value))


def hours_window(hours: int, field: str = "@timestamp") -> dict:
    end = utc_now()
    start = end - dt.timedelta(hours=hours)
    return {"range": {field: {"gte": iso_z(start), "lt": iso_z(end)}}}


def event_window(hours: int) -> dict:
    return {
        "bool": {
            "should": [hours_window(hours, "@timestamp"), hours_window(hours, "first_seen"), hours_window(hours, "last_seen")],
            "minimum_should_match": 1,
        }
    }


def bool_query(filters: list[dict]) -> dict:
    return {"bool": {"filter": filters}} if filters else {"match_all": {}}


def term_filter(field: str, value: Any) -> Optional[dict]:
    text = str(value or "").strip()
    if not text:
        return None
    return {"term": {field: text}}


def phrase_filter(field: str, value: Any) -> Optional[dict]:
    text = str(value or "").strip()
    if not text:
        return None
    return {"match_phrase": {field: text}}


def search_docs(index: str, query: dict, limit: int, sort_field: str, source: list[str], offset: int = 0, sort_order: str = "desc") -> list[dict]:
    body = {
        "from": offset,
        "size": limit,
        "track_total_hits": True,
        "query": query,
        "sort": [{sort_field: {"order": sort_order, "unmapped_type": "date"}}],
        "_source": source,
    }
    response = es_request("POST", "/%s/_search" % index, body)
    return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]


def search_docs_with_total(index: str, query: dict, limit: int, sort_field: str, source: list[str], offset: int = 0, sort_order: str = "desc") -> tuple[list[dict], int]:
    body = {
        "from": offset,
        "size": limit,
        "track_total_hits": True,
        "query": query,
        "sort": [{sort_field: {"order": sort_order, "unmapped_type": "date"}}],
        "_source": source,
    }
    response = es_request("POST", "/%s/_search" % index, body)
    hits = response.get("hits", {})
    total_raw = hits.get("total", 0)
    total = int(total_raw.get("value", 0) if isinstance(total_raw, dict) else total_raw)
    return [hit.get("_source", {}) for hit in hits.get("hits", [])], total


def count_docs(index: str, query: dict) -> int:
    response = es_request("POST", "/%s/_count" % index, {"query": query})
    return int(response.get("count", 0))


def latest_doc(index: str, source: list[str], sort_field: str, query: Optional[dict] = None) -> Optional[dict]:
    docs = search_docs(index, query or {"match_all": {}}, 1, sort_field, source)
    return docs[0] if docs else None


def platform_device_ips(current_user) -> Optional[tuple[str, ...]]:
    """AIOps is a global operational dataset; page permission is its access boundary.

    The platform's regional inventory currently contains OLT/CMTS devices, while
    AIOps observes metro routers, switches and collectors. Applying the regional
    inventory as an ES allow-list therefore hides valid AIOps data. Authenticated
    callers are still gated by the signed platform identity and BFF permissions.
    """
    return None


def platform_region_filter(current_user, fields: list[str]) -> Optional[dict]:
    """Translate the signed platform region scope into a bounded device-IP ES filter."""
    unique_ips = platform_device_ips(current_user)
    if unique_ips is None:
        return None
    if not unique_ips:
        return {"match_none": {}}
    return {
        "bool": {
            "should": [{"terms": {field: list(unique_ips)}} for field in fields],
            "minimum_should_match": 1,
        }
    }


def append_platform_scope(filters: list[dict], current_user, fields: list[str]) -> None:
    scope = platform_region_filter(current_user, fields)
    if scope is not None:
        filters.append(scope)


def compact_message(value: Any, max_length: int = 600) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_length] + ("..." if len(text) > max_length else "")


def compact_syslog(row: dict) -> dict:
    return {
        "timestamp": row.get("@timestamp") or row.get("log_time"),
        "device_name": row.get("device_name"),
        "device_ip": row.get("device_ip"),
        "module": row.get("module"),
        "severity": row.get("severity"),
        "event_code": row.get("event_code"),
        "event_family": row.get("event_family"),
        "raw_message": compact_message(row.get("raw_message")),
    }


def compact_link(link: Any) -> Optional[dict]:
    if not isinstance(link, dict):
        return None
    return {
        "link_name": link.get("link_name"),
        "link_state": link.get("link_state"),
        "source_device": link.get("source_device"),
        "source_interface": link.get("source_interface"),
        "target_device": link.get("target_device"),
        "target_interface": link.get("target_interface"),
        "match_source": link.get("match_source"),
    }


def compact_trap(row: dict) -> dict:
    return {
        "timestamp": row.get("@timestamp"),
        "trap_sender_ip": row.get("trap_sender_ip") or row.get("collector_source_ip") or row.get("source_ip"),
        "managed_device_name": row.get("managed_device_name"),
        "managed_device_ip": row.get("managed_device_ip"),
        "managed_object_name": row.get("managed_object_name"),
        "managed_object_address": row.get("managed_object_address"),
        "endpoint_device_names": row.get("endpoint_device_names") or [],
        "endpoint_interfaces": row.get("endpoint_interfaces") or [],
        "matched_link": compact_link(row.get("matched_link")),
        "topology_match": bool(row.get("topology_match")),
        "topology_correlation_status": row.get("topology_correlation_status"),
        "trap_oid": row.get("trap_oid"),
        "trap_oid_name": row.get("trap_oid_name"),
        "trap_oid_module": row.get("trap_oid_module"),
        "alarm_name": row.get("alarm_name"),
        "alarm_severity": row.get("alarm_severity"),
        "alarm_lifecycle_status": row.get("alarm_lifecycle_status"),
        "alarm_vendor": row.get("alarm_vendor"),
        "alarm_definition_matched": row.get("alarm_definition_matched"),
        "mib_translated": row.get("mib_translated"),
        "mib_lookup_source": row.get("mib_lookup_source"),
        "raw_message": compact_message(row.get("raw_message")),
    }


def compact_alarm_event(row: dict) -> dict:
    return {
        "event_id": row.get("event_id"),
        "event_type": row.get("event_type"),
        "event_family": row.get("event_family"),
        "device_name": row.get("device_name"),
        "device_ip": row.get("device_ip"),
        "object_key": row.get("object_key"),
        "event_status": row.get("event_status"),
        "event_count": row.get("event_count"),
        "first_seen": row.get("first_seen"),
        "last_seen": row.get("last_seen"),
        "severity_max": row.get("severity_max"),
        "event_summary": row.get("event_summary"),
    }


def error_json(exc: Exception, status: int = 500):
    return jsonify({"ok": False, "error": {"message": str(exc)}}), status


@runtime_bp.get("/runtime/overview")
@login_required
def runtime_overview(current_user):
    try:
        requested_hours = clamp_int(request.args.get("hours"), 24, 1, 168)
        windows = sorted({1, 3, 24, requested_hours})
        windows_data = []
        for hours in windows:
            syslog_filters = [hours_window(hours)]
            trap_filters = [hours_window(hours)]
            event_filters = [event_window(hours)]
            append_platform_scope(syslog_filters, current_user, ["device_ip"])
            append_platform_scope(trap_filters, current_user, ["managed_device_ip", "device_ip", "source_ip", "trap_sender_ip"])
            append_platform_scope(event_filters, current_user, ["device_ip"])
            windows_data.append(
                {
                    "hours": hours,
                    "syslog_parsed": count_docs("jscn-aiops-syslog-parsed-*", bool_query(syslog_filters)),
                    "trap_raw": count_docs("jscn-aiops-trap-raw-*", bool_query(trap_filters)),
                    "alarm_events": count_docs("jscn-aiops-alarm-events-*", bool_query(event_filters)),
                }
            )
        syslog_scope: list[dict] = []
        event_scope: list[dict] = []
        append_platform_scope(syslog_scope, current_user, ["device_ip"])
        append_platform_scope(event_scope, current_user, ["device_ip"])
        latest_syslog = latest_doc("jscn-aiops-syslog-parsed-*", ["@timestamp", "device_name", "device_ip", "event_code"], "@timestamp", bool_query(syslog_scope))
        latest_alarm = latest_doc("jscn-aiops-alarm-events-*", ["@timestamp", "first_seen", "last_seen", "event_type", "device_name", "device_ip", "object_key"], "last_seen", bool_query(event_scope))
        return jsonify(
            {
                "ok": True,
                "hours": requested_hours,
                "windows": windows_data,
                "latest_syslog": latest_syslog,
                "latest_alarm_event": latest_alarm,
            }
        )
    except Exception as exc:
        return error_json(exc)


@runtime_bp.get("/runtime/freshness")
@login_required
def runtime_freshness(current_user):
    try:
        syslog_scope: list[dict] = []
        event_scope: list[dict] = []
        append_platform_scope(syslog_scope, current_user, ["device_ip"])
        append_platform_scope(event_scope, current_user, ["device_ip"])
        latest_syslog = latest_doc("jscn-aiops-syslog-parsed-*", ["@timestamp", "device_name", "device_ip", "event_code"], "@timestamp", bool_query(syslog_scope))
        latest_alarm = latest_doc("jscn-aiops-alarm-events-*", ["last_seen", "event_type", "device_name", "device_ip", "object_key"], "last_seen", bool_query(event_scope))
        syslog_time = parse_time((latest_syslog or {}).get("@timestamp"))
        alarm_time = parse_time((latest_alarm or {}).get("last_seen"))
        lag_seconds = None
        if syslog_time and alarm_time:
            lag_seconds = round((syslog_time - alarm_time).total_seconds(), 3)
        return jsonify(
            {
                "ok": True,
                "latest_syslog_at": iso_z(syslog_time) if syslog_time else None,
                "latest_alarm_event_at": iso_z(alarm_time) if alarm_time else None,
                "alarm_lag_seconds": lag_seconds,
                "is_fresh": lag_seconds is not None and lag_seconds <= 900,
                "latest_syslog": latest_syslog,
                "latest_alarm_event": latest_alarm,
            }
        )
    except Exception as exc:
        return error_json(exc)


@runtime_bp.get("/syslog/latest")
@login_required
def latest_syslog(current_user):
    try:
        limit = clamp_int(request.args.get("limit"), 100, 1, 500)
        offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
        filters: list[dict] = []
        start = parse_time(request.args.get("start"))
        end = parse_time(request.args.get("end"))
        if start or end:
            range_filter: dict[str, Any] = {}
            if start:
                range_filter["gte"] = iso_z(start)
            if end:
                range_filter["lte"] = iso_z(end)
            filters.append({"range": {"@timestamp": range_filter}})
        else:
            filters.append(hours_window(clamp_int(request.args.get("hours"), 24, 1, 1680)))
        append_platform_scope(filters, current_user, ["device_ip"])
        for field in ["event_family", "event_code", "device_name", "device_ip", "module", "severity"]:
            item = phrase_filter(field, request.args.get(field))
            if item:
                filters.append(item)
        query_text = str(request.args.get("q") or "").strip()
        if query_text:
            filters.append(
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": ["device_name^4", "device_ip^4", "module^3", "event_family^3", "event_code^3", "severity", "raw_message"],
                        "type": "best_fields",
                    }
                }
            )
        sort_order = "asc" if str(request.args.get("order") or "desc").lower() == "asc" else "desc"
        docs, total = search_docs_with_total(
            "jscn-aiops-syslog-parsed-*",
            bool_query(filters),
            limit,
            "@timestamp",
            ["@timestamp", "log_time", "device_name", "device_ip", "module", "severity", "event_code", "event_family", "raw_message"],
            offset=offset,
            sort_order=sort_order,
        )
        return jsonify({"ok": True, "items": [compact_syslog(item) for item in docs], "limit": limit, "offset": offset, "total": total, "order": sort_order})
    except Exception as exc:
        return error_json(exc)


def trap_query_from_request(current_user=None) -> tuple[dict, int, int, str, str]:
    hours = clamp_int(request.args.get("hours"), 24, 1, 1680)
    limit = clamp_int(request.args.get("limit"), 100, 1, 500)
    offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
    filters: list[dict] = []
    start = parse_time(request.args.get("start"))
    end = parse_time(request.args.get("end"))
    if start or end:
        range_filter: dict[str, Any] = {}
        if start:
            range_filter["gte"] = iso_z(start)
        if end:
            range_filter["lte"] = iso_z(end)
        filters.append({"range": {"@timestamp": range_filter}})
    else:
        filters.append(hours_window(hours))
    if current_user is not None:
        append_platform_scope(filters, current_user, ["managed_device_ip", "device_ip", "source_ip", "trap_sender_ip"])
    for field in ["trap_oid", "trap_oid_name", "managed_device_name", "managed_device_ip", "trap_sender_ip", "alarm_name", "alarm_vendor", "alarm_lifecycle_status"]:
        item = phrase_filter(field, request.args.get(field))
        if item:
            filters.append(item)
    matched = str(request.args.get("alarm_definition_matched") or "").strip().lower()
    if matched in {"true", "false"}:
        filters.append({"term": {"alarm_definition_matched": matched == "true"}})
    mib = str(request.args.get("mib_translated") or "").strip().lower()
    if mib in {"true", "false"}:
        filters.append({"term": {"mib_translated": mib == "true"}})
    query_text = str(request.args.get("q") or "").strip()
    if query_text:
        filters.append(
            {
                "multi_match": {
                    "query": query_text,
                    "fields": ["alarm_name^4", "trap_oid^3", "trap_oid_name^3", "managed_device_name^3", "managed_device_ip^2", "managed_object_name^2", "trap_sender_ip", "raw_message"],
                    "type": "best_fields",
                }
            }
        )
    sort_order = "asc" if str(request.args.get("order") or "desc").lower() == "asc" else "desc"
    return bool_query(filters), limit, offset, sort_order, str(request.args.get("sort") or "@timestamp")


@runtime_bp.get("/trap/latest")
@login_required
def latest_trap(current_user):
    try:
        limit = clamp_int(request.args.get("limit"), 100, 1, 500)
        filters: list[dict] = []
        append_platform_scope(filters, current_user, ["managed_device_ip", "device_ip", "source_ip", "trap_sender_ip"])
        for field in ["trap_oid", "trap_oid_name", "managed_device_name", "managed_device_ip", "trap_sender_ip"]:
            item = term_filter(field, request.args.get(field))
            if item:
                filters.append(item)
        docs = search_docs(
            "jscn-aiops-trap-raw-*",
            bool_query(filters),
            limit,
            "@timestamp",
            [
                "@timestamp",
                "source_ip",
                "trap_sender_ip",
                "collector_source_ip",
                "snmp_agent_addr",
                "managed_device_name",
                "managed_device_ip",
                "device_name",
                "device_ip",
                "trap_oid",
                "trap_oid_name",
                "trap_oid_module",
                "alarm_name",
                "alarm_severity",
                "alarm_lifecycle_status",
                "alarm_vendor",
                "alarm_definition_matched",
                "mib_translated",
                "mib_lookup_source",
                "enterprise_oid",
                "specific_trap",
                "trap.varbinds",
                "raw_message",
            ],
        )
        enriched, _stats = enrich_traps(docs)
        return jsonify({"ok": True, "items": [compact_trap(item) for item in enriched], "limit": limit})
    except Exception as exc:
        return error_json(exc)


@runtime_bp.get("/trap")
@login_required
def trap_records(current_user):
    try:
        query, limit, offset, sort_order, sort_field = trap_query_from_request(current_user)
        sort_field = "@timestamp" if sort_field not in {"@timestamp"} else sort_field
        docs, total = search_docs_with_total(
            "jscn-aiops-trap-raw-*",
            query,
            limit,
            sort_field,
            [
                "@timestamp",
                "source_ip",
                "trap_sender_ip",
                "collector_source_ip",
                "snmp_agent_addr",
                "managed_device_name",
                "managed_device_ip",
                "device_name",
                "device_ip",
                "managed_object_name",
                "managed_object_address",
                "endpoint_device_names",
                "endpoint_interfaces",
                "matched_link",
                "topology_match",
                "topology_correlation_status",
                "trap_oid",
                "trap_oid_name",
                "trap_oid_module",
                "alarm_name",
                "alarm_severity",
                "alarm_lifecycle_status",
                "alarm_vendor",
                "alarm_definition_matched",
                "mib_translated",
                "mib_lookup_source",
                "raw_message",
            ],
            offset=offset,
            sort_order=sort_order,
        )
        enriched, _stats = enrich_traps(docs)
        return jsonify({"ok": True, "items": [compact_trap(item) for item in enriched], "limit": limit, "offset": offset, "total": total, "order": sort_order})
    except Exception as exc:
        return error_json(exc)


@runtime_bp.get("/alarm-events")
@login_required
def alarm_events(current_user):
    try:
        hours = clamp_int(request.args.get("hours"), 24, 1, 168)
        limit = clamp_int(request.args.get("limit"), 50, 1, 500)
        offset = clamp_int(request.args.get("offset"), 0, 0, 100000)
        sort_map = {"first_seen": "first_seen", "last_seen": "last_seen", "event_count": "event_count", "severity": "severity_max"}
        sort_field = sort_map.get(str(request.args.get("sort") or "last_seen"), "last_seen")
        sort_order = "asc" if str(request.args.get("order") or "desc").lower() == "asc" else "desc"
        filters: list[dict] = [event_window(hours)]
        append_platform_scope(filters, current_user, ["device_ip"])
        start = parse_time(request.args.get("start"))
        end = parse_time(request.args.get("end"))
        if start or end:
            range_filter: dict[str, Any] = {}
            if start:
                range_filter["gte"] = iso_z(start)
            if end:
                range_filter["lte"] = iso_z(end)
            filters.append({"range": {"last_seen": range_filter}})
        for field in ["event_type", "event_family", "event_status", "severity_max"]:
            item = phrase_filter(field, request.args.get(field))
            if item:
                filters.append(item)
        device_text = str(request.args.get("device") or "").strip()
        if device_text:
            filters.append(
                {
                    "bool": {
                        "should": [phrase_filter("device_name", device_text), phrase_filter("device_ip", device_text)],
                        "minimum_should_match": 1,
                    }
                }
            )
        object_filter = phrase_filter("object_key", request.args.get("object_key"))
        if object_filter:
            filters.append(object_filter)
        query_text = str(request.args.get("q") or "").strip()
        if query_text:
            filters.append(
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": ["event_type^3", "device_name^3", "device_ip^2", "object_key^2", "event_summary", "event_family"],
                        "type": "best_fields",
                    }
                }
            )
        docs, total = search_docs_with_total(
            "jscn-aiops-alarm-events-*",
            bool_query(filters),
            limit,
            sort_field,
            ["event_id", "event_type", "event_family", "device_name", "device_ip", "object_key", "event_status", "event_count", "first_seen", "last_seen", "severity_max", "event_summary"],
            offset=offset,
            sort_order=sort_order,
        )
        return jsonify({"ok": True, "hours": hours, "items": [compact_alarm_event(item) for item in docs], "limit": limit, "offset": offset, "total": total, "sort": sort_field, "order": sort_order})
    except Exception as exc:
        return error_json(exc)


@runtime_bp.get("/alarm-events/latest")
@login_required
def latest_alarm_events(current_user):
    return alarm_events()
