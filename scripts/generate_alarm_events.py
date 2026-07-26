#!/usr/bin/env python3
"""Generate offline alarm events from recent Syslog documents.

Task 8.1 intentionally stays offline and read-only for Elasticsearch. It
queries Syslog documents, reapplies Task 7 parsing rules when extracted_fields
are not present, groups logs into lifecycle/statistical alarm events, and
writes JSON plus Markdown reports.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import statistics
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def clean_lines(path: pathlib.Path) -> List[Tuple[int, str]]:
    lines: List[Tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        lines.append((len(raw) - len(raw.lstrip(" ")), raw.strip()))
    return lines


def load_event_family_rules(path: pathlib.Path) -> Dict[str, Any]:
    rules: Dict[str, Any] = {"default_family": "unknown", "families": {}}
    current_family: Optional[str] = None
    current_section: Optional[str] = None
    in_families = False
    for indent, line in clean_lines(path):
        if indent == 0 and line.startswith("default_family:"):
            rules["default_family"] = strip_quotes(line.split(":", 1)[1])
        elif indent == 0 and line == "families:":
            in_families = True
        elif in_families and indent == 2 and line.endswith(":"):
            current_family = line[:-1]
            rules["families"][current_family] = {"event_codes": [], "modules": [], "keywords": []}
            current_section = None
        elif in_families and indent == 4 and line.endswith(":") and current_family:
            current_section = line[:-1]
        elif in_families and indent == 6 and line.startswith("- ") and current_family and current_section:
            rules["families"][current_family][current_section].append(strip_quotes(line[2:]))
    return rules


def load_field_extract_rules(path: pathlib.Path) -> Dict[str, Any]:
    rules: Dict[str, Any] = {"families": {}}
    current_family: Optional[str] = None
    current_section: Optional[str] = None
    current_field: Optional[str] = None
    in_families = False
    for indent, line in clean_lines(path):
        if indent == 0 and line == "families:":
            in_families = True
        elif in_families and indent == 2 and line.endswith(":"):
            current_family = line[:-1]
            rules["families"][current_family] = {"core_fields": [], "patterns": {}}
            current_section = None
            current_field = None
        elif in_families and indent == 4 and line.endswith(":") and current_family:
            current_section = line[:-1]
            current_field = None
        elif in_families and indent == 6 and line.startswith("- ") and current_family and current_section == "core_fields":
            rules["families"][current_family]["core_fields"].append(strip_quotes(line[2:]))
        elif in_families and indent == 6 and line.endswith(":") and current_family and current_section == "patterns":
            current_field = line[:-1]
            rules["families"][current_family]["patterns"][current_field] = []
        elif in_families and indent == 8 and line.startswith("- ") and current_family and current_field:
            rules["families"][current_family]["patterns"][current_field].append(strip_quotes(line[2:]))
    return rules


def load_aggregation_rules(path: pathlib.Path) -> Dict[str, Any]:
    rules: Dict[str, Any] = {"event_types": {}}
    current_type: Optional[str] = None
    current_list: Optional[str] = None
    in_event_types = False
    for indent, line in clean_lines(path):
        if indent == 0 and line == "event_types:":
            in_event_types = True
        elif in_event_types and indent == 2 and line.endswith(":"):
            current_type = line[:-1]
            rules["event_types"][current_type] = {}
            current_list = None
        elif in_event_types and indent == 4 and current_type and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = strip_quotes(value.strip())
            if value:
                try:
                    rules["event_types"][current_type][key] = int(value)
                except ValueError:
                    rules["event_types"][current_type][key] = value
                current_list = None
            else:
                rules["event_types"][current_type][key] = []
                current_list = key
        elif in_event_types and indent == 6 and line.startswith("- ") and current_type and current_list:
            rules["event_types"][current_type][current_list].append(strip_quotes(line[2:]))
    return rules


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(value: Any) -> str:
    return str(value or "").strip()


def es_request(es_url: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(es_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc


def clear_scroll(es_url: str, scroll_id: Optional[str]) -> None:
    if not scroll_id:
        return
    try:
        es_request(es_url, "DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
    except Exception:
        return


def iter_es_docs(es_url: str, index: str, days: int, batch_size: int) -> Iterable[dict]:
    body = {
        "size": batch_size,
        "sort": ["_doc"],
        "track_total_hits": True,
        "_source": [
            "@timestamp",
            "device_ip",
            "device_name",
            "module",
            "severity",
            "event_code",
            "event_family",
            "parse_status",
            "extracted_fields",
            "raw_message",
            "message",
        ],
        "query": {"range": {"@timestamp": {"gte": f"now-{days}d", "lte": "now"}}},
    }
    scroll_id: Optional[str] = None
    try:
        response = es_request(es_url, "POST", f"/{index}/_search?scroll=2m", body)
        scroll_id = response.get("_scroll_id")
        while True:
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                yield hit.get("_source", {})
            response = es_request(es_url, "POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
            scroll_id = response.get("_scroll_id", scroll_id)
    finally:
        clear_scroll(es_url, scroll_id)


def classify_event(doc: dict, family_rules: dict) -> str:
    event_code = normalize(doc.get("event_code")).upper()
    module = normalize(doc.get("module")).upper()
    raw_upper = normalize(doc.get("raw_message") or doc.get("message")).upper()
    for family, rule in family_rules["families"].items():
        if event_code and event_code in {item.upper() for item in rule.get("event_codes", [])}:
            return family
    for family, rule in family_rules["families"].items():
        if module and module in {item.upper() for item in rule.get("modules", [])}:
            return family
    for family, rule in family_rules["families"].items():
        for keyword in rule.get("keywords", []):
            if keyword and keyword.upper() in raw_upper:
                return family
    return family_rules.get("default_family", "unknown")


def extract_fields(doc: dict, event_family: str, field_rules: dict) -> dict:
    existing = doc.get("extracted_fields")
    if isinstance(existing, dict) and existing:
        return existing
    raw_message = normalize(doc.get("raw_message") or doc.get("message"))
    extracted: Dict[str, str] = {}
    patterns = field_rules.get("families", {}).get(event_family, {}).get("patterns", {})
    for field, regexes in patterns.items():
        if field in extracted:
            continue
        for regex in regexes:
            match = re.search(regex, raw_message)
            if not match:
                continue
            named = {name: value.strip() for name, value in match.groupdict().items() if value}
            if named:
                extracted.update(named)
            else:
                extracted[field] = match.group(0).strip()
            break
    return extracted


def severity_rank(value: str) -> int:
    ranks = {
        "emergency": 7,
        "alert": 6,
        "critical": 5,
        "crit": 5,
        "error": 4,
        "err": 4,
        "warning": 3,
        "warn": 3,
        "notice": 2,
        "info": 1,
        "debug": 0,
        "紧急": 7,
        "严重": 6,
        "重要": 5,
        "错误": 4,
        "警告": 3,
        "通知": 2,
        "信息": 1,
        "调试": 0,
    }
    return ranks.get(normalize(value).lower(), ranks.get(normalize(value), 0))


def max_severity(values: Iterable[str]) -> str:
    items = [normalize(value) for value in values if normalize(value)]
    if not items:
        return ""
    return max(items, key=severity_rank)


def safe_int(value: Any) -> Optional[int]:
    text = normalize(value)
    return int(text) if text.lstrip("-").isdigit() else None


def window_start(ts: dt.datetime, minutes: int) -> dt.datetime:
    epoch = int(ts.timestamp())
    size = minutes * 60
    return dt.datetime.fromtimestamp((epoch // size) * size, tz=dt.timezone.utc)


def stable_event_id(parts: Iterable[Any]) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def event_type_for_family(event_family: str, aggregation_rules: dict) -> Optional[str]:
    for event_type, rule in aggregation_rules["event_types"].items():
        if rule.get("event_family") == event_family:
            return event_type
    return None


def object_value(log: dict, field: str) -> str:
    if field in log:
        return normalize(log.get(field)) or "__missing__"
    return normalize(log["extracted_fields"].get(field)) or "__missing__"


def aggregation_key(log: dict, event_type: str, rule: dict) -> Tuple[Any, ...]:
    win = window_start(log["timestamp"], int(rule["window_minutes"]))
    if event_type == "BFD_FLAP":
        session = log["extracted_fields"].get("session_id")
        fields = ["device_ip", "session_id"] if session else ["device_ip", "linktype", "diag"]
    elif event_type == "OPTICAL_FAULT":
        fields = ["device_ip", "interface"] if log["extracted_fields"].get("interface") else ["device_ip", "error_code"]
    else:
        fields = list(rule.get("group_by", []))
    return (event_type, iso_z(win), *[object_value(log, field) for field in fields])


def prepare_logs(raw_docs: Iterable[dict], family_rules: dict, field_rules: dict, aggregation_rules: dict) -> List[dict]:
    logs = []
    for doc in raw_docs:
        ts = parse_time(doc.get("@timestamp"))
        if ts is None:
            continue
        event_family = classify_event(doc, family_rules)
        event_type = event_type_for_family(event_family, aggregation_rules)
        if not event_type:
            continue
        extracted = extract_fields(doc, event_family, field_rules)
        logs.append(
            {
                "timestamp": ts,
                "@timestamp": iso_z(ts),
                "device_ip": normalize(doc.get("device_ip")),
                "device_name": normalize(doc.get("device_name")),
                "module": normalize(doc.get("module")),
                "severity": normalize(doc.get("severity")),
                "event_code": normalize(doc.get("event_code")),
                "event_family": event_family,
                "event_type": event_type,
                "event_mode": aggregation_rules["event_types"][event_type].get("event_mode", "lifecycle"),
                "parse_status": normalize(doc.get("parse_status")),
                "extracted_fields": extracted,
                "raw_message": normalize(doc.get("raw_message") or doc.get("message")),
            }
        )
    return logs


def common_event(event_type: str, event_family: str, group_logs: List[dict], object_key: str, aggregation_key_text: str) -> dict:
    ordered = sorted(group_logs, key=lambda item: item["timestamp"])
    first = ordered[0]["timestamp"]
    last = ordered[-1]["timestamp"]
    fingerprint = stable_event_id([event_type, aggregation_key_text])
    return {
        "event_id": fingerprint,
        "fingerprint": fingerprint,
        "event_type": event_type,
        "event_mode": ordered[0].get("event_mode", "lifecycle"),
        "event_family": event_family,
        "device_ip": ordered[0]["device_ip"],
        "device_name": ordered[0]["device_name"],
        "object_key": object_key,
        "first_seen": iso_z(first),
        "last_seen": iso_z(last),
        "duration_seconds": int((last - first).total_seconds()),
        "event_count": len(ordered),
        "event_status": "open",
        "severity_max": max_severity(log["severity"] for log in ordered),
        "raw_log_samples": [log["raw_message"] for log in ordered[:5]],
        "extracted_metrics": {},
        "event_summary": "",
        "aggregation_key": aggregation_key_text,
    }


def counter_rows(counter: collections.Counter, limit: int) -> List[dict]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def build_event(event_type: str, group_logs: List[dict], key: Tuple[Any, ...]) -> dict:
    event_family = group_logs[0]["event_family"]
    extracted = [log["extracted_fields"] for log in group_logs]
    aggregation_key_text = "|".join(map(str, key))

    if event_type == "PPP_AUTH_FAILURE":
        domain = extracted[0].get("domain", "__missing__")
        username_counts = collections.Counter(item.get("username", "__missing__") for item in extracted)
        focus_threshold = 3
        user_focus_items = [
            {"username": username, "failure_count": count}
            for username, count in username_counts.most_common()
            if username != "__missing__" and count >= focus_threshold
        ]
        event = common_event(event_type, event_family, group_logs, domain, aggregation_key_text)
        event.update({
            "domain": domain,
            "event_status": "statistical",
            "username_count": len([name for name in username_counts if name != "__missing__"]),
            "top_usernames": counter_rows(username_counts, 10),
            "total_failures": len(group_logs),
            "user_focus_items": user_focus_items,
            "extracted_metrics": {
                "username_count": len([name for name in username_counts if name != "__missing__"]),
                "total_failures": len(group_logs),
                "top_usernames": counter_rows(username_counts, 10),
                "user_focus_items": user_focus_items,
            },
        })
        event["event_summary"] = f"PPP authentication failures on {event['device_ip']} domain {domain}: {event['total_failures']} failures, {event['username_count']} usernames."
        return event

    if event_type == "PTP_CLOCK_JITTER":
        slot = extracted[0].get("slot", "__missing__")
        offsets = [safe_int(item.get("time_offset")) for item in extracted]
        offsets = [item for item in offsets if item is not None]
        thresholds = [item.get("threshold") for item in extracted if item.get("threshold")]
        suppression = sum(1 for log in group_logs if log["event_code"] == "PTP_SYNC_SUPPRESSION")
        resume = sum(1 for log in group_logs if log["event_code"] == "PTP_SYNC_RESUME")
        event = common_event(event_type, event_family, group_logs, slot, aggregation_key_text)
        if suppression and resume:
            status = "recovered_or_flapping"
        elif suppression:
            status = "open"
        else:
            status = "recover_without_open"
        event.update({
            "slot": slot,
            "suppression_count": suppression,
            "resume_count": resume,
            "time_offset_avg": round(statistics.mean(offsets), 2) if offsets else None,
            "time_offset_max": max(offsets) if offsets else None,
            "threshold": collections.Counter(thresholds).most_common(1)[0][0] if thresholds else "",
            "event_status": status,
            "extracted_metrics": {
                "suppression_count": suppression,
                "resume_count": resume,
                "time_offset_avg": round(statistics.mean(offsets), 2) if offsets else None,
                "time_offset_max": max(offsets) if offsets else None,
            },
        })
        event["event_summary"] = f"PTP clock jitter on slot {slot}: suppression={suppression}, resume={resume}."
        return event

    if event_type == "BFD_FLAP":
        up_down = sum(1 for item in extracted if item.get("old_state") == "UP" and item.get("new_state") == "DOWN")
        down_up = sum(1 for item in extracted if item.get("old_state") == "DOWN" and item.get("new_state") == "UP")
        event = common_event(event_type, event_family, group_logs, extracted[0].get("session_id") or extracted[0].get("linktype", "__missing__"), aggregation_key_text)
        if up_down and down_up:
            status = "recovered_or_flapping"
        elif up_down:
            status = "open"
        else:
            status = "recover_without_open"
        event.update({
            "session_id": extracted[0].get("session_id", ""),
            "old_state": extracted[0].get("old_state", ""),
            "new_state": extracted[-1].get("new_state", ""),
            "up_down_count": up_down,
            "down_up_count": down_up,
            "flap_count": min(up_down, down_up),
            "event_status": "flapping_or_recovered" if status == "recovered_or_flapping" else status,
            "extracted_metrics": {
                "up_down_count": up_down,
                "down_up_count": down_up,
                "flap_count": min(up_down, down_up),
            },
        })
        event["event_summary"] = f"BFD state changes: UP->DOWN={up_down}, DOWN->UP={down_up}."
        return event

    if event_type == "INTERFACE_LINK":
        interface = extracted[0].get("interface", "__missing__")
        up_count = sum(1 for item in extracted if normalize(item.get("new_state")).lower() == "up")
        down_count = sum(1 for item in extracted if normalize(item.get("new_state")).lower() == "down")
        event = common_event(event_type, event_family, group_logs, interface, aggregation_key_text)
        if up_count and down_count:
            status = "flapping_or_recovered"
        elif down_count:
            status = "open"
        else:
            status = "recover_without_open"
        event.update({
            "interface": interface,
            "up_count": up_count,
            "down_count": down_count,
            "event_status": status,
            "extracted_metrics": {
                "up_count": up_count,
                "down_count": down_count,
            },
        })
        event["event_summary"] = f"Interface {interface} link changes: down={down_count}, up={up_count}."
        return event

    if event_type == "OPTICAL_FAULT":
        occur = sum(1 for log in group_logs if log["event_code"].endswith("_OCCUR"))
        clear = sum(1 for log in group_logs if log["event_code"].endswith("_CLEAR"))
        interface = extracted[0].get("interface", "")
        error_code = extracted[0].get("error_code", "")
        event = common_event(event_type, event_family, group_logs, interface or error_code or "__missing__", aggregation_key_text)
        if occur and clear:
            status = "recovered"
        elif occur:
            status = "open"
        else:
            status = "clear_without_open"
        event.update({
            "interface": interface,
            "error_code": error_code,
            "reason": extracted[0].get("reason", ""),
            "occur_count": occur,
            "clear_count": clear,
            "event_status": status,
            "extracted_metrics": {
                "occur_count": occur,
                "clear_count": clear,
            },
        })
        event["event_summary"] = f"Optical fault on {interface or error_code}: occur={occur}, clear={clear}."
        return event

    if event_type == "RADIUS_SERVER_ABNORMAL":
        event = common_event(event_type, event_family, group_logs, extracted[0].get("server_ip", "__missing__"), aggregation_key_text)
        event.update({
            "radius_server": extracted[0].get("radius_server", ""),
            "server_ip": extracted[0].get("server_ip", ""),
            "port": extracted[0].get("port", ""),
            "extracted_metrics": {"event_count": len(group_logs)},
        })
        event["event_summary"] = f"RADIUS server abnormal on {event['server_ip']} compressed from {event['event_count']} logs."
        return event

    if event_type == "QOS_CONGESTION":
        slot = extracted[0].get("slot", "__missing__")
        queue_id = extracted[0].get("queue_id", "__missing__")
        event = common_event(event_type, event_family, group_logs, f"{slot}/{queue_id}", aggregation_key_text)
        device_counts = collections.Counter(log["device_ip"] or "__missing__" for log in group_logs)
        queue_counts = collections.Counter(item.get("queue_id", "__missing__") for item in extracted)
        event.update({
            "slot": slot,
            "queue_id": queue_id,
            "reason": extracted[0].get("reason", ""),
            "event_status": "statistical",
            "top_devices": counter_rows(device_counts, 10),
            "top_queues": counter_rows(queue_counts, 10),
            "extracted_metrics": {
                "event_count": len(group_logs),
                "top_devices": counter_rows(device_counts, 10),
                "top_queues": counter_rows(queue_counts, 10),
            },
        })
        event["event_summary"] = f"QoS congestion on slot {slot}, queue {queue_id}: {event['event_count']} logs across {len(device_counts)} devices."
        return event

    raise ValueError(f"Unsupported event_type: {event_type}")


def aggregate_logs(logs: List[dict], aggregation_rules: dict) -> List[dict]:
    groups: Dict[Tuple[Any, ...], List[dict]] = collections.defaultdict(list)
    for log in logs:
        rule = aggregation_rules["event_types"][log["event_type"]]
        groups[aggregation_key(log, log["event_type"], rule)].append(log)
    events = [build_event(key[0], value, key) for key, value in groups.items()]
    return sorted(events, key=lambda item: (item["first_seen"], item["event_type"], item["device_ip"]))


def pct(numerator: int, denominator: int) -> float:
    return round(numerator * 100.0 / denominator, 2) if denominator else 0.0


def top_rows(counter: collections.Counter, limit: int) -> List[dict]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def summarize(raw_log_total: int, logs: List[dict], events: List[dict], top_n: int) -> dict:
    raw_by_type = collections.Counter(log["event_type"] for log in logs)
    events_by_type = collections.Counter(event["event_type"] for event in events)
    status_by_type = {
        event_type: dict(collections.Counter(event["event_status"] for event in events if event["event_type"] == event_type))
        for event_type in events_by_type
    }
    compression = []
    for event_type, raw_count in raw_by_type.items():
        event_count = events_by_type.get(event_type, 0)
        compression.append({
            "event_type": event_type,
            "raw_logs": raw_count,
            "events": event_count,
            "logs_per_event": round(raw_count / event_count, 2) if event_count else 0,
            "reduction_ratio": pct(raw_count - event_count, raw_count),
        })
    compression.sort(key=lambda item: item["raw_logs"], reverse=True)

    open_events = [event for event in events if event["event_status"] == "open"]
    recovered_events = [
        event for event in events
        if event["event_status"] in {"recovered", "recovered_or_flapping", "flapping_or_recovered", "recover_without_open", "clear_without_open"}
    ]
    gaps = [
        "This is offline window aggregation only; it does not maintain real-time active event lifecycle.",
        "BFD uses session_id when available, but session identity still depends on raw H3C message consistency.",
        "Optical events without interface fall back to device_ip + error_code.",
        "PPP usernames missing from raw logs are grouped under __missing__.",
    ]
    return {
        "raw_log_total": raw_log_total,
        "aggregatable_log_total": len(logs),
        "unaggregated_log_total": raw_log_total - len(logs),
        "alarm_event_total": len(events),
        "event_type_counts": top_rows(events_by_type, top_n),
        "compression_by_type": compression,
        "top_device_events": top_rows(collections.Counter(event["device_ip"] for event in events), top_n),
        "event_mode_counts": top_rows(collections.Counter(event["event_mode"] for event in events), top_n),
        "ppp_before_after": {
            "raw_logs": raw_by_type.get("PPP_AUTH_FAILURE", 0),
            "events": events_by_type.get("PPP_AUTH_FAILURE", 0),
        },
        "ptp_pairing": status_by_type.get("PTP_CLOCK_JITTER", {}),
        "bfd_pairing": status_by_type.get("BFD_FLAP", {}),
        "optical_pairing": status_by_type.get("OPTICAL_FAULT", {}),
        "open_events": open_events[:top_n],
        "recovered_or_flapping_events": recovered_events[:top_n],
        "rule_gaps": gaps,
    }


def load_baseline_summary(path: str) -> dict:
    if not path:
        return {}
    baseline_path = pathlib.Path(path)
    if not baseline_path.exists():
        return {}
    try:
        return json.loads(baseline_path.read_text(encoding="utf-8")).get("summary", {})
    except (OSError, json.JSONDecodeError):
        return {}


def count_from_rows(rows: List[dict], key: str) -> int:
    for row in rows:
        if row.get("key") == key:
            return int(row.get("count", 0))
    return 0


def build_task8_comparison(current: dict, baseline: dict) -> dict:
    if not baseline:
        return {}
    current_counts = current.get("event_type_counts", [])
    baseline_counts = baseline.get("event_type_counts", [])
    event_types = sorted({row["key"] for row in current_counts} | {row["key"] for row in baseline_counts})
    by_type = []
    for event_type in event_types:
        old = count_from_rows(baseline_counts, event_type)
        new = count_from_rows(current_counts, event_type)
        by_type.append({
            "event_type": event_type,
            "task8_events": old,
            "task8_1_events": new,
            "delta": new - old,
            "change_ratio": pct(new - old, old),
        })
    return {
        "task8_total_events": baseline.get("alarm_event_total", 0),
        "task8_1_total_events": current.get("alarm_event_total", 0),
        "total_delta": current.get("alarm_event_total", 0) - baseline.get("alarm_event_total", 0),
        "ppp_event_delta": count_from_rows(current_counts, "PPP_AUTH_FAILURE") - count_from_rows(baseline_counts, "PPP_AUTH_FAILURE"),
        "qos_event_delta": count_from_rows(current_counts, "QOS_CONGESTION") - count_from_rows(baseline_counts, "QOS_CONGESTION"),
        "by_event_type": by_type,
    }


def markdown_table(rows: List[dict], key_header: str = "Key") -> str:
    if not rows:
        return f"| {key_header} | Count |\n| --- | ---: |\n| (none) | 0 |"
    lines = [f"| {key_header} | Count |", "| --- | ---: |"]
    for row in rows:
        lines.append(f"| `{row['key']}` | {row['count']} |")
    return "\n".join(lines)


def compression_table(rows: List[dict]) -> str:
    lines = ["| event_type | raw_logs | events | logs/event | reduction |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| `{row['event_type']}` | {row['raw_logs']} | {row['events']} | {row['logs_per_event']} | {row['reduction_ratio']}% |")
    return "\n".join(lines)


def comparison_table(rows: List[dict]) -> str:
    if not rows:
        return "| event_type | Task 8 | Task 8.1 | Delta | Change |\n| --- | ---: | ---: | ---: | ---: |\n| (none) | 0 | 0 | 0 | 0.0% |"
    lines = ["| event_type | Task 8 | Task 8.1 | Delta | Change |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| `{row['event_type']}` | {row['task8_events']} | {row['task8_1_events']} | {row['delta']} | {row['change_ratio']}% |")
    return "\n".join(lines)


def event_list(events: List[dict]) -> str:
    if not events:
        return "- None"
    lines = []
    for event in events:
        lines.append(
            f"- `{event['event_type']}` `{event['event_status']}` `{event['device_ip']}` `{event['object_key']}` "
            f"{event['first_seen']} -> {event['last_seen']} count={event['event_count']}"
        )
    return "\n".join(lines)


def write_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Task 8.1 Alarm Event Aggregation Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Elasticsearch: `{report['elasticsearch_url']}`",
        f"- Index pattern: `{report['index']}`",
        f"- Lookback days: `{report['lookback_days']}`",
        f"- Raw logs: `{summary['raw_log_total']}`",
        f"- Aggregatable logs: `{summary['aggregatable_log_total']}`",
        f"- Unaggregated logs: `{summary['unaggregated_log_total']}`",
        f"- Alarm events: `{summary['alarm_event_total']}`",
        "",
        "## Event Type Counts",
        "",
        markdown_table(summary["event_type_counts"], "event_type"),
        "",
        "## Event Mode Counts",
        "",
        markdown_table(summary["event_mode_counts"], "event_mode"),
        "",
        "## Compression By Event Type",
        "",
        compression_table(summary["compression_by_type"]),
        "",
        "## Task 8 Comparison",
        "",
    ]
    comparison = summary.get("task8_comparison", {})
    if comparison:
        lines.extend([
            f"- Task 8 total events: `{comparison['task8_total_events']}`",
            f"- Task 8.1 total events: `{comparison['task8_1_total_events']}`",
            f"- Total event delta: `{comparison['total_delta']}`",
            f"- PPP event delta: `{comparison['ppp_event_delta']}`",
            f"- QoS event delta: `{comparison['qos_event_delta']}`",
            "",
            comparison_table(comparison["by_event_type"]),
            "",
        ])
    else:
        lines.extend(["- No Task 8 baseline JSON was available for comparison.", ""])
    lines.extend([
        "## TOP Device Event Ranking",
        "",
        markdown_table(summary["top_device_events"], "device_ip"),
        "",
        "## PPP Before / After",
        "",
        f"- Raw PPP logs: `{summary['ppp_before_after']['raw_logs']}`",
        f"- PPP events: `{summary['ppp_before_after']['events']}`",
        "",
        "## PTP Suppression / Resume Pairing",
        "",
        "```json",
        json.dumps(summary["ptp_pairing"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## BFD UP / DOWN Pairing",
        "",
        "```json",
        json.dumps(summary["bfd_pairing"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Optical Occur / Clear Pairing",
        "",
        "```json",
        json.dumps(summary["optical_pairing"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Open Events",
        "",
        event_list(summary["open_events"]),
        "",
        "## Recovered / Flapping Events",
        "",
        event_list(summary["recovered_or_flapping_events"]),
        "",
        "## Current Rule Gaps",
        "",
    ])
    lines.extend(f"- {gap}" for gap in summary["rule_gaps"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--index", default=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"))
    parser.add_argument("--days", type=int, default=int(os.getenv("TASK8_LOOKBACK_DAYS", "7")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("TASK8_BATCH_SIZE", "2000")))
    parser.add_argument("--top-n", type=int, default=int(os.getenv("TASK8_TOP_N", "20")))
    parser.add_argument("--event-family-rules", default="config/event_family_rules.yml")
    parser.add_argument("--field-extract-rules", default="config/field_extract_rules.yml")
    parser.add_argument("--aggregation-rules", default="config/event_aggregation_rules.yml")
    parser.add_argument("--out-dir", default=os.getenv("TASK8_OUT_DIR", "reports/task8_1"))
    parser.add_argument("--output-prefix", default=os.getenv("TASK8_OUTPUT_PREFIX", "task8_1_alarm_events"))
    parser.add_argument("--baseline-json", default=os.getenv("TASK8_BASELINE_JSON", "reports/task8/task8_alarm_events.json"))
    args = parser.parse_args()

    family_rules = load_event_family_rules(pathlib.Path(args.event_family_rules))
    field_rules = load_field_extract_rules(pathlib.Path(args.field_extract_rules))
    aggregation_rules = load_aggregation_rules(pathlib.Path(args.aggregation_rules))

    raw_docs = list(iter_es_docs(args.es_url, args.index, args.days, args.batch_size))
    logs = prepare_logs(raw_docs, family_rules, field_rules, aggregation_rules)
    events = aggregate_logs(logs, aggregation_rules)
    summary = summarize(len(raw_docs), logs, events, args.top_n)
    baseline = load_baseline_summary(args.baseline_json)
    if baseline:
        summary["task8_comparison"] = build_task8_comparison(summary, baseline)
    report = {
        "generated_at": iso_z(utc_now()),
        "elasticsearch_url": args.es_url,
        "index": args.index,
        "lookback_days": args.days,
        "rules": {
            "event_family_rules": args.event_family_rules,
            "field_extract_rules": args.field_extract_rules,
            "aggregation_rules": args.aggregation_rules,
        },
        "summary": summary,
        "events": events,
    }

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{args.output_prefix}.json"
    md_path = out_dir / f"{args.output_prefix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(write_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(json_path),
                "markdown": str(md_path),
                "raw_logs": report["summary"]["raw_log_total"],
                "aggregatable_logs": report["summary"]["aggregatable_log_total"],
                "alarm_events": report["summary"]["alarm_event_total"],
                "event_type_counts": report["summary"]["event_type_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
