"""Investigation tools for lightweight AIOps Agent candidates.

Task 15 keeps investigation bounded: the backend expands selected candidates
into a structured context package instead of letting AI run arbitrary queries.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import pymysql
except ImportError:  # pragma: no cover - optional runtime enhancement
    pymysql = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional runtime enhancement
    load_dotenv = None

from aiops.context.current_window_summary import (
    clean_text,
    count_docs,
    es_request,
    event_source_fields,
    event_window_query,
    iso_z,
    parse_time,
    range_query,
    search_docs,
    utc_now,
)
from aiops.agent.persistence import build_ai_memory_context
from aiops.mib.trap_enrichment import enrich_traps
from aiops.topology.lookup import TopologyLookupService


LOGGER = logging.getLogger(__name__)


@dataclass
class InvestigationLimits:
    candidates: int = 20
    related_current_events: int = 20
    historical_events: int = 20
    related_traps: int = 20
    topology_links: int = 30
    ai_memory: int = 5


@dataclass
class InvestigationConfig:
    es_url: str = "http://127.0.0.1:9200"
    syslog_index: str = "jscn-aiops-syslog-parsed-*"
    trap_index: str = "jscn-aiops-trap-raw-*"
    event_index: str = "jscn-aiops-alarm-events-*"
    allowed_device_ips: Optional[Tuple[str, ...]] = None
    baseline_days: int = 7
    before_minutes: int = 30
    after_minutes: int = 30
    env_file: Optional[str] = None
    limits: InvestigationLimits = field(default_factory=InvestigationLimits)


def load_env_file(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    candidates: List[str] = []
    if path:
        candidates.append(path)
    else:
        candidates.extend([".env", "deploy/.env"])
    for candidate in candidates:
        if os.path.exists(candidate):
            load_dotenv(candidate, override=False)


def bool_query(filters: List[dict], should: Optional[List[dict]] = None, minimum_should_match: int = 0) -> dict:
    query: Dict[str, Any] = {"bool": {"filter": filters}}
    if should:
        query["bool"]["should"] = should
        query["bool"]["minimum_should_match"] = minimum_should_match
    return query


def device_scope_query(config: InvestigationConfig, query: dict) -> dict:
    """Keep every AI investigation inside the platform device boundary."""
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


def term_if_present(field: str, value: Any) -> Optional[dict]:
    text = clean_text(value)
    if not text or text == "__missing__":
        return None
    return {"term": {field: text}}


def candidate_identity(candidate_type: str, candidate: dict) -> dict:
    managed_device_ip = candidate.get("managed_device_ip") or candidate.get("device_ip")
    managed_device_name = candidate.get("managed_device_name") or candidate.get("device_name")
    if candidate.get("candidate_source") == "trap" or candidate.get("trap_oid"):
        managed_device_ip = candidate.get("managed_device_ip")
        managed_device_name = candidate.get("managed_device_name") or candidate.get("device_name")
    return {
        "candidate_type": candidate_type,
        "event_type": candidate.get("event_type"),
        "device_ip": managed_device_ip,
        "device_name": managed_device_name,
        "managed_device_ip": managed_device_ip,
        "managed_device_name": managed_device_name,
        "trap_sender_ip": candidate.get("trap_sender_ip") or candidate.get("source_ip"),
        "snmp_agent_addr": candidate.get("snmp_agent_addr"),
        "device_identity_source": candidate.get("device_identity_source"),
        "device_identity_confidence": candidate.get("device_identity_confidence"),
        "object_key": candidate.get("object_key"),
        "managed_object_name": candidate.get("managed_object_name"),
        "managed_object_address": candidate.get("managed_object_address"),
        "endpoint_device_names": candidate.get("endpoint_device_names") or [],
        "endpoint_interfaces": candidate.get("endpoint_interfaces") or [],
        "topology_object_key": candidate.get("topology_object_key"),
        "matched_link": candidate.get("matched_link"),
        "topology_match": candidate.get("topology_match"),
        "trap_oid": candidate.get("trap_oid"),
        "alarm_name": candidate.get("alarm_name"),
        "alarm_severity": candidate.get("alarm_severity"),
        "alarm_lifecycle_status": candidate.get("alarm_lifecycle_status"),
        "alarm_vendor": candidate.get("alarm_vendor"),
        "alarm_enterprise_name": candidate.get("alarm_enterprise_name"),
        "alarm_definition_matched": candidate.get("alarm_definition_matched"),
        "enterprise_oid": candidate.get("enterprise_oid"),
        "specific_trap": candidate.get("specific_trap"),
        "first_seen": candidate.get("first_seen"),
        "last_seen": candidate.get("last_seen"),
    }


def candidate_score(candidate_type: str, candidate: dict) -> Tuple[int, int, int]:
    priority = {
        "critical_alarm_candidates": 0,
        "open_incidents": 1,
        "multi_device_correlations": 2,
        "flapping_objects": 3,
        "new_anomalies": 4,
        "baseline_deviations": 5,
        "important_trap_candidates": 6,
        "noise_candidates": 7,
    }.get(candidate_type, 9)
    count = candidate.get("event_count") or candidate.get("current_count") or candidate.get("total_count") or candidate.get("count") or candidate.get("flap_count") or 0
    try:
        numeric_count = int(float(count))
    except (TypeError, ValueError):
        numeric_count = 0
    source_rank = 0
    if candidate_type == "critical_alarm_candidates":
        source_rank = 0 if candidate.get("candidate_source") == "alarm_event" else 1
    return priority, source_rank, -numeric_count


def select_candidates(summary: dict, limit: int) -> List[dict]:
    sections = [
        "critical_alarm_candidates",
        "open_incidents",
        "multi_device_correlations",
        "flapping_objects",
        "new_anomalies",
        "baseline_deviations",
        "important_trap_candidates",
        "important_traps",
        "noise_candidates",
    ]
    rows = []
    for section in sections:
        normalized_section = "important_trap_candidates" if section == "important_traps" else section
        for candidate in summary.get(section, []) or []:
            rows.append({"candidate_type": normalized_section, "candidate": candidate})
    rows.sort(key=lambda item: candidate_score(item["candidate_type"], item["candidate"]))
    return rows[:limit]


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
        text = clean_text(text)
        evidence.append(text[:300] + ("..." if len(text) > 300 else ""))
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "event_mode": event.get("event_mode"),
        "device_ip": event.get("device_ip"),
        "device_name": event.get("device_name"),
        "object_key": event.get("object_key"),
        "first_seen": event.get("first_seen"),
        "last_seen": event.get("last_seen"),
        "event_count": event.get("event_count"),
        "event_status": event.get("event_status"),
        "severity_max": event.get("severity_max"),
        "event_summary": event.get("event_summary"),
        "extracted_metrics": event.get("extracted_metrics") or {},
        "evidence_samples": evidence,
    }


def compact_trap(trap: dict) -> dict:
    message = clean_text(trap.get("raw_message"))
    return {
        "timestamp": trap.get("@timestamp"),
        "trap_oid": trap.get("trap_oid"),
        "trap_oid_name": trap.get("trap_oid_name"),
        "trap_oid_module": trap.get("trap_oid_module"),
        "trap_oid_type": trap.get("trap_oid_type"),
        "trap_oid_description": trap.get("trap_oid_description"),
        "mib_translated": trap.get("mib_translated"),
        "mib_lookup_source": trap.get("mib_lookup_source"),
        "alarm_name": trap.get("alarm_name"),
        "alarm_severity": trap.get("alarm_severity"),
        "alarm_lifecycle_status": trap.get("alarm_lifecycle_status"),
        "alarm_vendor": trap.get("alarm_vendor"),
        "alarm_enterprise_name": trap.get("alarm_enterprise_name"),
        "alarm_fault_reason": trap.get("alarm_fault_reason"),
        "alarm_suggestion": trap.get("alarm_suggestion"),
        "alarm_definition_matched": trap.get("alarm_definition_matched"),
        "alarm_lookup_source": trap.get("alarm_lookup_source"),
        "source_ip": trap.get("source_ip"),
        "trap_sender_ip": trap.get("trap_sender_ip"),
        "snmp_agent_addr": trap.get("snmp_agent_addr"),
        "managed_device_ip": trap.get("managed_device_ip"),
        "managed_device_name": trap.get("managed_device_name"),
        "managed_object_name": trap.get("managed_object_name"),
        "managed_object_address": trap.get("managed_object_address"),
        "endpoint_device_names": trap.get("endpoint_device_names") or [],
        "endpoint_interfaces": trap.get("endpoint_interfaces") or [],
        "topology_object_key": trap.get("topology_object_key"),
        "topology_match": trap.get("topology_match"),
        "matched_link": trap.get("matched_link"),
        "topology_correlation_status": trap.get("topology_correlation_status"),
        "device_identity_source": trap.get("device_identity_source"),
        "device_identity_confidence": trap.get("device_identity_confidence"),
        "enterprise_oid": trap.get("enterprise_oid"),
        "specific_trap": trap.get("specific_trap"),
        "device_ip": trap.get("device_ip"),
        "device_name": trap.get("device_name"),
        "sample_message": message[:300] + ("..." if len(message) > 300 else ""),
    }


def candidate_time_range(summary: dict, candidate: dict, config: InvestigationConfig) -> Tuple[dt.datetime, dt.datetime]:
    window_start = parse_time(summary.get("metadata", {}).get("window_start")) or (utc_now() - dt.timedelta(hours=7))
    window_end = parse_time(summary.get("metadata", {}).get("window_end")) or utc_now()
    first_seen = parse_time(candidate.get("first_seen")) or window_start
    last_seen = parse_time(candidate.get("last_seen")) or window_end
    start = min(first_seen, window_start) - dt.timedelta(minutes=config.before_minutes)
    end = max(last_seen, window_end) + dt.timedelta(minutes=config.after_minutes)
    return start, end


def event_should_terms(identity: dict, candidate: dict) -> List[dict]:
    should = []
    for field in ["event_type", "device_ip", "device_name", "object_key"]:
        term = term_if_present(field, identity.get(field) or candidate.get(field))
        if term:
            should.append(term)
    if identity.get("candidate_type") == "multi_device_correlations":
        term = term_if_present("event_type", candidate.get("event_type"))
        if term and term not in should:
            should.append(term)
        for device in candidate.get("devices") or []:
            term = term_if_present("device_ip", device)
            if term:
                should.append(term)
    for name in identity.get("endpoint_device_names") or candidate.get("endpoint_device_names") or []:
        term = term_if_present("device_name", name)
        if term:
            should.append(term)
    matched_link = identity.get("matched_link") or candidate.get("matched_link") or {}
    if isinstance(matched_link, dict):
        for name in [matched_link.get("source_device"), matched_link.get("target_device")]:
            term = term_if_present("device_name", name)
            if term:
                should.append(term)
        for object_key in [matched_link.get("source_interface"), matched_link.get("target_interface"), matched_link.get("link_name")]:
            term = term_if_present("object_key", object_key)
            if term:
                should.append(term)
    return should


def find_related_current_events(config: InvestigationConfig, summary: dict, identity: dict, candidate: dict) -> List[dict]:
    start, end = candidate_time_range(summary, candidate, config)
    should = event_should_terms(identity, candidate)
    if not should:
        return []
    docs = search_docs(
        config.es_url,
        config.event_index,
        device_scope_query(config, bool_query([event_window_query(start, end)], should, 1)),
        config.limits.related_current_events,
        sort=[{"event_count": {"order": "desc", "unmapped_type": "long"}}, {"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )
    return [compact_event(item) for item in docs]


def historical_filters(identity: dict, candidate: dict) -> List[dict]:
    filters = []
    for field in ["event_type", "device_ip", "device_name", "object_key"]:
        term = term_if_present(field, identity.get(field) or candidate.get(field))
        if term:
            filters.append(term)
    if identity.get("candidate_type") == "multi_device_correlations":
        term = term_if_present("event_type", candidate.get("event_type"))
        if term:
            filters = [term]
    return filters


def topology_event_should_terms(identity: dict, candidate: dict) -> List[dict]:
    should = []
    for event_type in ["INTERFACE_LINK", "OPTICAL_FAULT", "BFD_FLAP", "RADIUS_SERVER_ABNORMAL", "PTP_CLOCK_JITTER"]:
        term = term_if_present("event_type", event_type)
        if term:
            should.append(term)
    matched_link = identity.get("matched_link") or candidate.get("matched_link") or {}
    endpoint_names = list(identity.get("endpoint_device_names") or candidate.get("endpoint_device_names") or [])
    endpoint_interfaces = list(identity.get("endpoint_interfaces") or candidate.get("endpoint_interfaces") or [])
    if isinstance(matched_link, dict):
        endpoint_names.extend([matched_link.get("source_device"), matched_link.get("target_device")])
        endpoint_interfaces.extend([matched_link.get("source_interface"), matched_link.get("target_interface"), matched_link.get("link_name")])
    for name in endpoint_names:
        term = term_if_present("device_name", name)
        if term:
            should.append(term)
    for interface in endpoint_interfaces:
        term = term_if_present("object_key", interface)
        if term:
            should.append(term)
    for value in [identity.get("managed_object_name") or candidate.get("managed_object_name"), identity.get("managed_object_address") or candidate.get("managed_object_address")]:
        term = term_if_present("object_key", value)
        if term:
            should.append(term)
    return should


def find_topology_related_alarm_events(config: InvestigationConfig, summary: dict, identity: dict, candidate: dict) -> List[dict]:
    if not (identity.get("matched_link") or identity.get("managed_object_name") or identity.get("endpoint_device_names")):
        return []
    start, end = candidate_time_range(summary, candidate, config)
    should = topology_event_should_terms(identity, candidate)
    if not should:
        return []
    docs = search_docs(
        config.es_url,
        config.event_index,
        device_scope_query(config, bool_query([event_window_query(start, end)], should, 1)),
        config.limits.related_current_events,
        sort=[{"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )
    return [compact_event(item) for item in docs]


def find_historical_events(config: InvestigationConfig, summary: dict, identity: dict, candidate: dict) -> List[dict]:
    window_start = parse_time(summary.get("metadata", {}).get("window_start")) or utc_now()
    baseline_start = window_start - dt.timedelta(days=config.baseline_days)
    filters = historical_filters(identity, candidate)
    should = topology_event_should_terms(identity, candidate)
    if not filters and not should:
        return []
    docs = search_docs(
        config.es_url,
        config.event_index,
        device_scope_query(config, bool_query([event_window_query(baseline_start, window_start)] + filters, should if not filters else None, 1 if not filters else 0)),
        config.limits.historical_events,
        sort=[{"last_seen": {"order": "desc", "unmapped_type": "date"}}],
        source=event_source_fields(),
    )
    return [compact_event(item) for item in docs]


def find_related_traps(config: InvestigationConfig, summary: dict, identity: dict, candidate: dict) -> List[dict]:
    start, end = candidate_time_range(summary, candidate, config)
    should = []
    for field, value in [
        ("managed_device_ip.keyword", identity.get("managed_device_ip")),
        ("managed_device_name.keyword", identity.get("managed_device_name")),
        ("device_ip.keyword", identity.get("managed_device_ip")),
        ("device_name.keyword", identity.get("managed_device_name")),
        ("managed_object_name.keyword", identity.get("managed_object_name") or candidate.get("managed_object_name")),
        ("topology_object_key.keyword", identity.get("topology_object_key") or candidate.get("topology_object_key")),
        ("trap_oid.keyword", identity.get("trap_oid") or candidate.get("trap_oid") or candidate.get("object_key")),
        ("enterprise_oid.keyword", identity.get("enterprise_oid") or candidate.get("enterprise_oid")),
        ("specific_trap", identity.get("specific_trap") or candidate.get("specific_trap")),
    ]:
        term = term_if_present(field, value)
        if term:
            should.append(term)
    for name in identity.get("endpoint_device_names") or candidate.get("endpoint_device_names") or []:
        term = term_if_present("endpoint_device_names.keyword", name)
        if term:
            should.append(term)
    if not should:
        return []
    docs = search_docs(
        config.es_url,
        config.trap_index,
        device_scope_query(config, bool_query([range_query(start, end)], should, 1)),
        config.limits.related_traps,
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
            "alarm_enterprise_name",
            "alarm_fault_reason",
            "alarm_suggestion",
            "alarm_definition_matched",
            "alarm_lookup_source",
            "source_ip",
            "trap_sender_ip",
            "collector_source_ip",
            "snmp_agent_addr",
            "managed_device_ip",
            "managed_device_name",
            "managed_object_name",
            "managed_object_address",
            "endpoint_device_names",
            "endpoint_interfaces",
            "topology_object_key",
            "topology_match",
            "matched_link",
            "topology_correlation_status",
            "device_identity_source",
            "device_identity_confidence",
            "enterprise_oid",
            "specific_trap",
            "device_ip",
            "device_name",
            "trap.varbinds",
            "raw_message",
        ],
    )
    enriched, _stats = enrich_traps(docs)
    return [compact_trap(item) for item in enriched]


def mysql_connection():
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


def load_topology(identity: dict, candidate: dict, config: InvestigationConfig) -> dict:
    matched_link = identity.get("matched_link") or candidate.get("matched_link")
    if matched_link:
        service = TopologyLookupService()
        matched_devices = []
        if isinstance(matched_link, dict):
            for name in [matched_link.get("source_device"), matched_link.get("target_device")]:
                device = service.lookup_device_by_name(name)
                if device:
                    matched_devices.append(device)
        return {
            "enabled": True,
            "matched_devices": matched_devices,
            "related_links": [matched_link],
            "notes": ["Topology link matched from Trap managed object."],
        }
    object_name = identity.get("managed_object_name") or candidate.get("managed_object_name")
    endpoints = identity.get("endpoint_device_names") or candidate.get("endpoint_device_names") or []
    interfaces = identity.get("endpoint_interfaces") or candidate.get("endpoint_interfaces") or []
    if object_name or len(endpoints) >= 2:
        service = TopologyLookupService()
        link = service.lookup_link_by_name(object_name) if object_name else None
        if not link and len(endpoints) >= 2:
            link = service.lookup_link_by_endpoints(
                endpoints[0],
                endpoints[1],
                interfaces[0] if len(interfaces) > 0 else None,
                interfaces[1] if len(interfaces) > 1 else None,
            )
        if link:
            return {
                "enabled": True,
                "matched_devices": [item for item in [service.lookup_device_by_name(link.get("source_device")), service.lookup_device_by_name(link.get("target_device"))] if item],
                "related_links": [link],
                "notes": ["Topology link matched during investigation."],
            }
    device_names = {clean_text(identity.get("device_name") or candidate.get("device_name"))}
    device_ips = {clean_text(identity.get("managed_device_ip") or identity.get("device_ip") or candidate.get("managed_device_ip") or candidate.get("device_ip"))}
    for device in candidate.get("devices") or []:
        device_ips.add(clean_text(device))
    device_names.discard("")
    device_ips.discard("")
    context = {"enabled": False, "matched_devices": [], "related_links": [], "notes": []}
    conn = mysql_connection()
    if conn is None:
        context["notes"].append("MySQL topology lookup skipped because pymysql or MYSQL_PASSWORD is unavailable.")
        return context
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, device_name, status, role, hierarchy, as_number, ip_address,
                       model, manufacturer, software_version
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
        context["notes"].append("MySQL topology lookup failed: %s" % exc)
        return context
    finally:
        conn.close()

    matched = []
    matched_names = set()
    for row in devices:
        row_name = clean_text(row.get("device_name"))
        row_ip = clean_text(row.get("ip_address"))
        if row_name in device_names or row_ip in device_ips:
            matched_names.add(row_name)
            matched.append(
                {
                    "device_name": row_name,
                    "ip_address": row_ip,
                    "status": clean_text(row.get("status")),
                    "role": clean_text(row.get("role")),
                    "hierarchy": clean_text(row.get("hierarchy")),
                    "as_number": clean_text(row.get("as_number")),
                    "model": clean_text(row.get("model")),
                    "manufacturer": clean_text(row.get("manufacturer")),
                    "software_version": clean_text(row.get("software_version")),
                }
            )
    related = []
    for row in links:
        source_device = clean_text(row.get("source_device"))
        target_device = clean_text(row.get("target_device"))
        source_ip = clean_text(row.get("source_ip"))
        target_ip = clean_text(row.get("target_ip"))
        if source_device in matched_names or target_device in matched_names or source_ip in device_ips or target_ip in device_ips:
            related.append(
                {
                    "link_id": row.get("link_id"),
                    "link_name": clean_text(row.get("link_name")),
                    "link_state": clean_text(row.get("link_state")),
                    "source_device": source_device,
                    "source_interface": clean_text(row.get("source_interface")),
                    "source_ip": source_ip,
                    "target_device": target_device,
                    "target_interface": clean_text(row.get("target_interface")),
                    "target_ip": target_ip,
                    "update_time": str(row.get("update_time") or ""),
                }
            )
    context.update({"enabled": True, "matched_devices": matched[:20], "related_links": related[: config.limits.topology_links]})
    if not matched:
        context["notes"].append("No topology device matched the candidate device identity.")
    return context


def load_ai_memory(identity: dict, candidate: dict, config: InvestigationConfig) -> dict:
    memory_candidate = dict(candidate or {})
    memory_candidate.update({key: value for key, value in identity.items() if value and key not in memory_candidate})
    try:
        return build_ai_memory_context([memory_candidate], limit=config.limits.ai_memory, env_file=config.env_file)
    except Exception as exc:
        memory = {"enabled": False, "records": [], "notes": ["AI findings memory lookup failed: %s" % exc]}
        return memory


def build_baseline_snapshot(config: InvestigationConfig, summary: dict, identity: dict, candidate: dict) -> dict:
    window_start = parse_time(summary.get("metadata", {}).get("window_start")) or utc_now()
    window_end = parse_time(summary.get("metadata", {}).get("window_end")) or utc_now()
    baseline_start = window_start - dt.timedelta(days=config.baseline_days)
    filters = historical_filters(identity, candidate)
    current_count = 0
    historical_count = 0
    should = topology_event_should_terms(identity, candidate)
    if filters:
        current_count = count_docs(config.es_url, config.event_index, device_scope_query(config, bool_query([event_window_query(window_start, window_end)] + filters)))
        historical_count = count_docs(config.es_url, config.event_index, device_scope_query(config, bool_query([event_window_query(baseline_start, window_start)] + filters)))
    elif should:
        current_count = count_docs(config.es_url, config.event_index, device_scope_query(config, bool_query([event_window_query(window_start, window_end)], should, 1)))
        historical_count = count_docs(config.es_url, config.event_index, device_scope_query(config, bool_query([event_window_query(baseline_start, window_start)], should, 1)))
    baseline_avg = round((historical_count / max(config.baseline_days, 1)) * ((window_end - window_start).total_seconds() / 86400), 2)
    return {
        "window_start": iso_z(window_start),
        "window_end": iso_z(window_end),
        "baseline_start": iso_z(baseline_start),
        "baseline_end": iso_z(window_start),
        "current_count": current_count,
        "historical_count": historical_count,
        "baseline_avg_for_window": baseline_avg,
        "delta": round(current_count - baseline_avg, 2),
        "filters_applied": filters,
        "topology_should_terms_applied": should[:20],
    }


def investigate_one(config: InvestigationConfig, summary: dict, candidate_type: str, candidate: dict) -> dict:
    identity = candidate_identity(candidate_type, candidate)
    return {
        "candidate_type": candidate_type,
        "candidate": candidate,
        "identity": identity,
        "baseline": build_baseline_snapshot(config, summary, identity, candidate),
        "related_current_events": find_related_current_events(config, summary, identity, candidate),
        "related_alarm_events": find_topology_related_alarm_events(config, summary, identity, candidate),
        "historical_events": find_historical_events(config, summary, identity, candidate),
        "related_traps": find_related_traps(config, summary, identity, candidate),
        "topology_context": load_topology(identity, candidate, config),
        "ai_memory": load_ai_memory(identity, candidate, config),
    }


def investigate_candidates(summary: dict, config: InvestigationConfig) -> dict:
    load_env_file(config.env_file)
    selected = select_candidates(summary, config.limits.candidates)
    LOGGER.info("Investigating %s candidates", len(selected))
    findings = [investigate_one(config, summary, item["candidate_type"], item["candidate"]) for item in selected]
    return {
        "metadata": {
            "generated_at": iso_z(utc_now()),
            "source_summary_window_start": summary.get("metadata", {}).get("window_start"),
            "source_summary_window_end": summary.get("metadata", {}).get("window_end"),
            "candidate_count": len(findings),
            "purpose": "bounded backend investigation context for lightweight AIOps Agent; no AI call performed",
        },
        "investigations": findings,
        "data_quality": {
            "tool_scope": "bounded candidate expansion only",
            "ai_direct_database_access": False,
            "max_candidates": config.limits.candidates,
            "max_related_current_events_per_candidate": config.limits.related_current_events,
            "max_historical_events_per_candidate": config.limits.historical_events,
            "max_related_traps_per_candidate": config.limits.related_traps,
            "memory_source": "MySQL ai_findings and ai_finding_feedback when available",
            "topology_source": "MySQL networkDevice/networkLinks when available",
            "notes": [
                "This tool does not expose arbitrary search_events to AI.",
                "Trap sender IP is preserved as relay/source evidence and is not used as managed-device identity for topology or history lookup.",
            ],
        },
    }
