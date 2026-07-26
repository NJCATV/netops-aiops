#!/usr/bin/env python3
"""Persist generated alarm events into Elasticsearch idempotently."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple


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


def es_request(es_url: str, method: str, path: str, body: Optional[dict] = None, ndjson: Optional[str] = None) -> dict:
    if ndjson is not None:
        data = ndjson.encode("utf-8")
        headers = {"Content-Type": "application/x-ndjson"}
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        data = None
        headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(es_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    return json.loads(payload) if payload else {}


def load_events(path: pathlib.Path) -> List[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        return data["events"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unsupported alarm events JSON shape: {path}")


def index_name(prefix: str, event: dict) -> str:
    first_seen = parse_time(event.get("first_seen")) or utc_now()
    return f"{prefix}-{first_seen.strftime('%Y.%m.%d')}"


def normalize_event(event: dict, now: str) -> dict:
    doc = dict(event)
    doc.setdefault("event_mode", "lifecycle")
    doc["@timestamp"] = doc.get("first_seen") or now
    doc["created_at"] = doc.get("created_at") or now
    doc["updated_at"] = now
    doc["extracted_metrics"] = doc.get("extracted_metrics") or {}
    doc["raw_log_samples"] = doc.get("raw_log_samples") or []
    return doc


def install_template(es_url: str, template_path: pathlib.Path, template_name: str) -> dict:
    body = json.loads(template_path.read_text(encoding="utf-8"))
    return es_request(es_url, "PUT", f"/_index_template/{template_name}", body)


def bulk_upsert(es_url: str, events: List[dict], index_prefix: str, batch_size: int) -> dict:
    now = iso_z(utc_now())
    created_or_updated = 0
    failed = 0
    errors: List[dict] = []
    batch: List[dict] = []

    def flush(items: List[dict]) -> None:
        nonlocal created_or_updated, failed
        if not items:
            return
        lines: List[str] = []
        for event in items:
            doc = normalize_event(event, now)
            event_id = doc.get("event_id")
            if not event_id:
                failed += 1
                errors.append({"error": "missing event_id", "event": event})
                continue
            lines.append(json.dumps({"update": {"_index": index_name(index_prefix, doc), "_id": event_id}}, ensure_ascii=False))
            lines.append(json.dumps({"doc": doc, "doc_as_upsert": True}, ensure_ascii=False))
        if not lines:
            return
        result = es_request(es_url, "POST", "/_bulk", ndjson="\n".join(lines) + "\n")
        for item in result.get("items", []):
            update = item.get("update", {})
            if update.get("error"):
                failed += 1
                errors.append(update)
            else:
                created_or_updated += 1

    for event in events:
        batch.append(event)
        if len(batch) >= batch_size:
            flush(batch)
            batch = []
    flush(batch)
    return {"upserted": created_or_updated, "failed": failed, "errors": errors[:20]}


def agg_terms(es_url: str, index_pattern: str, field: str) -> List[dict]:
    body = {
        "size": 0,
        "aggs": {
            "top": {
                "terms": {"field": field, "size": 10, "missing": "__missing__"}
            }
        },
    }
    result = es_request(es_url, "POST", f"/{index_pattern}/_search", body)
    return [{"key": item["key"], "count": item["doc_count"]} for item in result.get("aggregations", {}).get("top", {}).get("buckets", [])]


def count_docs(es_url: str, index_pattern: str) -> int:
    result = es_request(es_url, "GET", f"/{index_pattern}/_count")
    return int(result.get("count", 0))


def write_report(path: pathlib.Path, report: dict) -> None:
    lines = [
        "# Task 9 Alarm Events ES Import Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Elasticsearch: `{report['elasticsearch_url']}`",
        f"- Source JSON: `{report['source_json']}`",
        f"- Index prefix: `{report['index_prefix']}`",
        f"- Dry run: `{report['dry_run']}`",
        f"- Source events: `{report['source_event_count']}`",
        f"- Upserted events: `{report['upserted']}`",
        f"- Failed events: `{report['failed']}`",
        f"- Indexed document count: `{report['indexed_doc_count']}`",
        "",
        "## Top event_type",
        "",
        table(report["top_event_type"], "event_type"),
        "",
        "## Top device_ip",
        "",
        table(report["top_device_ip"], "device_ip"),
        "",
        "## Top event_status",
        "",
        table(report["top_event_status"], "event_status"),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def table(rows: List[dict], key_header: str) -> str:
    if not rows:
        return f"| {key_header} | Count |\n| --- | ---: |\n| (none) | 0 |"
    lines = [f"| {key_header} | Count |", "| --- | ---: |"]
    for row in rows:
        lines.append(f"| `{row['key']}` | {row['count']} |")
    return "\n".join(lines)


def write_events_to_es(
    es_url: str,
    events_json: pathlib.Path,
    index_prefix: str,
    template_path: pathlib.Path,
    report_path: pathlib.Path,
    batch_size: int,
    dry_run: bool,
    install_index_template: bool,
) -> dict:
    events = load_events(events_json)
    index_pattern = f"{index_prefix}-*"
    if install_index_template and not dry_run:
        install_template(es_url, template_path, "jscn-aiops-alarm-events")
    result = {"upserted": 0, "failed": 0, "errors": []}
    if not dry_run:
        result = bulk_upsert(es_url, events, index_prefix, batch_size)
    report = {
        "generated_at": iso_z(utc_now()),
        "elasticsearch_url": es_url,
        "source_json": str(events_json),
        "index_prefix": index_prefix,
        "dry_run": dry_run,
        "source_event_count": len(events),
        "upserted": result["upserted"],
        "failed": result["failed"],
        "errors": result["errors"],
        "indexed_doc_count": 0 if dry_run else count_docs(es_url, index_pattern),
        "top_event_type": [] if dry_run else agg_terms(es_url, index_pattern, "event_type"),
        "top_device_ip": [] if dry_run else agg_terms(es_url, index_pattern, "device_ip"),
        "top_event_status": [] if dry_run else agg_terms(es_url, index_pattern, "event_status"),
    }
    write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--events-json", default=os.getenv("ALARM_EVENTS_JSON", "reports/task8_1/task8_1_alarm_events.json"))
    parser.add_argument("--index-prefix", default=os.getenv("ALARM_EVENTS_INDEX_PREFIX", "jscn-aiops-alarm-events"))
    parser.add_argument("--template", default=os.getenv("ALARM_EVENTS_TEMPLATE", "deploy/elasticsearch/templates/alarm_events_template.json"))
    parser.add_argument("--report", default=os.getenv("TASK9_REPORT", "reports/task9/task9_es_import_report.md"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("TASK9_BATCH_SIZE", "1000")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-template", action="store_true")
    args = parser.parse_args()
    report = write_events_to_es(
        args.es_url,
        pathlib.Path(args.events_json),
        args.index_prefix,
        pathlib.Path(args.template),
        pathlib.Path(args.report),
        args.batch_size,
        args.dry_run,
        not args.skip_template,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
