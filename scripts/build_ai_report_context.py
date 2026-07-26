#!/usr/bin/env python3
"""Build structured AI report context from Elasticsearch.

Task 12 prepares a model-ready JSON context from raw Syslog, Trap, and
alarm_events data. It does not call any AI service and does not write to MySQL.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import statistics
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

try:
    import pymysql
except ImportError:  # pragma: no cover - optional runtime enhancement
    pymysql = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional runtime enhancement
    load_dotenv = None


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


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\\t", " ").replace("\t", " ")
    return " ".join(text.split())


def load_env_file(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    candidates: List[pathlib.Path] = []
    if path:
        candidates.append(pathlib.Path(path))
    else:
        root = pathlib.Path(__file__).resolve().parents[1]
        candidates.extend([root / ".env", root / "deploy" / ".env"])
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate, override=False)


def range_query(start: dt.datetime, end: dt.datetime, field: str = "@timestamp") -> dict:
    return {"range": {field: {"gte": iso_z(start), "lt": iso_z(end)}}}


def total_hits(response: dict) -> int:
    total = response.get("hits", {}).get("total", {})
    if isinstance(total, dict):
        return int(total.get("value", 0))
    return int(total or 0)


def bucket_list(response: dict, name: str) -> List[dict]:
    return [{"key": item["key"], "count": item["doc_count"]} for item in response.get("aggregations", {}).get(name, {}).get("buckets", [])]


def terms_agg(field: str, size: int) -> dict:
    return {"terms": {"field": field, "size": size, "missing": "__missing__"}}


def sum_agg(field: str) -> dict:
    return {"sum": {"field": field}}


def search_aggs(es_url: str, index: str, query: dict, aggs: dict) -> dict:
    return es_request(es_url, "POST", "/%s/_search" % index, {"size": 0, "track_total_hits": True, "query": query, "aggs": aggs})


def search_docs(es_url: str, index: str, query: dict, size: int, sort: Optional[list] = None, source: Optional[list] = None) -> List[dict]:
    body: Dict[str, Any] = {"size": size, "track_total_hits": True, "query": query}
    if sort:
        body["sort"] = sort
    if source:
        body["_source"] = source
    response = es_request(es_url, "POST", "/%s/_search" % index, body)
    return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]


def count_docs(es_url: str, index: str, query: dict) -> int:
    response = es_request(es_url, "POST", "/%s/_count" % index, {"query": query})
    return int(response.get("count", 0))


def top_terms(es_url: str, index: str, query: dict, aggs: Dict[str, str], size: int) -> Dict[str, List[dict]]:
    response = search_aggs(es_url, index, query, {name: terms_agg(field, size) for name, field in aggs.items()})
    result = {}
    for name in aggs:
        result[name] = bucket_list(response, name)
    return result


def hourly_trend(es_url: str, index: str, query: dict) -> List[dict]:
    response = search_aggs(
        es_url,
        index,
        query,
        {
            "hourly": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": "1h",
                    "min_doc_count": 0,
                }
            }
        },
    )
    return [{"time": item["key_as_string"], "count": item["doc_count"]} for item in response.get("aggregations", {}).get("hourly", {}).get("buckets", [])]


def event_docs(es_url: str, event_index: str, query: dict, size: int) -> List[dict]:
    return search_docs(
        es_url,
        event_index,
        query,
        size,
        sort=[{"event_count": {"order": "desc", "unmapped_type": "long"}}, {"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=[
            "event_id",
            "event_type",
            "event_mode",
            "event_family",
            "device_ip",
            "device_name",
            "object_key",
            "first_seen",
            "last_seen",
            "duration_seconds",
            "event_count",
            "event_status",
            "severity_max",
            "event_summary",
            "raw_log_samples",
            "extracted_metrics",
            "username_count",
            "top_usernames",
            "total_failures",
            "user_focus_items",
            "slot",
            "queue_id",
            "interface",
            "error_code",
            "reason",
            "radius_server",
            "server_ip",
            "time_offset_avg",
            "time_offset_max",
            "threshold",
            "suppression_count",
            "resume_count",
            "up_down_count",
            "down_up_count",
            "flap_count",
        ],
    )


def compact_event(event: dict) -> dict:
    keys = [
        "event_id",
        "event_type",
        "event_mode",
        "device_ip",
        "device_name",
        "object_key",
        "first_seen",
        "last_seen",
        "event_count",
        "event_status",
        "severity_max",
        "event_summary",
        "extracted_metrics",
        "raw_log_samples",
        "username_count",
        "top_usernames",
        "total_failures",
        "user_focus_items",
        "slot",
        "queue_id",
        "interface",
        "error_code",
        "reason",
        "radius_server",
        "server_ip",
        "time_offset_avg",
        "time_offset_max",
        "threshold",
        "suppression_count",
        "resume_count",
        "up_down_count",
        "down_up_count",
        "flap_count",
    ]
    output = {key: event.get(key) for key in keys if event.get(key) not in (None, "", [])}
    if "raw_log_samples" in output:
        output["raw_log_samples"] = output["raw_log_samples"][:3]
    return output


def mysql_connect_from_env():
    if pymysql is None:
        return None
    password = os.getenv("MYSQL_PASSWORD")
    if not password:
        return None
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "13306")),
        user=os.getenv("MYSQL_USER", "aiops"),
        password=password,
        database=os.getenv("MYSQL_DATABASE", "jscn_aiops"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=20,
    )


def load_topology_context(device_terms: List[dict], device_name_terms: List[dict], event_samples: List[dict]) -> dict:
    target_names = {clean_text(item.get("device_name")) for item in event_samples if item.get("device_name")}
    target_names.update(clean_text(item.get("key")) for item in device_name_terms if item.get("key") and item.get("key") != "__missing__")
    target_ips = {clean_text(item.get("key")) for item in device_terms if item.get("key") and item.get("key") != "__missing__"}
    context = {
        "enabled": False,
        "source": "mysql",
        "device_table": "networkDevice",
        "link_table": "networkLinks",
        "matched_devices": [],
        "unmatched_event_device_ips": sorted(target_ips),
        "related_links": [],
        "device_role_counts": [],
        "device_status_counts": [],
        "link_state_counts": [],
        "notes": [],
    }
    connection = mysql_connect_from_env()
    if connection is None:
        context["notes"].append("MySQL topology enrichment skipped because pymysql or MYSQL_PASSWORD is unavailable.")
        return context
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, device_name, status, role, hierarchy, as_number, ip_address,
                       model, manufacturer, software_version, source, authorization
                FROM networkDevice
                """
            )
            devices = cursor.fetchall()
            cursor.execute(
                """
                SELECT link_id, link_name, link_state, source_device, source_interface,
                       source_ip, target_device, target_interface, target_ip, update_time
                FROM networkLinks
                """
            )
            links = cursor.fetchall()
    except Exception as exc:
        context["notes"].append("MySQL topology enrichment failed: %s" % exc)
        return context
    finally:
        connection.close()

    device_by_name = {clean_text(row.get("device_name")): row for row in devices if clean_text(row.get("device_name"))}
    event_ip_by_name = {clean_text(item.get("device_name")): item.get("device_ip") for item in event_samples if item.get("device_name")}
    matched_names = set()
    matched_devices = []
    for name in sorted(target_names):
        if name and name in device_by_name and name not in matched_names:
            row = device_by_name[name]
            matched_names.add(name)
            matched_devices.append(
                {
                    "event_device_name": name,
                    "event_device_ip": event_ip_by_name.get(name),
                    "inventory_ip_address": clean_text(row.get("ip_address")),
                    "status": clean_text(row.get("status")),
                    "role": clean_text(row.get("role")),
                    "hierarchy": clean_text(row.get("hierarchy")),
                    "as_number": clean_text(row.get("as_number")),
                    "model": clean_text(row.get("model")),
                    "manufacturer": clean_text(row.get("manufacturer")),
                    "software_version": clean_text(row.get("software_version")),
                    "source": clean_text(row.get("source")),
                    "authorization": clean_text(row.get("authorization")),
                }
            )

    related_links = []
    for row in links:
        source_device = clean_text(row.get("source_device"))
        target_device = clean_text(row.get("target_device"))
        if source_device in matched_names or target_device in matched_names:
            related_links.append(
                {
                    "link_id": row.get("link_id"),
                    "link_name": clean_text(row.get("link_name")),
                    "link_state": clean_text(row.get("link_state")),
                    "source_device": source_device,
                    "source_interface": clean_text(row.get("source_interface")),
                    "source_ip": clean_text(row.get("source_ip")),
                    "target_device": target_device,
                    "target_interface": clean_text(row.get("target_interface")),
                    "target_ip": clean_text(row.get("target_ip")),
                    "update_time": str(row.get("update_time") or ""),
                }
            )

    context.update(
        {
            "enabled": True,
            "inventory_device_total": len(devices),
            "inventory_link_total": len(links),
            "matched_device_count": len(matched_devices),
            "matched_devices": matched_devices[:50],
            "unmatched_event_device_ips": sorted(target_ips - {clean_text(item.get("event_device_ip")) for item in matched_devices}),
            "related_link_count": len(related_links),
            "related_links": related_links[:100],
            "device_role_counts": count_values(devices, "role"),
            "device_status_counts": count_values(devices, "status"),
            "link_state_counts": count_values(links, "link_state"),
        }
    )
    if not matched_devices:
        context["notes"].append("No current event device_name matched networkDevice.device_name.")
    return context


