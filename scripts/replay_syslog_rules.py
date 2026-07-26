#!/usr/bin/env python3
"""Replay configurable Syslog parsing rules against Elasticsearch data.

The script is read-only for Elasticsearch. It loads the YAML rule files,
queries recent Syslog documents, recomputes event_family, extracted_fields,
and parse_status, then writes JSON and Markdown validation reports.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
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


def read_clean_lines(path: pathlib.Path) -> List[Tuple[int, str]]:
    lines: List[Tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    return lines


def load_event_family_rules(path: pathlib.Path) -> Dict[str, Any]:
    rules: Dict[str, Any] = {"default_family": "unknown", "families": {}}
    current_family: Optional[str] = None
    current_section: Optional[str] = None
    in_families = False

    for indent, line in read_clean_lines(path):
        if indent == 0 and line.startswith("default_family:"):
            rules["default_family"] = strip_quotes(line.split(":", 1)[1])
            continue
        if indent == 0 and line == "families:":
            in_families = True
            continue
        if not in_families:
            continue
        if indent == 2 and line.endswith(":"):
            current_family = line[:-1]
            rules["families"][current_family] = {
                "event_codes": [],
                "modules": [],
                "keywords": [],
            }
            current_section = None
            continue
        if indent == 4 and line.endswith(":") and current_family:
            current_section = line[:-1]
            rules["families"][current_family].setdefault(current_section, [])
            continue
        if indent == 6 and line.startswith("- ") and current_family and current_section:
            rules["families"][current_family][current_section].append(strip_quotes(line[2:]))

    return rules


def load_field_extract_rules(path: pathlib.Path) -> Dict[str, Any]:
    rules: Dict[str, Any] = {"families": {}}
    current_family: Optional[str] = None
    current_section: Optional[str] = None
    current_field: Optional[str] = None
    in_families = False

    for indent, line in read_clean_lines(path):
        if indent == 0 and line == "families:":
            in_families = True
            continue
        if not in_families:
            continue
        if indent == 2 and line.endswith(":"):
            current_family = line[:-1]
            rules["families"][current_family] = {"core_fields": [], "patterns": {}}
            current_section = None
            current_field = None
            continue
        if indent == 4 and line.endswith(":") and current_family:
            current_section = line[:-1]
            current_field = None
            continue
        if (
            indent == 6
            and line.startswith("- ")
            and current_family
            and current_section == "core_fields"
        ):
            rules["families"][current_family]["core_fields"].append(strip_quotes(line[2:]))
            continue
        if (
            indent == 6
            and line.endswith(":")
            and current_family
            and current_section == "patterns"
        ):
            current_field = line[:-1]
            rules["families"][current_family]["patterns"][current_field] = []
            continue
        if (
            indent == 8
            and line.startswith("- ")
            and current_family
            and current_section == "patterns"
            and current_field
        ):
            rules["families"][current_family]["patterns"][current_field].append(
                strip_quotes(line[2:])
            )

    return rules


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def es_request(es_url: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        es_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    return json.loads(payload)


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
            "log_time",
            "source_ip",
            "device_name",
            "device_ip",
            "module",
            "severity",
            "event_code",
            "event_family",
            "parse_status",
            "raw_message",
            "message",
        ],
        "query": {
            "range": {
                "@timestamp": {
                    "gte": f"now-{days}d",
                    "lte": "now",
                }
            }
        },
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
            if not scroll_id:
                break
            response = es_request(es_url, "POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
            scroll_id = response.get("_scroll_id", scroll_id)
    finally:
        clear_scroll(es_url, scroll_id)


def normalize(value: Any) -> str:
    return str(value or "").strip()


def classify_event(doc: dict, family_rules: dict) -> str:
    event_code = normalize(doc.get("event_code")).upper()
    module = normalize(doc.get("module")).upper()
    raw_message = normalize(doc.get("raw_message") or doc.get("message"))
    raw_upper = raw_message.upper()

    for family, rule in family_rules["families"].items():
        if event_code and event_code in {item.upper() for item in rule.get("event_codes", [])}:
            return family
    for family, rule in family_rules["families"].items():
        modules = {item.upper() for item in rule.get("modules", [])}
        if module and module in modules:
            return family
    for family, rule in family_rules["families"].items():
        for keyword in rule.get("keywords", []):
            if keyword and keyword.upper() in raw_upper:
                return family
    return family_rules.get("default_family", "unknown")


def extract_fields(doc: dict, event_family: str, field_rules: dict) -> dict:
    raw_message = normalize(doc.get("raw_message") or doc.get("message"))
    extracted: Dict[str, str] = {}
    family_rule = field_rules.get("families", {}).get(event_family, {})
    patterns = family_rule.get("patterns", {})

    for field, regexes in patterns.items():
        if field in extracted:
            continue
        for regex in regexes:
            try:
                match = re.search(regex, raw_message)
            except re.error as exc:
                extracted[f"_regex_error_{field}"] = str(exc)
                continue
            if not match:
                continue
            named = {name: value.strip() for name, value in match.groupdict().items() if value}
            if named:
                extracted.update(named)
            elif match.group(0):
                extracted[field] = match.group(0).strip()
            break
    return extracted


def compute_parse_status(event_family: str, extracted: dict, field_rules: dict) -> str:
    if event_family == "unknown":
        return "failed"
    core_fields = field_rules.get("families", {}).get(event_family, {}).get("core_fields", [])
    if not core_fields:
        return "parsed"
    matched = sum(1 for field in core_fields if extracted.get(field))
    if matched == len(core_fields):
        return "parsed"
    return "partial"


def top_items(counter: collections.Counter, limit: int) -> List[dict]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 2)


def summarize(events: List[dict], field_rules: dict, top_n: int) -> dict:
    total = len(events)
    family_counts = collections.Counter(event["event_family"] for event in events)
    status_counts = collections.Counter(event["parse_status"] for event in events)
    unknown = [event for event in events if event["event_family"] == "unknown"]
    unknown_codes = collections.Counter(event["event_code"] or "__missing__" for event in unknown)

    field_success: Dict[str, dict] = {}
    for family, rule in field_rules.get("families", {}).items():
        family_events = [event for event in events if event["event_family"] == family]
        total_family = len(family_events)
        field_names = list(rule.get("patterns", {}).keys())
        field_success[family] = {
            "total": total_family,
            "fields": {
                field: {
                    "success": sum(1 for event in family_events if event["extracted_fields"].get(field)),
                    "rate": pct(
                        sum(1 for event in family_events if event["extracted_fields"].get(field)),
                        total_family,
                    ),
                }
                for field in field_names
            },
        }

    ppp_events = [event for event in events if event["event_family"] == "ppp_auth"]
    ptp_events = [event for event in events if event["event_family"] == "ptp_clock"]
    bfd_events = [event for event in events if event["event_family"] == "bfd_flap"]
    optical_events = [event for event in events if event["event_family"] == "optical_fault"]

    ptp_offsets = [
        int(event["extracted_fields"]["time_offset"])
        for event in ptp_events
        if str(event["extracted_fields"].get("time_offset", "")).lstrip("-").isdigit()
    ]
    ptp_thresholds = [
        int(event["extracted_fields"]["threshold"])
        for event in ptp_events
        if str(event["extracted_fields"].get("threshold", "")).lstrip("-").isdigit()
    ]
    bfd_transitions = collections.Counter(
        f"{event['extracted_fields'].get('old_state', '__missing__')}->{event['extracted_fields'].get('new_state', '__missing__')}"
        for event in bfd_events
    )

    gaps = []
    if unknown:
        gaps.append("Unknown event codes still need family rules.")
    for family, details in field_success.items():
        if details["total"] == 0:
            continue
        core_fields = field_rules.get("families", {}).get(family, {}).get("core_fields", [])
        low_fields = [
            field
            for field, stat in details["fields"].items()
            if field in core_fields and stat["rate"] < 80.0
        ]
        if low_fields:
            gaps.append(f"{family} low extraction fields: {', '.join(low_fields)}.")

    return {
        "total_logs": total,
        "event_family_distribution": top_items(family_counts, top_n),
        "parse_status_distribution": top_items(status_counts, top_n),
        "unknown_count": len(unknown),
        "unknown_ratio": pct(len(unknown), total),
        "unknown_event_code_top": top_items(unknown_codes, top_n),
        "field_success_by_family": field_success,
        "ppp_stats": {
            "total": len(ppp_events),
            "username_success": sum(1 for event in ppp_events if event["extracted_fields"].get("username")),
            "domain_success": sum(1 for event in ppp_events if event["extracted_fields"].get("domain")),
            "top_domains": top_items(collections.Counter(event["extracted_fields"].get("domain", "__missing__") for event in ppp_events), top_n),
        },
        "ptp_stats": {
            "total": len(ptp_events),
            "time_offset_success": len(ptp_offsets),
            "threshold_success": len(ptp_thresholds),
            "time_offset_avg": round(statistics.mean(ptp_offsets), 2) if ptp_offsets else None,
            "time_offset_max": max(ptp_offsets) if ptp_offsets else None,
            "threshold_values": top_items(collections.Counter(ptp_thresholds), top_n),
        },
        "bfd_stats": {
            "total": len(bfd_events),
            "state_change_success": sum(
                1
                for event in bfd_events
                if event["extracted_fields"].get("old_state") and event["extracted_fields"].get("new_state")
            ),
            "top_transitions": top_items(bfd_transitions, top_n),
        },
        "optical_stats": {
            "total": len(optical_events),
            "interface_success": sum(1 for event in optical_events if event["extracted_fields"].get("interface")),
            "error_code_success": sum(1 for event in optical_events if event["extracted_fields"].get("error_code")),
            "top_interfaces": top_items(collections.Counter(event["extracted_fields"].get("interface", "__missing__") for event in optical_events), top_n),
            "top_error_codes": top_items(collections.Counter(event["extracted_fields"].get("error_code", "__missing__") for event in optical_events), top_n),
        },
        "gaps": gaps,
        "next_suggestions": [
            "Add rules for high-frequency unknown event_code values.",
            "Tune core fields after reviewing real samples with partial parse_status.",
            "Use event_family plus extracted_fields as the input contract for Task 8 event aggregation.",
        ],
    }


def table(rows: List[dict], key_name: str = "Key") -> str:
    if not rows:
        return f"| {key_name} | Count |\n| --- | ---: |\n| (none) | 0 |"
    lines = [f"| {key_name} | Count |", "| --- | ---: |"]
    for row in rows:
        lines.append(f"| `{row['key']}` | {row['count']} |")
    return "\n".join(lines)


def field_success_markdown(summary: dict) -> str:
    lines = ["| event_family | total | field | success | rate |", "| --- | ---: | --- | ---: | ---: |"]
    for family, details in summary["field_success_by_family"].items():
        if not details["fields"]:
            lines.append(f"| `{family}` | {details['total']} | (none) | 0 | 0.0% |")
            continue
        for field, stat in details["fields"].items():
            lines.append(
                f"| `{family}` | {details['total']} | `{field}` | {stat['success']} | {stat['rate']}% |"
            )
    return "\n".join(lines)


def write_parse_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Task 7 Syslog Parse Replay Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Elasticsearch: `{report['elasticsearch_url']}`",
        f"- Index pattern: `{report['index']}`",
        f"- Lookback days: `{report['lookback_days']}`",
        f"- Total logs: `{summary['total_logs']}`",
        f"- Unknown: `{summary['unknown_count']}` (`{summary['unknown_ratio']}%`)",
        "",
        "## Event Family Distribution",
        "",
        table(summary["event_family_distribution"], "event_family"),
        "",
        "## Parse Status Distribution",
        "",
        table(summary["parse_status_distribution"], "parse_status"),
        "",
        "## Unknown Event Code TOP",
        "",
        table(summary["unknown_event_code_top"], "event_code"),
        "",
        "## Field Extraction Success",
        "",
        field_success_markdown(summary),
        "",
        "## PPP Username / Domain",
        "",
        f"- Total PPP logs: `{summary['ppp_stats']['total']}`",
        f"- Username extracted: `{summary['ppp_stats']['username_success']}`",
        f"- Domain extracted: `{summary['ppp_stats']['domain_success']}`",
        "",
        table(summary["ppp_stats"]["top_domains"], "domain"),
        "",
        "## PTP Time Offset / Threshold",
        "",
        f"- Total PTP logs: `{summary['ptp_stats']['total']}`",
        f"- time_offset extracted: `{summary['ptp_stats']['time_offset_success']}`",
        f"- threshold extracted: `{summary['ptp_stats']['threshold_success']}`",
        f"- time_offset avg: `{summary['ptp_stats']['time_offset_avg']}`",
        f"- time_offset max: `{summary['ptp_stats']['time_offset_max']}`",
        "",
        table(summary["ptp_stats"]["threshold_values"], "threshold"),
        "",
        "## BFD State Changes",
        "",
        f"- Total BFD logs: `{summary['bfd_stats']['total']}`",
        f"- State change extracted: `{summary['bfd_stats']['state_change_success']}`",
        "",
        table(summary["bfd_stats"]["top_transitions"], "transition"),
        "",
        "## Optical Interface / Error Code",
        "",
        f"- Total Optical logs: `{summary['optical_stats']['total']}`",
        f"- interface extracted: `{summary['optical_stats']['interface_success']}`",
        f"- error_code extracted: `{summary['optical_stats']['error_code_success']}`",
        "",
        "### Top Optical Interfaces",
        "",
        table(summary["optical_stats"]["top_interfaces"], "interface"),
        "",
        "### Top Optical Error Codes",
        "",
        table(summary["optical_stats"]["top_error_codes"], "error_code"),
        "",
        "## Current Rule Gaps",
        "",
    ]
    if summary["gaps"]:
        lines.extend(f"- {item}" for item in summary["gaps"])
    else:
        lines.append("- No major gaps found in this replay window.")
    lines.extend(["", "## Next Suggestions", ""])
    lines.extend(f"- {item}" for item in summary["next_suggestions"])
    lines.append("")
    return "\n".join(lines)


def write_unknown_markdown(report: dict, unknown_samples: List[dict]) -> str:
    summary = report["summary"]
    lines = [
        "# Task 7 Unknown Event Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Unknown count: `{summary['unknown_count']}`",
        f"- Unknown ratio: `{summary['unknown_ratio']}%`",
        "",
        "## Unknown Event Code TOP",
        "",
        table(summary["unknown_event_code_top"], "event_code"),
        "",
        "## Samples",
        "",
    ]
    if not unknown_samples:
        lines.append("- No unknown samples in this replay window.")
    else:
        for idx, sample in enumerate(unknown_samples, start=1):
            lines.extend(
                [
                    f"### Sample {idx}",
                    "",
                    f"- timestamp: `{sample.get('@timestamp', '')}`",
                    f"- device_ip: `{sample.get('device_ip', '')}`",
                    f"- device_name: `{sample.get('device_name', '')}`",
                    f"- module: `{sample.get('module', '')}`",
                    f"- event_code: `{sample.get('event_code', '')}`",
                    "",
                    "```text",
                    normalize(sample.get("raw_message") or sample.get("message")),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--index", default=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"))
    parser.add_argument("--days", type=int, default=int(os.getenv("TASK7_LOOKBACK_DAYS", "7")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("TASK7_BATCH_SIZE", "1000")))
    parser.add_argument("--top-n", type=int, default=int(os.getenv("TASK7_TOP_N", "10")))
    parser.add_argument("--sample-size", type=int, default=int(os.getenv("TASK7_UNKNOWN_SAMPLE_SIZE", "10")))
    parser.add_argument("--event-family-rules", default="config/event_family_rules.yml")
    parser.add_argument("--field-extract-rules", default="config/field_extract_rules.yml")
    parser.add_argument("--out-dir", default=os.getenv("TASK7_OUT_DIR", "reports/task7"))
    args = parser.parse_args()

    family_rules = load_event_family_rules(pathlib.Path(args.event_family_rules))
    field_rules = load_field_extract_rules(pathlib.Path(args.field_extract_rules))

    events = []
    for doc in iter_es_docs(args.es_url, args.index, args.days, args.batch_size):
        event_family = classify_event(doc, family_rules)
        extracted = extract_fields(doc, event_family, field_rules)
        parse_status = compute_parse_status(event_family, extracted, field_rules)
        events.append(
            {
                "@timestamp": doc.get("@timestamp"),
                "device_ip": doc.get("device_ip"),
                "device_name": doc.get("device_name"),
                "module": doc.get("module"),
                "severity": doc.get("severity"),
                "event_code": doc.get("event_code"),
                "event_family": event_family,
                "parse_status": parse_status,
                "extracted_fields": extracted,
                "raw_message": doc.get("raw_message") or doc.get("message"),
            }
        )

    now = utc_now()
    unknown_samples = [
        event for event in events if event["event_family"] == "unknown"
    ][: args.sample_size]
    report = {
        "generated_at": iso_z(now),
        "elasticsearch_url": args.es_url,
        "index": args.index,
        "lookback_days": args.days,
        "rules": {
            "event_family_rules": args.event_family_rules,
            "field_extract_rules": args.field_extract_rules,
        },
        "summary": summarize(events, field_rules, args.top_n),
        "sample_events": events[: min(20, len(events))],
    }

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "task7_parse_report.json"
    md_path = out_dir / "task7_parse_report.md"
    unknown_path = out_dir / "unknown_event_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(write_parse_markdown(report), encoding="utf-8")
    unknown_path.write_text(write_unknown_markdown(report, unknown_samples), encoding="utf-8")

    print(
        json.dumps(
            {
                "json": str(json_path),
                "markdown": str(md_path),
                "unknown_report": str(unknown_path),
                "total_logs": report["summary"]["total_logs"],
                "unknown_count": report["summary"]["unknown_count"],
                "unknown_ratio": report["summary"]["unknown_ratio"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
