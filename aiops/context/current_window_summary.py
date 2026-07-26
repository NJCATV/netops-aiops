"""Build compact current-window summaries for the lightweight AIOps agent.

The summary is intentionally smaller than the full Task 12 AI report context.
It keeps candidate incidents, anomalies, correlations, and data-quality notes,
but avoids passing bulk raw logs or calling any AI service.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

from aiops.mib.trap_enrichment import enrich_traps


LOGGER = logging.getLogger(__name__)

PREFERRED_OPEN_EVENT_TYPES = {
    "OPTICAL_FAULT",
    "INTERFACE_LINK",
    "BFD_FLAP",
    "RADIUS_SERVER_ABNORMAL",
    "PTP_CLOCK_JITTER",
    "QOS_CONGESTION",
}

CRITICAL_ALARM_EVENT_TYPES = {
    "INTERFACE_LINK",
    "OPTICAL_FAULT",
}

NON_CRITICAL_ALARM_EVENT_TYPES = {
    "BFD_FLAP",
    "PTP_CLOCK_JITTER",
    "PPP_AUTH_FAILURE",
    "QOS_CONGESTION",
    "RADIUS_SERVER_ABNORMAL",
}

CRITICAL_ALARM_KEYWORDS = (
    "down",
    "physical state down",
    "line protocol",
    "optical",
    "rx power",
    "los",
    "loss",
    "light",
    "fault",
    "board",
    "card",
    "slot",
    "hardware",
    "fan",
    "power",
    "temperature",
    "temp",
    "overheat",
    "链路",
    "接口",
    "光",
    "板卡",
    "单板",
    "风扇",
    "电源",
    "温度",
    "故障",
)

FLAPPING_EVENT_TYPES = {
    "BFD_FLAP",
    "INTERFACE_LINK",
    "OPTICAL_FAULT",
    "PTP_CLOCK_JITTER",
}

CORRELATION_EVENT_TYPES = {
    "RADIUS_SERVER_ABNORMAL",
    "BFD_FLAP",
    "QOS_CONGESTION",
    "PTP_CLOCK_JITTER",
    "OPTICAL_FAULT",
    "INTERFACE_LINK",
}


@dataclass
class SummaryLimits:
    critical_alarm_candidates: int = 50
    critical_traps: int = 20
    important_traps: int = 20
    open_incidents: int = 50
    baseline_deviations: int = 30
    new_anomalies: int = 30
    flapping_objects: int = 30
    multi_device_correlations: int = 30
    noise_candidates: int = 20
    event_scan_size: int = 5000
    trap_scan_size: int = 500


@dataclass
class SummaryConfig:
    es_url: str = "http://127.0.0.1:9200"
    hours: int = 7
    baseline_days: int = 7
    syslog_index: str = "jscn-aiops-syslog-parsed-*"
    trap_index: str = "jscn-aiops-trap-raw-*"
    event_index: str = "jscn-aiops-alarm-events-*"
    allowed_device_ips: Optional[Tuple[str, ...]] = None
    env_file: Optional[str] = None
    limits: SummaryLimits = field(default_factory=SummaryLimits)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def load_env_file(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    candidates: List[str] = []
    if path:
        candidates.append(path)
    else:
        candidates.extend([".env", "deploy/.env"])
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            load_dotenv(candidate, override=False)


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


def range_query(start: dt.datetime, end: dt.datetime, field: str = "@timestamp") -> dict:
    return {"range": {field: {"gte": iso_z(start), "lt": iso_z(end)}}}


def event_window_query(start: dt.datetime, end: dt.datetime) -> dict:
    """Match alarm events that are active or represented in the target window."""
    return {
        "bool": {
            "should": [
                range_query(start, end, "@timestamp"),
                range_query(start, end, "first_seen"),
                range_query(start, end, "last_seen"),
            ],
            "minimum_should_match": 1,
        }
    }


def device_scope_query(config: SummaryConfig, query: dict) -> dict:
    """Apply the platform device boundary to every ES query feeding the model."""
    if config.allowed_device_ips is None:
        return query
    if not config.allowed_device_ips:
        return {"match_none": {}}
    return {
        "bool": {
            "filter": [query],
            "should": [
                {"terms": {"device_ip": list(config.allowed_device_ips)}},
                {"terms": {"managed_device_ip": list(config.allowed_device_ips)}},
            ],
            "minimum_should_match": 1,
        }
    }


def total_hits(response: dict) -> int:
    total = response.get("hits", {}).get("total", {})
    if isinstance(total, dict):
        return int(total.get("value", 0))
    return int(total or 0)


def search_docs(
    es_url: str,
    index: str,
    query: dict,
    size: int,
    sort: Optional[list] = None,
    source: Optional[list] = None,
) -> List[dict]:
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


def search_aggs(es_url: str, index: str, query: dict, aggs: dict) -> dict:
    return es_request(
        es_url,
        "POST",
        "/%s/_search" % index,
        {"size": 0, "track_total_hits": True, "query": query, "aggs": aggs},
    )


def terms_agg(field: str, size: int) -> dict:
    return {"terms": {"field": field, "size": size, "missing": "__missing__"}}


def sum_agg(field: str) -> dict:
    return {"sum": {"field": field}}


def bucket_list(response: dict, name: str) -> List[dict]:
    return [{"key": item["key"], "count": item["doc_count"]} for item in response.get("aggregations", {}).get(name, {}).get("buckets", [])]


def value_count(response: dict, name: str) -> int:
    return int(response.get("aggregations", {}).get(name, {}).get("value", 0) or 0)


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\\t", " ").replace("\t", " ")
    return " ".join(text.split())


def normalize_key(parts: Iterable[Any]) -> str:
    values = [clean_text(part) or "__missing__" for part in parts]
    return "|".join(values)


def compact_sample_message(value: Any, max_length: int = 300) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def event_source_fields() -> List[str]:
    return [
        "event_id",
        "event_type",
        "event_mode",
        "event_family",
        "device_ip",
        "device_name",
        "object_key",
        "first_seen",
        "last_seen",
        "event_count",
        "event_status",
        "severity_max",
        "event_summary",
        "raw_log_samples",
        "extracted_metrics",
        "aggregation_key",
        "interface",
        "slot",
        "queue_id",
        "radius_server",
        "server_ip",
        "flap_count",
        "up_down_count",
        "down_up_count",
        "suppression_count",
        "resume_count",
        "error_code",
        "reason",
        "time_offset_avg",
        "time_offset_max",
    ]


def load_current_events(config: SummaryConfig, start: dt.datetime, end: dt.datetime) -> List[dict]:
    LOGGER.info("Loading current alarm events from %s", config.event_index)
    return search_docs(
        config.es_url,
        config.event_index,
        device_scope_query(config, event_window_query(start, end)),
        config.limits.event_scan_size,
        sort=[{"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )


def load_current_traps(config: SummaryConfig, start: dt.datetime, end: dt.datetime) -> List[dict]:
    LOGGER.info("Loading current trap samples from %s", config.trap_index)
    return search_docs(
        config.es_url,
        config.trap_index,
        device_scope_query(config, range_query(start, end)),
        config.limits.trap_scan_size,
        sort=[{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        source=[
            "@timestamp",
            "trap_oid",
            "trap_oid_name",
            "trap_oid_module",
            "trap_oid_type",
            "trap_oid_description",
            "mib_translated",
            "mib_lookup_source",
            "alarm_name",
            "alarm_severity",
            "alarm_lifecycle_status",
            "alarm_vendor",
            "alarm_enterprise_id",
            "alarm_enterprise_name",
            "alarm_fault_reason",
            "alarm_suggestion",
            "alarm_definition_matched",
            "alarm_lookup_source",
            "source_ip",
            "trap_sender_ip",
            "collector_source_ip",
            "snmp_agent_addr",
            "agent_addr",
            "managed_device_ip",
            "managed_device_name",
            "managed_object_name",
            "managed_object_address",
            "endpoint_device_names",
            "endpoint_interfaces",
            "topology_object_key",
            "object_identity_source",
            "object_identity_confidence",
            "topology_match",
            "matched_link",
            "related_device_roles",
            "topology_correlation_status",
            "device_identity_source",
            "device_identity_confidence",
            "device_ip",
            "device_name",
            "enterprise_oid",
            "specific_trap",
            "trap.varbinds",
            "raw_message",
            "severity",
            "level",
        ],
    )


def build_overview(config: SummaryConfig, start: dt.datetime, end: dt.datetime, events: List[dict]) -> dict:
    event_query = device_scope_query(config, event_window_query(start, end))
    event_aggs = search_aggs(
        config.es_url,
        config.event_index,
        event_query,
        {
            "compressed_raw_log_count": sum_agg("event_count"),
            "open_status": {"filter": {"term": {"event_status": "open"}}},
            "recovered_status": {"filter": {"terms": {"event_status": ["recovered", "recovered_or_flapping", "flapping_or_recovered"]}}},
            "flapping_status": {"filter": {"terms": {"event_status": ["flapping", "recovered_or_flapping", "flapping_or_recovered"]}}},
        },
    )
    return {
        "syslog_total": count_docs(config.es_url, config.syslog_index, device_scope_query(config, range_query(start, end))),
        "trap_total": count_docs(config.es_url, config.trap_index, device_scope_query(config, range_query(start, end))),
        "alarm_event_total": total_hits(event_aggs),
        "open_event_total": event_aggs.get("aggregations", {}).get("open_status", {}).get("doc_count", 0),
        "recovered_event_total": event_aggs.get("aggregations", {}).get("recovered_status", {}).get("doc_count", 0),
        "flapping_event_total": max(event_aggs.get("aggregations", {}).get("flapping_status", {}).get("doc_count", 0), len([event for event in events if event_flap_count(event) >= 2])),
        "compressed_raw_log_count": value_count(event_aggs, "compressed_raw_log_count"),
    }


def trap_time_bounds(items: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    values = [parse_time(item.get("@timestamp")) for item in items]
    values = [value for value in values if value]
    if not values:
        return None, None
    return iso_z(min(values)), iso_z(max(values))


def trap_group_identity(trap: dict) -> Tuple[str, str, str, str]:
    object_key = clean_text(trap.get("topology_object_key") or trap.get("managed_object_name"))
    matched_link = trap.get("matched_link") or {}
    matched_link_name = clean_text(matched_link.get("link_name")) if isinstance(matched_link, dict) else ""
    if object_key or matched_link_name:
        return (
            object_key or matched_link_name,
            matched_link_name or "__missing__",
            clean_text(trap.get("trap_oid")) or "__missing__",
            clean_text(trap.get("specific_trap")) or "__missing__",
        )
    return (
        clean_text(trap.get("managed_device_ip")) or "__missing__",
        clean_text(trap.get("managed_device_name")) or "__missing__",
        clean_text(trap.get("trap_oid")) or "__missing__",
        clean_text(trap.get("specific_trap")) or "__missing__",
    )


def build_trap_candidates(traps: List[dict], limits: SummaryLimits) -> Tuple[List[dict], List[dict], List[str]]:
    groups: Dict[Tuple[str, str, str, str], List[dict]] = defaultdict(list)
    severity_seen = False
    critical: List[dict] = []
    notes: List[str] = []
    for trap in traps:
        severity = clean_text(trap.get("severity") or trap.get("level")).lower()
        if severity:
            severity_seen = True
        groups[trap_group_identity(trap)].append(trap)
    rows = []
    for (_group_key, _matched_link_name, trap_oid, specific_trap), items in groups.items():
        first_seen, last_seen = trap_time_bounds(items)
        sample = next((item.get("raw_message") for item in items if item.get("raw_message")), "")
        sender_ips = sorted({clean_text(item.get("trap_sender_ip") or item.get("source_ip")) for item in items if clean_text(item.get("trap_sender_ip") or item.get("source_ip"))})
        identity_sources = Counter(clean_text(item.get("device_identity_source")) or "unknown" for item in items)
        identity_confidence = max(float(item.get("device_identity_confidence") or 0.0) for item in items)
        managed_device_ips = sorted({clean_text(item.get("managed_device_ip")) for item in items if clean_text(item.get("managed_device_ip"))})
        managed_device_names = sorted({clean_text(item.get("managed_device_name")) for item in items if clean_text(item.get("managed_device_name"))})
        object_names = sorted({clean_text(item.get("managed_object_name")) for item in items if clean_text(item.get("managed_object_name"))})
        object_addresses = sorted({clean_text(item.get("managed_object_address")) for item in items if clean_text(item.get("managed_object_address"))})
        endpoint_names: List[str] = []
        endpoint_interfaces: List[str] = []
        matched_link = next((item.get("matched_link") for item in items if item.get("matched_link")), None)
        related_device_roles = next((item.get("related_device_roles") for item in items if item.get("related_device_roles")), [])
        for item in items:
            for name in item.get("endpoint_device_names") or []:
                text = clean_text(name)
                if text and text not in endpoint_names:
                    endpoint_names.append(text)
            for interface in item.get("endpoint_interfaces") or []:
                text = clean_text(interface)
                if text and text not in endpoint_interfaces:
                    endpoint_interfaces.append(text)
        topology_statuses = Counter(clean_text(item.get("topology_correlation_status")) or "unknown" for item in items)
        row = {
            "alarm_name": next((clean_text(item.get("alarm_name")) for item in items if item.get("alarm_name")), None),
            "alarm_severity": next((clean_text(item.get("alarm_severity")) for item in items if item.get("alarm_severity")), None),
            "alarm_lifecycle_status": next((clean_text(item.get("alarm_lifecycle_status")) for item in items if item.get("alarm_lifecycle_status")), None),
            "alarm_vendor": next((clean_text(item.get("alarm_vendor")) for item in items if item.get("alarm_vendor")), None),
            "alarm_enterprise_name": next((clean_text(item.get("alarm_enterprise_name")) for item in items if item.get("alarm_enterprise_name")), None),
            "alarm_fault_reason": compact_sample_message(next((item.get("alarm_fault_reason") for item in items if item.get("alarm_fault_reason")), ""), 180) or None,
            "alarm_suggestion": compact_sample_message(next((item.get("alarm_suggestion") for item in items if item.get("alarm_suggestion")), ""), 180) or None,
            "alarm_definition_matched": any(bool(item.get("alarm_definition_matched")) for item in items),
            "alarm_lookup_source": next((clean_text(item.get("alarm_lookup_source")) for item in items if item.get("alarm_lookup_source")), None),
            "trap_oid": trap_oid,
            "trap_oid_name": next((clean_text(item.get("trap_oid_name")) for item in items if item.get("trap_oid_name")), None),
            "trap_oid_module": next((clean_text(item.get("trap_oid_module")) for item in items if item.get("trap_oid_module")), None),
            "trap_oid_type": next((clean_text(item.get("trap_oid_type")) for item in items if item.get("trap_oid_type")), None),
            "trap_oid_description": next((clean_text(item.get("trap_oid_description")) for item in items if item.get("trap_oid_description")), None),
            "mib_translated": any(bool(item.get("mib_translated")) for item in items),
            "mib_lookup_source": next((clean_text(item.get("mib_lookup_source")) for item in items if item.get("mib_lookup_source")), None),
            "source_ip": sender_ips[0] if len(sender_ips) == 1 else None,
            "trap_sender_ip": sender_ips[0] if len(sender_ips) == 1 else None,
            "trap_sender_ips": sender_ips[:10],
            "snmp_agent_addr": next((clean_text(item.get("snmp_agent_addr")) for item in items if item.get("snmp_agent_addr")), None),
            "managed_device_ip": managed_device_ips[0] if len(managed_device_ips) == 1 else None,
            "managed_device_name": managed_device_names[0] if len(managed_device_names) == 1 else None,
            "managed_device_ips": managed_device_ips[:10],
            "managed_device_names": managed_device_names[:10],
            "device_ip": managed_device_ips[0] if len(managed_device_ips) == 1 else None,
            "device_name": managed_device_names[0] if len(managed_device_names) == 1 else None,
            "managed_object_name": object_names[0] if len(object_names) == 1 else (object_names[:3] if object_names else None),
            "managed_object_address": object_addresses[0] if len(object_addresses) == 1 else (object_addresses[:3] if object_addresses else None),
            "endpoint_device_names": endpoint_names[:4],
            "endpoint_interfaces": endpoint_interfaces[:4],
            "topology_object_key": next((clean_text(item.get("topology_object_key")) for item in items if item.get("topology_object_key")), None),
            "object_identity_source": next((clean_text(item.get("object_identity_source")) for item in items if item.get("object_identity_source")), None),
            "object_identity_confidence": max(float(item.get("object_identity_confidence") or 0.0) for item in items),
            "device_identity_source": identity_sources.most_common(1)[0][0],
            "device_identity_confidence": identity_confidence,
            "topology_match": bool(matched_link),
            "matched_link": matched_link,
            "related_device_roles": related_device_roles[:4] if isinstance(related_device_roles, list) else [],
            "topology_correlation_status": topology_statuses.most_common(1)[0][0],
            "enterprise_oid": next((clean_text(item.get("enterprise_oid")) for item in items if item.get("enterprise_oid")), None),
            "specific_trap": specific_trap,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "count": len(items),
            "sample_message": compact_sample_message(sample),
            "candidate_source": "trap",
            "priority_reason": "Trap is included because upstream filtering keeps only critical or important Trap records.",
        }
        if row["alarm_name"]:
            row["display_name"] = "%s (%s)" % (row["alarm_name"], trap_oid)
            row["priority_reason"] = "Private alarm definition matched %s; Trap is upstream-filtered as critical or important." % row["alarm_name"]
        if row["trap_oid_name"]:
            row.setdefault("display_name", "%s (%s)" % (row["trap_oid_name"], trap_oid))
            if not row.get("alarm_name"):
                row["priority_reason"] = "Trap %s is upstream-filtered as critical or important." % row["trap_oid_name"]
        if row.get("matched_link"):
            link = row["matched_link"]
            row["priority_reason"] = "Trap matched topology link %s between %s/%s and %s/%s." % (
                link.get("link_name"),
                link.get("source_device"),
                link.get("source_interface"),
                link.get("target_device"),
                link.get("target_interface"),
            )
        severities = {clean_text(item.get("severity") or item.get("level")).lower() for item in items}
        if severities & {"critical", "emergency", "fatal", "5"}:
            critical.append(row)
        rows.append(row)
    rows.sort(key=lambda item: item["count"], reverse=True)
    critical.sort(key=lambda item: item["count"], reverse=True)
    notes.append("Trap input is treated as upstream-filtered critical/important data for AI attention.")
    if not severity_seen:
        notes.append("Trap records do not expose a reliable severity field, so important_traps is ranked by frequency and untranslated Trap details should be treated as insufficient evidence, not ignored.")
    if any(trap.get("device_identity_source") == "sender_fallback" for trap in traps):
        notes.append("Some Trap records used sender_fallback for device identity; treat these as low-confidence because the sender may be a relay.")
    if any(trap.get("managed_object_name") and not trap.get("matched_link") for trap in traps):
        notes.append("Some Trap managed objects were extracted but not matched to networkLinks; keep these in watch or insufficient until topology metadata is reconciled.")
    return critical[: limits.critical_traps], rows[: limits.important_traps], notes


def compact_event(event: dict) -> dict:
    raw_samples = event.get("raw_log_samples") or []
    if not isinstance(raw_samples, list):
        raw_samples = [raw_samples]
    evidence = []
    for sample in raw_samples[:2]:
        if isinstance(sample, dict):
            text = sample.get("raw_message") or sample.get("message") or json.dumps(sample, ensure_ascii=False)
        else:
            text = sample
        evidence.append(compact_sample_message(text))
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "device_ip": event.get("device_ip"),
        "device_name": event.get("device_name"),
        "object_key": event.get("object_key"),
        "first_seen": event.get("first_seen"),
        "last_seen": event.get("last_seen"),
        "event_count": int(event.get("event_count") or 0),
        "severity_max": event.get("severity_max"),
        "event_status": event.get("event_status"),
        "event_summary": event.get("event_summary"),
        "extracted_metrics": event.get("extracted_metrics") or {},
        "evidence_samples": evidence,
    }


def critical_alarm_reason(event: dict) -> str:
    event_type = clean_text(event.get("event_type"))
    if event_type in NON_CRITICAL_ALARM_EVENT_TYPES:
        return ""
    object_key = clean_text(event.get("object_key"))
    summary = clean_text(event.get("event_summary")).lower()
    haystack = " ".join(
        [
            event_type.lower(),
            clean_text(event.get("device_name")).lower(),
            object_key.lower(),
            summary,
            json.dumps(event.get("extracted_metrics") or {}, ensure_ascii=False).lower(),
        ]
    )
    keyword_hit = next((keyword for keyword in CRITICAL_ALARM_KEYWORDS if keyword.lower() in haystack), "")
    if event_type in CRITICAL_ALARM_EVENT_TYPES and keyword_hit:
        return "open %s matches critical alarm keyword %s" % (event_type, keyword_hit)
    if event_type in CRITICAL_ALARM_EVENT_TYPES:
        return "open %s is a physical/interface/optical alarm candidate" % event_type
    if keyword_hit:
        return "open alarm matches critical keyword %s" % keyword_hit
    return ""


def open_incident_sort_key(event: dict) -> Tuple[int, int, int, str]:
    reason = critical_alarm_reason(event)
    event_type = clean_text(event.get("event_type"))
    preferred_rank = 0 if event_type in PREFERRED_OPEN_EVENT_TYPES else 1
    critical_rank = 0 if reason else 1
    count = int(event.get("event_count") or 0)
    return critical_rank, preferred_rank, -count, clean_text(event.get("last_seen"))


def build_open_incidents(events: List[dict], limit: int) -> List[dict]:
    open_events = [event for event in events if event.get("event_status") == "open"]
    open_events.sort(key=open_incident_sort_key)
    return [compact_event(event) for event in open_events[:limit]]


def build_critical_alarm_candidates(open_incidents: List[dict], important_traps: List[dict], limit: int) -> List[dict]:
    rows: List[dict] = []
    for incident in open_incidents:
        reason = critical_alarm_reason(incident)
        if not reason:
            continue
        row = dict(incident)
        row.update(
            {
                "candidate_source": "alarm_event",
                "priority_reason": reason,
                "attention_required": True,
            }
        )
        rows.append(row)
    for trap in important_traps:
        row = dict(trap)
        row.update(
            {
                "candidate_source": "trap",
                "attention_required": True,
                "priority_reason": trap.get("priority_reason") or "Trap is upstream-filtered as critical or important but is not MIB-translated yet.",
            }
        )
        rows.append(row)
    return rows[:limit]


def counter_from_events(events: List[dict], fields: Tuple[str, ...], event_types: Optional[set] = None) -> Counter:
    counter: Counter = Counter()
    for event in events:
        if event_types and event.get("event_type") not in event_types:
            continue
        key = normalize_key(event.get(field) for field in fields)
        counter[key] += 1
    return counter


def count_baseline_key(config: SummaryConfig, start: dt.datetime, end: dt.datetime, filters: Dict[str, str]) -> int:
    terms = [{"term": {field: value}} for field, value in filters.items() if value and value != "__missing__"]
    if not terms:
        return 0
    return count_docs(config.es_url, config.event_index, device_scope_query(config, {"bool": {"filter": [event_window_query(start, end)] + terms}}))


def build_baseline_deviations(config: SummaryConfig, current_events: List[dict], baseline_start: dt.datetime, baseline_end: dt.datetime) -> List[dict]:
    rows = []
    dimensions = [
        ("event_type", ("event_type",)),
        ("device_ip", ("device_ip",)),
        ("device_name", ("device_name",)),
    ]
    baseline_days = max(config.baseline_days, 1)
    scale = config.hours / 24.0
    for dimension, fields in dimensions:
        for key, current_count in counter_from_events(current_events, fields).most_common(100):
            if current_count < 10 or key == "__missing__":
                continue
            filters = dict(zip(fields, key.split("|")))
            baseline_total = count_baseline_key(config, baseline_start, baseline_end, filters)
            baseline_avg = round((baseline_total / baseline_days) * scale, 2)
            ratio = round(current_count / baseline_avg, 2) if baseline_avg > 0 else None
            delta = round(current_count - baseline_avg, 2)
            if baseline_avg <= 0 or current_count >= baseline_avg * 2 or delta >= 50:
                rows.append(
                    {
                        "dimension": dimension,
                        "key": key,
                        "current_count": current_count,
                        "baseline_avg": baseline_avg,
                        "delta": delta,
                        "ratio": ratio,
                        "reason": "current window count is significantly higher than the 7-day baseline window average",
                    }
                )
    rows.sort(key=lambda item: (item["ratio"] if item["ratio"] is not None else math.inf, item["delta"]), reverse=True)
    return rows[: config.limits.baseline_deviations]


def anomaly_patterns(event: dict) -> List[Tuple[str, Dict[str, str]]]:
    event_type = clean_text(event.get("event_type"))
    device_ip = clean_text(event.get("device_ip"))
    object_key = clean_text(event.get("object_key"))
    rows = []
    if event_type and device_ip:
        rows.append((normalize_key([event_type, device_ip]), {"event_type": event_type, "device_ip": device_ip}))
    if event_type and object_key:
        rows.append((normalize_key([event_type, object_key]), {"event_type": event_type, "object_key": object_key}))
    if event_type and device_ip and object_key:
        rows.append((normalize_key([event_type, device_ip, object_key]), {"event_type": event_type, "device_ip": device_ip, "object_key": object_key}))
    return rows


def build_new_anomalies(config: SummaryConfig, current_events: List[dict], baseline_start: dt.datetime, baseline_end: dt.datetime) -> List[dict]:
    pattern_counts: Counter = Counter()
    pattern_filters: Dict[str, Dict[str, str]] = {}
    example_by_pattern: Dict[str, dict] = {}
    for event in current_events:
        for pattern_key, filters in anomaly_patterns(event):
            pattern_counts[pattern_key] += 1
            pattern_filters[pattern_key] = filters
            example_by_pattern.setdefault(pattern_key, event)
    rows = []
    for pattern_key, current_count in pattern_counts.most_common(200):
        if current_count < 3:
            continue
        lookback_count = count_baseline_key(config, baseline_start, baseline_end, pattern_filters[pattern_key])
        if lookback_count <= 1:
            event = example_by_pattern[pattern_key]
            rows.append(
                {
                    "pattern_key": pattern_key,
                    "event_type": event.get("event_type"),
                    "device_ip": event.get("device_ip"),
                    "device_name": event.get("device_name"),
                    "object_key": event.get("object_key"),
                    "current_count": current_count,
                    "lookback_count": lookback_count,
                    "reason": "pattern rarely appeared in the 7-day lookback but appears repeatedly in the current window",
                }
            )
    return rows[: config.limits.new_anomalies]


def event_flap_count(event: dict) -> int:
    values = [
        event.get("flap_count"),
        event.get("up_down_count"),
        event.get("down_up_count"),
        event.get("suppression_count"),
        event.get("resume_count"),
        (event.get("extracted_metrics") or {}).get("flap_count"),
    ]
    total = 0
    for value in values:
        try:
            total += int(value or 0)
        except (TypeError, ValueError):
            continue
    return total or int(event.get("event_count") or 0)


def build_flapping_objects(events: List[dict], limit: int) -> List[dict]:
    grouped: Dict[Tuple[str, str, str, str], dict] = {}
    for event in events:
        if event.get("event_type") not in FLAPPING_EVENT_TYPES:
            continue
        flap_count = event_flap_count(event)
        status = clean_text(event.get("event_status")).lower()
        if flap_count < 2 and "flap" not in status:
            continue
        key = (
            clean_text(event.get("event_type")),
            clean_text(event.get("device_ip")),
            clean_text(event.get("device_name")),
            clean_text(event.get("object_key")),
        )
        row = grouped.setdefault(
            key,
            {
                "event_type": event.get("event_type"),
                "device_ip": event.get("device_ip"),
                "device_name": event.get("device_name"),
                "object_key": event.get("object_key"),
                "first_seen": event.get("first_seen"),
                "last_seen": event.get("last_seen"),
                "flap_count": 0,
                "reason": "repeated state changes or suppression/resume signals in the current window",
            },
        )
        row["flap_count"] += flap_count
        row["first_seen"] = min([value for value in [row.get("first_seen"), event.get("first_seen")] if value])
        row["last_seen"] = max([value for value in [row.get("last_seen"), event.get("last_seen")] if value])
    rows = list(grouped.values())
    rows.sort(key=lambda item: item["flap_count"], reverse=True)
    return rows[:limit]


def correlation_key(event: dict) -> Tuple[Optional[str], Optional[str]]:
    event_type = event.get("event_type")
    if event_type == "RADIUS_SERVER_ABNORMAL":
        return "radius_server", clean_text(event.get("server_ip") or event.get("radius_server") or event.get("object_key"))
    if event_type == "BFD_FLAP":
        return "bfd_peer_or_session", clean_text(event.get("object_key") or event.get("aggregation_key"))
    if event_type == "QOS_CONGESTION":
        return "qos_queue", clean_text(event.get("queue_id") or event.get("object_key"))
    if event_type == "PTP_CLOCK_JITTER":
        return "ptp_slot", clean_text(event.get("slot") or event.get("object_key"))
    if event_type == "OPTICAL_FAULT":
        return "optical_object", clean_text(event.get("error_code") or event.get("object_key"))
    if event_type == "INTERFACE_LINK":
        return "interface_object", clean_text(event.get("object_key"))
    return None, None


def build_multi_device_correlations(events: List[dict], traps: List[dict], limit: int) -> List[dict]:
    groups: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for event in events:
        if event.get("event_type") not in CORRELATION_EVENT_TYPES:
            continue
        corr_type, obj = correlation_key(event)
        if not corr_type or not obj or obj == "__missing__":
            continue
        groups[(corr_type, obj, clean_text(event.get("event_type")))].append(event)

    rows = []
    for (corr_type, obj, event_type), items in groups.items():
        devices = sorted({clean_text(item.get("device_ip")) for item in items if clean_text(item.get("device_ip"))})
        if len(devices) < 2:
            continue
        rows.append(
            {
                "correlation_type": corr_type,
                "object_key": obj,
                "event_type": event_type,
                "device_count": len(devices),
                "devices": devices[:20],
                "total_count": sum(int(item.get("event_count") or 1) for item in items),
                "first_seen": min(item.get("first_seen") for item in items if item.get("first_seen")),
                "last_seen": max(item.get("last_seen") for item in items if item.get("last_seen")),
                "reason": "same object produced related events on multiple devices in the current window",
            }
        )

    trap_groups: Dict[str, List[dict]] = defaultdict(list)
    for trap in traps:
        trap_oid = clean_text(trap.get("trap_oid"))
        if trap_oid:
            trap_groups[trap_oid].append(trap)
    for trap_oid, items in trap_groups.items():
        devices = sorted({clean_text(item.get("managed_device_ip") or item.get("managed_device_name")) for item in items if clean_text(item.get("managed_device_ip") or item.get("managed_device_name"))})
        if len(devices) < 2:
            continue
        first_seen, last_seen = trap_time_bounds(items)
        rows.append(
            {
                "correlation_type": "trap_oid",
                "object_key": trap_oid,
                "event_type": "TRAP",
                "device_count": len(devices),
                "devices": devices[:20],
                "total_count": len(items),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "reason": "same Trap OID appeared on multiple managed devices in the current window",
            }
        )

    rows.sort(key=lambda item: (item["device_count"], item["total_count"]), reverse=True)
    return rows[:limit]


def build_noise_candidates(config: SummaryConfig, current_events: List[dict], baseline_start: dt.datetime, baseline_end: dt.datetime) -> List[dict]:
    by_type = counter_from_events(current_events, ("event_type",))
    open_by_type = counter_from_events([event for event in current_events if event.get("event_status") == "open"], ("event_type",))
    rows = []
    scale = config.hours / 24.0
    for event_type, count in by_type.most_common(100):
        if count < 10 or event_type == "__missing__":
            continue
        baseline_total = count_baseline_key(config, baseline_start, baseline_end, {"event_type": event_type})
        baseline_avg = round((baseline_total / max(config.baseline_days, 1)) * scale, 2)
        has_open = open_by_type.get(event_type, 0) > 0
        if baseline_avg >= 10 and count <= baseline_avg * 1.2 and not has_open:
            rows.append(
                {
                    "event_type": event_type,
                    "count": count,
                    "baseline_avg": baseline_avg,
                    "reason": "event volume is stable or below baseline and has no open lifecycle incidents in the current window",
                    "suggested_attention": "low",
                }
            )
    return rows[: config.limits.noise_candidates]


def build_data_quality(
    config: SummaryConfig,
    start: dt.datetime,
    end: dt.datetime,
    baseline_start: dt.datetime,
    baseline_end: dt.datetime,
    current_events: List[dict],
    trap_notes: List[str],
    mib_stats: Optional[dict] = None,
) -> dict:
    unknown_query = device_scope_query(config, {"bool": {"filter": [range_query(start, end), {"term": {"event_family.keyword": "unknown"}}]}})
    try:
        unknown_count = count_docs(config.es_url, config.syslog_index, unknown_query)
    except Exception:
        unknown_count = None
    baseline_count = count_docs(config.es_url, config.event_index, device_scope_query(config, event_window_query(baseline_start, baseline_end)))
    missing = {
        "device_ip": sum(1 for event in current_events if not event.get("device_ip")),
        "device_name": sum(1 for event in current_events if not event.get("device_name")),
        "object_key": sum(1 for event in current_events if not event.get("object_key")),
        "event_status": sum(1 for event in current_events if not event.get("event_status")),
    }
    notes = list(trap_notes)
    if baseline_count == 0:
        notes.append("No alarm event baseline documents were found in the configured lookback window.")
    if mib_stats and mib_stats.get("lookup_error"):
        notes.append("MIB lookup failed: %s" % mib_stats.get("lookup_error"))
    if mib_stats and mib_stats.get("device_lookup_error"):
        notes.append("Trap managed-device lookup failed: %s" % mib_stats.get("device_lookup_error"))
    trap_sender_ip_count = (mib_stats or {}).get("trap_sender_ip_count")
    trap_resolved_count = (mib_stats or {}).get("trap_managed_device_resolved_count")
    trap_unresolved_count = (mib_stats or {}).get("trap_managed_device_unresolved_count")
    trap_sender_as_device_ip_count = (mib_stats or {}).get("trap_sender_as_device_ip_count")
    trap_object_extracted_count = (mib_stats or {}).get("trap_object_extracted_count")
    trap_topology_link_matched_count = (mib_stats or {}).get("trap_topology_link_matched_count")
    trap_topology_link_unmatched_count = (mib_stats or {}).get("trap_topology_link_unmatched_count")
    trap_device_identity_unresolved_count = (mib_stats or {}).get("trap_device_identity_unresolved_count")
    trap_alarm_definition_matched_count = (mib_stats or {}).get("trap_alarm_definition_matched_count")
    trap_alarm_definition_unmatched_count = (mib_stats or {}).get("trap_alarm_definition_unmatched_count")
    identity_source_counts = (mib_stats or {}).get("identity_source_counts") or {}
    if trap_sender_as_device_ip_count:
        notes.append("Some Trap device identities fell back to sender IP; verify whether those senders are relays before treating them as managed devices.")
    scanned_syslog_count = count_docs(config.es_url, config.syslog_index, device_scope_query(config, range_query(start, end)))
    unknown_ratio = None
    if unknown_count is not None and scanned_syslog_count:
        unknown_ratio = round(float(unknown_count) / float(scanned_syslog_count), 4)
    return {
        "unknown_event_family_count": unknown_count,
        "unknown_event_family_exists": bool(unknown_count) if unknown_count is not None else None,
        "unknown_event_family_ratio": unknown_ratio,
        "syslog_scanned_count_for_quality": scanned_syslog_count,
        "trap_upstream_filtered_as_critical_or_important": True,
        "trap_alarm_lookup_available": (mib_stats or {}).get("alarm_lookup_available"),
        "trap_alarm_lookup_requested": (mib_stats or {}).get("alarm_lookup_requested"),
        "trap_alarm_lookup_hits": (mib_stats or {}).get("alarm_lookup_hits"),
        "trap_alarm_lookup_misses": (mib_stats or {}).get("alarm_lookup_misses"),
        "trap_alarm_lookup_error": (mib_stats or {}).get("alarm_lookup_error"),
        "trap_alarm_definition_matched_count": trap_alarm_definition_matched_count,
        "trap_alarm_definition_unmatched_count": trap_alarm_definition_unmatched_count,
        "mib_lookup_available": (mib_stats or {}).get("lookup_available"),
        "mib_lookup_requested": (mib_stats or {}).get("lookup_requested"),
        "mib_lookup_hits": (mib_stats or {}).get("lookup_hits"),
        "mib_lookup_misses": (mib_stats or {}).get("lookup_misses"),
        "mib_es_translated_hits": (mib_stats or {}).get("es_translated_hits"),
        "trap_mib_translated": bool((mib_stats or {}).get("translated_total")),
        "trap_mib_translated_count": (mib_stats or {}).get("translated_total"),
        "trap_mib_untranslated_count": (mib_stats or {}).get("untranslated_total"),
        "trap_sender_ip_count": trap_sender_ip_count,
        "trap_managed_device_resolved_count": trap_resolved_count,
        "trap_managed_device_unresolved_count": trap_unresolved_count,
        "trap_sender_as_device_ip_count": trap_sender_as_device_ip_count,
        "trap_object_extracted_count": trap_object_extracted_count,
        "trap_topology_link_matched_count": trap_topology_link_matched_count,
        "trap_topology_link_unmatched_count": trap_topology_link_unmatched_count,
        "trap_device_identity_unresolved_count": trap_device_identity_unresolved_count,
        "trap_identity_source_counts": identity_source_counts,
        "trap_identity_resolution_notes": notes,
        "trap_severity_available": not any("severity field" in note for note in trap_notes),
        "topology_context_available": bool(trap_topology_link_matched_count),
        "baseline_window_start": iso_z(baseline_start),
        "baseline_window_end": iso_z(baseline_end),
        "baseline_event_count": baseline_count,
        "baseline_data_sufficient": baseline_count >= 100,
        "field_missing_counts_in_scanned_events": missing,
        "scanned_event_count": len(current_events),
        "event_scan_limit": config.limits.event_scan_size,
        "notes": notes,
    }


def build_current_window_summary(config: SummaryConfig) -> dict:
    load_env_file(config.env_file)
    now = utc_now()
    start = now - dt.timedelta(hours=config.hours)
    baseline_end = start
    baseline_start = baseline_end - dt.timedelta(days=config.baseline_days)

    LOGGER.info("Building current window summary: hours=%s baseline_days=%s", config.hours, config.baseline_days)
    current_events = load_current_events(config, start, now)
    current_traps_raw = load_current_traps(config, start, now)
    current_traps, mib_stats = enrich_traps(current_traps_raw)
    critical_traps, important_traps, trap_notes = build_trap_candidates(current_traps, config.limits)
    trap_senders = {clean_text(trap.get("trap_sender_ip")) for trap in current_traps if clean_text(trap.get("trap_sender_ip"))}
    trap_names = {clean_text(trap.get("managed_device_name")) for trap in current_traps if clean_text(trap.get("managed_device_name"))}
    if len(trap_senders) == 1 and len(trap_names) > 1:
        only_sender = next(iter(trap_senders))
        trap_notes.append("%s is trap relay/source, not managed device; multiple managed_device_name values were observed behind this sender." % only_sender)
    names_by_sender: Dict[str, set] = defaultdict(set)
    for trap in current_traps:
        sender = clean_text(trap.get("trap_sender_ip"))
        name = clean_text(trap.get("managed_device_name"))
        if sender and name:
            names_by_sender[sender].add(name)
    for sender, names in sorted(names_by_sender.items()):
        if len(names) > 1:
            trap_notes.append("%s is trap relay/source, not managed device; observed %s managed_device_name values behind this sender." % (sender, len(names)))
    open_incidents = build_open_incidents(current_events, config.limits.open_incidents)
    critical_alarm_candidates = build_critical_alarm_candidates(open_incidents, important_traps, config.limits.critical_alarm_candidates)

    summary = {
        "metadata": {
            "generated_at": iso_z(now),
            "window_start": iso_z(start),
            "window_end": iso_z(now),
            "hours": config.hours,
            "platform_scope_device_ips": None if config.allowed_device_ips is None else list(config.allowed_device_ips),
        },
        "overview": build_overview(config, start, now, current_events),
        "critical_alarm_candidates": critical_alarm_candidates,
        "critical_traps": critical_traps,
        "important_traps": important_traps,
        "important_trap_candidates": important_traps,
        "open_incidents": open_incidents,
        "baseline_deviations": build_baseline_deviations(config, current_events, baseline_start, baseline_end),
        "new_anomalies": build_new_anomalies(config, current_events, baseline_start, baseline_end),
        "flapping_objects": build_flapping_objects(current_events, config.limits.flapping_objects),
        "multi_device_correlations": build_multi_device_correlations(current_events, current_traps, config.limits.multi_device_correlations),
        "noise_candidates": build_noise_candidates(config, current_events, baseline_start, baseline_end),
        "data_quality": build_data_quality(config, start, now, baseline_start, baseline_end, current_events, trap_notes, mib_stats),
    }
    LOGGER.info(
        "Summary built: events=%s traps=%s critical_alarm_candidates=%s open_incidents=%s anomalies=%s correlations=%s",
        len(current_events),
        len(current_traps),
        len(summary["critical_alarm_candidates"]),
        len(summary["open_incidents"]),
        len(summary["new_anomalies"]),
        len(summary["multi_device_correlations"]),
    )
    return summary