def count_values(rows: List[dict], field: str, limit: int = 20) -> List[dict]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = clean_text(row.get(field)) or "__missing__"
        counts[key] = counts.get(key, 0) + 1
    return [{"key": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]


def event_type_filter(event_type: str, start: dt.datetime, end: dt.datetime) -> dict:
    return {"bool": {"filter": [range_query(start, end), {"term": {"event_type": event_type}}]}}


def safe_avg(values: Iterable[float]) -> Optional[float]:
    data = [float(value) for value in values if value is not None]
    if not data:
        return None
    return round(statistics.mean(data), 2)


def sum_numeric(events: List[dict], field: str) -> float:
    total = 0.0
    for event in events:
        value = event.get(field)
        if value is None:
            value = (event.get("extracted_metrics") or {}).get(field)
        try:
            total += float(value or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def metric_value(response: dict, name: str) -> float:
    return round(float(response.get("aggregations", {}).get(name, {}).get("value", 0) or 0), 2)


def max_value(response: dict, name: str) -> float:
    value = response.get("aggregations", {}).get(name, {}).get("value")
    if value is None:
        return 0.0
    return round(float(value), 2)


def avg_value(response: dict, name: str) -> Optional[float]:
    value = response.get("aggregations", {}).get(name, {}).get("value")
    if value is None:
        return None
    return round(float(value), 2)


def event_type_overview(es_url: str, event_index: str, start: dt.datetime, end: dt.datetime, event_type: str, top_n: int, extra_aggs: Optional[dict] = None) -> dict:
    query = event_type_filter(event_type, start, end)
    aggs = {
        "total_raw_logs": sum_agg("event_count"),
        "top_devices": terms_agg("device_ip", top_n),
    }
    if extra_aggs:
        aggs.update(extra_aggs)
    response = search_aggs(es_url, event_index, query, aggs)
    return {
        "response": response,
        "event_count": total_hits(response),
        "raw_log_count": int(metric_value(response, "total_raw_logs")),
        "top_devices": bucket_list(response, "top_devices"),
    }


def top_from_event_field(events: List[dict], field: str, key_name: str = "key", count_name: str = "count", limit: int = 10) -> List[dict]:
    counts: Dict[str, int] = {}
    for event in events:
        values = event.get(field) or (event.get("extracted_metrics") or {}).get(field) or []
        if isinstance(values, dict):
            values = [values]
        for item in values:
            if not isinstance(item, dict):
                continue
            key = str(item.get(key_name) or item.get("username") or item.get("device_ip") or item.get("queue_id") or "__missing__")
            try:
                count = int(item.get(count_name, 1))
            except (TypeError, ValueError):
                count = 1
            counts[key] = counts.get(key, 0) + count
    return [{"key": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]


def current_event_summary(es_url: str, event_index: str, start: dt.datetime, end: dt.datetime, top_n: int) -> dict:
    query = range_query(start, end)
    response = search_aggs(
        es_url,
        event_index,
        query,
        {
            "top_event_type": terms_agg("event_type", top_n),
            "top_device_ip": terms_agg("device_ip", top_n),
            "top_device_name": terms_agg("device_name", top_n),
            "top_event_status": terms_agg("event_status", top_n),
            "total_event_count": sum_agg("event_count"),
        },
    )
    open_query = {"bool": {"filter": [query, {"term": {"event_status": "open"}}]}}
    recovered_query = {"bool": {"filter": [query, {"terms": {"event_status": ["recovered", "recovered_or_flapping", "flapping_or_recovered"]}}]}}
    key_events = event_docs(es_url, event_index, query, 20)
    return {
        "index": event_index,
        "total": total_hits(response),
        "compressed_raw_log_count": int(response.get("aggregations", {}).get("total_event_count", {}).get("value", 0)),
        "top_event_type": bucket_list(response, "top_event_type"),
        "top_device_ip": bucket_list(response, "top_device_ip"),
        "top_device_name": bucket_list(response, "top_device_name"),
        "top_event_status": bucket_list(response, "top_event_status"),
        "open_events": [compact_event(item) for item in event_docs(es_url, event_index, open_query, 20)],
        "recovered_or_flapping_events": [compact_event(item) for item in event_docs(es_url, event_index, recovered_query, 20)],
        "key_event_samples": [compact_event(item) for item in key_events],
    }


def baseline_summary(es_url: str, event_index: str, start: dt.datetime, end: dt.datetime, current_total: int, previous_total: int, top_n: int) -> dict:
    query = range_query(start, end)
    response = search_aggs(
        es_url,
        event_index,
        query,
        {
            "daily_events": {
                "date_histogram": {
                    "field": "@timestamp",
                    "calendar_interval": "1d",
                    "min_doc_count": 0,
                }
            },
            "event_type_daily": {
                "terms": {"field": "event_type", "size": top_n},
                "aggs": {"per_day": {"date_histogram": {"field": "@timestamp", "calendar_interval": "1d"}}},
            },
            "device_daily": {
                "terms": {"field": "device_ip", "size": top_n},
                "aggs": {"per_day": {"date_histogram": {"field": "@timestamp", "calendar_interval": "1d"}}},
            },
        },
    )
    daily = [{"date": item["key_as_string"][:10], "count": item["doc_count"]} for item in response.get("aggregations", {}).get("daily_events", {}).get("buckets", [])]
    baseline_days = max(1, len(daily))
    daily_avg = round(sum(item["count"] for item in daily) / baseline_days, 2)

    def daily_avg_terms(name: str) -> List[dict]:
        rows = []
        for bucket in response.get("aggregations", {}).get(name, {}).get("buckets", []):
            counts = [item["doc_count"] for item in bucket.get("per_day", {}).get("buckets", [])]
            rows.append({"key": bucket["key"], "total": bucket["doc_count"], "daily_avg": round(sum(counts) / max(1, baseline_days), 2)})
        return rows

    return {
        "window_start": iso_z(start),
        "window_end": iso_z(end),
        "daily_event_counts": daily,
        "daily_event_avg": daily_avg,
        "event_type_daily_avg": daily_avg_terms("event_type_daily"),
        "device_daily_avg": daily_avg_terms("device_daily"),
        "current_vs_previous_window": {
            "current_event_total": current_total,
            "previous_event_total": previous_total,
            "delta": current_total - previous_total,
        },
        "current_vs_7d_avg": {
            "current_event_total": current_total,
            "baseline_daily_avg": daily_avg,
            "delta": round(current_total - daily_avg, 2),
        },
    }


def special_analysis(es_url: str, event_index: str, start: dt.datetime, end: dt.datetime, top_n: int) -> dict:
    types = {
        "ppp": "PPP_AUTH_FAILURE",
        "ptp": "PTP_CLOCK_JITTER",
        "bfd": "BFD_FLAP",
        "optical": "OPTICAL_FAULT",
        "radius": "RADIUS_SERVER_ABNORMAL",
        "qos": "QOS_CONGESTION",
    }
    result: Dict[str, Any] = {}
    for name, event_type in types.items():
        events = event_docs(es_url, event_index, event_type_filter(event_type, start, end), 500)
        overview = event_type_overview(es_url, event_index, start, end, event_type, top_n)
        result[name] = {
            "event_type": event_type,
            "event_count": overview["event_count"],
            "raw_log_count": overview["raw_log_count"],
            "top_devices": overview["top_devices"],
            "samples": [compact_event(item) for item in events[:10]],
            "_events": events,
        }
    ppp_overview = event_type_overview(
        es_url,
        event_index,
        start,
        end,
        "PPP_AUTH_FAILURE",
        top_n,
        {"username_count_total": sum_agg("username_count"), "failure_total": sum_agg("total_failures")},
    )
    result["ppp"].update(
        {
            "failure_total": int(metric_value(ppp_overview["response"], "failure_total") or result["ppp"]["raw_log_count"]),
            "username_count_estimate": int(metric_value(ppp_overview["response"], "username_count_total")),
            "top_usernames": top_from_event_field(events_for(result, "ppp"), "top_usernames", limit=top_n),
            "user_focus_items": top_from_event_field(events_for(result, "ppp"), "user_focus_items", limit=top_n),
        }
    )
    ptp_overview = event_type_overview(
        es_url,
        event_index,
        start,
        end,
        "PTP_CLOCK_JITTER",
        top_n,
        {
            "suppression_total": sum_agg("suppression_count"),
            "resume_total": sum_agg("resume_count"),
            "time_offset_avg_all": {"avg": {"field": "time_offset_avg"}},
            "time_offset_max_all": {"max": {"field": "time_offset_max"}},
        },
    )
    ptp_events = events_for(result, "ptp")
    result["ptp"].update(
        {
            "suppression_total": int(metric_value(ptp_overview["response"], "suppression_total")),
            "resume_total": int(metric_value(ptp_overview["response"], "resume_total")),
            "time_offset_avg": avg_value(ptp_overview["response"], "time_offset_avg_all"),
            "time_offset_max": max_value(ptp_overview["response"], "time_offset_max_all"),
        }
    )
    bfd_overview = event_type_overview(
        es_url,
        event_index,
        start,
        end,
        "BFD_FLAP",
        top_n,
        {"up_down_total": sum_agg("up_down_count"), "down_up_total": sum_agg("down_up_count"), "flap_total": sum_agg("flap_count")},
    )
    bfd_events = events_for(result, "bfd")
    result["bfd"].update(
        {
            "up_down_total": int(metric_value(bfd_overview["response"], "up_down_total")),
            "down_up_total": int(metric_value(bfd_overview["response"], "down_up_total")),
            "flap_total": int(metric_value(bfd_overview["response"], "flap_total")),
            "flap_devices": top_simple(bfd_events, "device_ip", top_n),
        }
    )
    optical_events = events_for(result, "optical")
    result["optical"].update(
        {
            "open_or_unrecovered": len([event for event in optical_events if event.get("event_status") == "open"]),
            "recovered": len([event for event in optical_events if event.get("event_status") == "recovered"]),
            "top_interfaces": top_simple(optical_events, "interface", top_n),
            "top_error_codes": top_simple(optical_events, "error_code", top_n),
        }
    )
    radius_events = events_for(result, "radius")
    result["radius"].update({"top_radius_servers": top_simple(radius_events, "server_ip", top_n)})
    qos_events = events_for(result, "qos")
    result["qos"].update({"top_queues": top_simple(qos_events, "queue_id", top_n)})
    return result


def events_for(result: dict, name: str) -> List[dict]:
    return result.get(name, {}).get("_events", [])


def top_simple(events: List[dict], field: str, limit: int) -> List[dict]:
    counts: Dict[str, int] = {}
    for event in events:
        key = event.get(field) or "__missing__"
        counts[str(key)] = counts.get(str(key), 0) + 1
    return [{"key": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]


def strip_private_event_lists(result: dict) -> dict:
    for data in result.values():
        data.pop("_events", None)
    return result


def trap_signals(es_url: str, trap_index: str, event_index: str, start: dt.datetime, end: dt.datetime, top_n: int) -> dict:
    query = range_query(start, end)
    terms = top_terms(
        es_url,
        trap_index,
        query,
        {
            "top_trap_oid": "trap_oid.keyword",
            "top_source_ip": "source_ip.keyword",
            "top_enterprise_oid": "enterprise_oid.keyword",
        },
        top_n,
    )
    event_devices = {item["key"] for item in top_terms(es_url, event_index, query, {"top_device_ip": "device_ip"}, 100)["top_device_ip"]}
    correlated = []
    for item in terms["top_source_ip"]:
        if item["key"] in event_devices:
            correlated.append({"source_ip": item["key"], "trap_count": item["count"], "has_syslog_event": True})
    return {"total": count_docs(es_url, trap_index, query), "top": terms, "same_device_correlations": correlated[:top_n]}


def build_context(args: argparse.Namespace) -> dict:
    now = utc_now()
    current_start = now - dt.timedelta(hours=args.hours)
    previous_start = current_start - dt.timedelta(hours=args.hours)
    baseline_start = now - dt.timedelta(days=args.baseline_days)
    current_query = range_query(current_start, now)
    previous_query = {"bool": {"filter": [range_query(previous_start, current_start)]}}

    syslog_terms = top_terms(
        args.es_url,
        args.syslog_index,
        current_query,
        {
            "top_device_ip": "device_ip.keyword",
            "top_device_name": "device_name.keyword",
            "top_event_code": "event_code.keyword",
            "top_event_family": "event_family.keyword",
            "top_severity": "severity.keyword",
        },
        args.top_n,
    )
    syslog = {
        "index": args.syslog_index,
        "total": count_docs(args.es_url, args.syslog_index, current_query),
        "hourly_trend": hourly_trend(args.es_url, args.syslog_index, current_query),
    }
    syslog.update(syslog_terms)

    events = current_event_summary(args.es_url, args.event_index, current_start, now, args.top_n)
    current_event_total = events["total"]
    previous_event_total = count_docs(args.es_url, args.event_index, previous_query)
    special = special_analysis(args.es_url, args.event_index, current_start, now, args.top_n)

    context = {
        "metadata": {
            "generated_at": iso_z(now),
            "elasticsearch_url": args.es_url,
            "purpose": "AI report context only; no AI call performed.",
        },
        "window": {
            "hours": args.hours,
            "start": iso_z(current_start),
            "end": iso_z(now),
            "previous_start": iso_z(previous_start),
            "previous_end": iso_z(current_start),
            "baseline_days": args.baseline_days,
        },
        "current_window": {
            "syslog": syslog,
            "trap": trap_signals(args.es_url, args.trap_index, args.event_index, current_start, now, args.top_n),
            "alarm_events": events,
        },
        "baseline": baseline_summary(args.es_url, args.event_index, baseline_start, now, current_event_total, previous_event_total, args.top_n),
        "special_analysis": strip_private_event_lists(special),
        "topology_context": load_topology_context(events["top_device_ip"], events["top_device_name"], events["key_event_samples"]),
        "context_notes": [
            "AI should base conclusions on current_window, baseline comparisons, and key_event_samples.",
            "When topology_context.enabled is true, use networkDevice and networkLinks fields to infer affected device roles and neighboring links.",
            "Trap signals are not MIB-translated in this task.",
            "MySQL is used only for optional device/link metadata enrichment in this task.",
        ],
    }
    return context


def markdown_table(rows: List[dict], key_header: str) -> str:
    if not rows:
        return "| %s | Count |\n| --- | ---: |\n| (none) | 0 |" % key_header
    lines = ["| %s | Count |" % key_header, "| --- | ---: |"]
    for row in rows:
        lines.append("| `%s` | %s |" % (row.get("key"), row.get("count")))
    return "\n".join(lines)


def write_markdown(context: dict) -> str:
    window = context["window"]
    current = context["current_window"]
    baseline = context["baseline"]
    special = context["special_analysis"]
    topology = context.get("topology_context", {})
    lines = [
        "# Task 12 Sample AI Context Summary",
        "",
        "- Generated at: `%s`" % context["metadata"]["generated_at"],
        "- Window: `%s` to `%s`" % (window["start"], window["end"]),
        "- Hours: `%s`" % window["hours"],
        "- Baseline days: `%s`" % window["baseline_days"],
        "",
        "## Current Window",
        "",
        "- Syslog total: `%s`" % current["syslog"]["total"],
        "- Trap total: `%s`" % current["trap"]["total"],
        "- Alarm events total: `%s`" % current["alarm_events"]["total"],
        "- Compressed raw log count in events: `%s`" % current["alarm_events"]["compressed_raw_log_count"],
        "",
        "### Top Event Types",
        "",
        markdown_table(current["alarm_events"]["top_event_type"], "event_type"),
        "",
        "### Top Devices",
        "",
        markdown_table(current["alarm_events"]["top_device_ip"], "device_ip"),
        "",
        "## Baseline Comparison",
        "",
        "- Current events: `%s`" % baseline["current_vs_7d_avg"]["current_event_total"],
        "- 7-day daily average: `%s`" % baseline["current_vs_7d_avg"]["baseline_daily_avg"],
        "- Delta vs 7-day average: `%s`" % baseline["current_vs_7d_avg"]["delta"],
        "- Previous window events: `%s`" % baseline["current_vs_previous_window"]["previous_event_total"],
        "- Delta vs previous window: `%s`" % baseline["current_vs_previous_window"]["delta"],
        "",
        "## Special Analysis",
        "",
        "- PPP failures: `%s`, username estimate: `%s`" % (special["ppp"]["failure_total"], special["ppp"]["username_count_estimate"]),
        "- PTP suppression/resume: `%s / %s`, max offset: `%s`" % (special["ptp"]["suppression_total"], special["ptp"]["resume_total"], special["ptp"]["time_offset_max"]),
        "- BFD UP->DOWN / DOWN->UP: `%s / %s`" % (special["bfd"]["up_down_total"], special["bfd"]["down_up_total"]),
        "- Optical open/recovered: `%s / %s`" % (special["optical"]["open_or_unrecovered"], special["optical"]["recovered"]),
        "- Radius events: `%s`" % special["radius"]["event_count"],
        "- QoS events: `%s`" % special["qos"]["event_count"],
        "",
        "## Topology Context",
        "",
        "- Enabled: `%s`" % topology.get("enabled"),
        "- Inventory devices: `%s`" % topology.get("inventory_device_total", 0),
        "- Inventory links: `%s`" % topology.get("inventory_link_total", 0),
        "- Matched current event devices: `%s`" % topology.get("matched_device_count", 0),
        "- Related links: `%s`" % topology.get("related_link_count", 0),
        "",
        "## Key Event Samples",
        "",
    ]
    for event in current["alarm_events"]["key_event_samples"][:10]:
        lines.append("- `%s` `%s` `%s` count=`%s`: %s" % (event.get("event_type"), event.get("device_ip"), event.get("event_status"), event.get("event_count"), event.get("event_summary")))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--hours", type=int, default=int(os.getenv("AI_CONTEXT_HOURS", "24")))
    parser.add_argument("--baseline-days", type=int, default=int(os.getenv("AI_CONTEXT_BASELINE_DAYS", "7")))
    parser.add_argument("--top-n", type=int, default=int(os.getenv("AI_CONTEXT_TOP_N", "10")))
    parser.add_argument("--syslog-index", default=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"))
    parser.add_argument("--trap-index", default=os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"))
    parser.add_argument("--event-index", default=os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*"))
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE"))
    parser.add_argument("--out-dir", default=os.getenv("AI_CONTEXT_OUT_DIR", "/data/jscn-aiops/reports/context"))
    parser.add_argument("--sample-md", default=os.getenv("TASK12_SAMPLE_MD", "reports/task12/sample_ai_context.md"))
    args = parser.parse_args()
    load_env_file(args.env_file)

    context = build_context(args)
    generated = parse_time(context["metadata"]["generated_at"]) or utc_now()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / ("%s-ai-context.json" % generated.strftime("%Y%m%d-%H"))
    json_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = pathlib.Path(args.sample_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(write_markdown(context), encoding="utf-8")
    print(json.dumps({"context_json": str(json_path), "sample_markdown": str(md_path), "syslog_total": context["current_window"]["syslog"]["total"], "trap_total": context["current_window"]["trap"]["total"], "alarm_events_total": context["current_window"]["alarm_events"]["total"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
