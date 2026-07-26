#!/usr/bin/env python3
"""Incrementally aggregate Syslog documents into alarm events.

Task 10 turns the offline Task 8.1 aggregation flow into a repeatable worker:
it reads a checkpoint, queries new Syslog documents, generates alarm events,
upserts them to Elasticsearch, and advances the checkpoint after a successful
non-dry-run execution.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
from typing import Any, Dict, Iterable, List, Optional


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_alarm_events as aggregation  # noqa: E402
import write_alarm_events_to_es as event_writer  # noqa: E402


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


def load_checkpoint(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(path: pathlib.Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def query_start_from_checkpoint(checkpoint: dict, lookback_minutes: int, now: dt.datetime) -> dt.datetime:
    last_success = parse_time(checkpoint.get("last_success_at"))
    if last_success:
        return last_success
    return now - dt.timedelta(minutes=lookback_minutes)


def clear_scroll(es_url: str, scroll_id: Optional[str]) -> None:
    if not scroll_id:
        return
    try:
        aggregation.es_request(es_url, "DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
    except Exception:
        return


def iter_es_docs_range(
    es_url: str,
    index: str,
    start: dt.datetime,
    end: dt.datetime,
    batch_size: int,
) -> Iterable[dict]:
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
        "query": {
            "range": {
                "@timestamp": {
                    "gte": iso_z(start),
                    "lt": iso_z(end),
                }
            }
        },
    }
    scroll_id: Optional[str] = None
    try:
        response = aggregation.es_request(es_url, "POST", f"/{index}/_search?scroll=2m", body)
        scroll_id = response.get("_scroll_id")
        while True:
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                yield hit.get("_source", {})
            response = aggregation.es_request(es_url, "POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
            scroll_id = response.get("_scroll_id", scroll_id)
    finally:
        clear_scroll(es_url, scroll_id)


def write_worker_report(path: pathlib.Path, report: dict) -> None:
    lines = [
        "# Task 10 Event Aggregation Worker Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Elasticsearch: `{report['elasticsearch_url']}`",
        f"- Source index: `{report['source_index']}`",
        f"- Target index prefix: `{report['target_index_prefix']}`",
        f"- Query start: `{report['query_start']}`",
        f"- Query end: `{report['query_end']}`",
        f"- Dry run: `{report['dry_run']}`",
        f"- Raw Syslog documents: `{report['raw_syslog_count']}`",
        f"- Prepared logs: `{report['prepared_log_count']}`",
        f"- Generated events: `{report['generated_event_count']}`",
        f"- Upserted events: `{report['upserted']}`",
        f"- Failed events: `{report['failed']}`",
        f"- Checkpoint path: `{report['checkpoint_path']}`",
        f"- Checkpoint updated: `{report['checkpoint_updated']}`",
        "",
        "## Event Type Counts",
        "",
        table(report["event_type_counts"], "event_type"),
        "",
        "## Event Status Counts",
        "",
        table(report["event_status_counts"], "event_status"),
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


def count_by(events: List[dict], field: str) -> List[dict]:
    counts: Dict[str, int] = {}
    for event in events:
        key = str(event.get(field) or "__missing__")
        counts[key] = counts.get(key, 0) + 1
    return [{"key": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def run_once(args: argparse.Namespace) -> dict:
    now = utc_now()
    checkpoint_path = pathlib.Path(args.checkpoint)
    checkpoint = load_checkpoint(checkpoint_path)
    if getattr(args, "use_checkpoint", True):
        start = query_start_from_checkpoint(checkpoint, args.lookback_minutes, now)
    else:
        start = now - dt.timedelta(minutes=args.lookback_minutes)
    end = now

    family_rules = aggregation.load_event_family_rules(pathlib.Path(args.family_rules))
    field_rules = aggregation.load_field_extract_rules(pathlib.Path(args.field_rules))
    aggregation_rules = aggregation.load_aggregation_rules(pathlib.Path(args.aggregation_rules))

    raw_docs = list(iter_es_docs_range(args.es_url, args.source_index, start, end, args.batch_size))
    prepared_logs = aggregation.prepare_logs(raw_docs, family_rules, field_rules, aggregation_rules)
    events = aggregation.aggregate_logs(prepared_logs, aggregation_rules)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / f"{end.strftime('%Y%m%d-%H%M%S')}-worker-events.json"
    events_path.write_text(
        json.dumps(
            {
                "generated_at": iso_z(end),
                "query_start": iso_z(start),
                "query_end": iso_z(end),
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = {"upserted": 0, "failed": 0, "errors": []}
    if not args.dry_run:
        event_writer.install_template(args.es_url, pathlib.Path(args.template), "jscn-aiops-alarm-events")
        result = event_writer.bulk_upsert(args.es_url, events, args.target_index_prefix, args.batch_size)

    checkpoint_updated = False
    if getattr(args, "use_checkpoint", True) and not args.dry_run and result["failed"] == 0:
        save_checkpoint(
            checkpoint_path,
            {
                "last_success_at": iso_z(end),
                "last_query_start": iso_z(start),
                "last_query_end": iso_z(end),
                "last_raw_syslog_count": len(raw_docs),
                "last_prepared_log_count": len(prepared_logs),
                "last_event_count": len(events),
                "last_upserted_count": result["upserted"],
                "updated_at": iso_z(utc_now()),
            },
        )
        checkpoint_updated = True

    report = {
        "generated_at": iso_z(utc_now()),
        "elasticsearch_url": args.es_url,
        "source_index": args.source_index,
        "target_index_prefix": args.target_index_prefix,
        "query_start": iso_z(start),
        "query_end": iso_z(end),
        "dry_run": args.dry_run,
        "raw_syslog_count": len(raw_docs),
        "prepared_log_count": len(prepared_logs),
        "generated_event_count": len(events),
        "upserted": result["upserted"],
        "failed": result["failed"],
        "errors": result["errors"],
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_updated": checkpoint_updated,
        "events_json": str(events_path),
        "event_type_counts": count_by(events, "event_type"),
        "event_status_counts": count_by(events, "event_status"),
    }
    write_worker_report(pathlib.Path(args.report), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--source-index", default=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"))
    parser.add_argument("--target-index-prefix", default=os.getenv("ALARM_EVENTS_INDEX_PREFIX", "jscn-aiops-alarm-events"))
    parser.add_argument("--family-rules", default=os.getenv("EVENT_FAMILY_RULES", "config/event_family_rules.yml"))
    parser.add_argument("--field-rules", default=os.getenv("FIELD_EXTRACT_RULES", "config/field_extract_rules.yml"))
    parser.add_argument("--aggregation-rules", default=os.getenv("EVENT_AGGREGATION_RULES", "config/event_aggregation_rules.yml"))
    parser.add_argument("--template", default=os.getenv("ALARM_EVENTS_TEMPLATE", "deploy/elasticsearch/templates/alarm_events_template.json"))
    parser.add_argument(
        "--checkpoint",
        default=os.getenv("EVENT_AGGREGATOR_CHECKPOINT", "/data/jscn-aiops/runtime/checkpoints/event_aggregator.json"),
    )
    parser.add_argument("--out-dir", default=os.getenv("TASK10_OUT_DIR", "/data/jscn-aiops/reports/task10"))
    parser.add_argument("--report", default=os.getenv("TASK10_REPORT", "/data/jscn-aiops/reports/task10/task10_worker_run_report.md"))
    parser.add_argument("--lookback-minutes", type=int, default=int(os.getenv("EVENT_AGGREGATOR_LOOKBACK_MINUTES", "10")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("EVENT_AGGREGATOR_BATCH_SIZE", "1000")))
    parser.add_argument("--interval-seconds", type=int, default=int(os.getenv("EVENT_AGGREGATOR_INTERVAL_SECONDS", "300")))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-checkpoint", action="store_true", help="Always query the configured lookback window instead of advancing from checkpoint.")
    args = parser.parse_args()
    args.use_checkpoint = not args.no_checkpoint

    while True:
        report = run_once(args)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.once:
            return 1 if report["failed"] else 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
