#!/usr/bin/env python3
"""Run alarm event aggregation as a fixed-lookback micro-batch worker."""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import time
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workers.event_aggregation_worker import run_once  # noqa: E402


LOGGER = logging.getLogger("alarm_event_worker")


def load_env_file(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--lookback-minutes", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE", "deploy/.env"))
    parser.add_argument("--log-level", default=os.getenv("ALARM_EVENT_WORKER_LOG_LEVEL", "INFO"))
    parser.add_argument("--es-url", default=None)
    parser.add_argument("--source-index", default=None)
    parser.add_argument("--target-index-prefix", default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    return parser.parse_args()


def build_worker_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        es_url=args.es_url or os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        source_index=args.source_index or os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"),
        target_index_prefix=args.target_index_prefix or os.getenv("ALARM_EVENTS_INDEX_PREFIX", "jscn-aiops-alarm-events"),
        family_rules=os.getenv("EVENT_FAMILY_RULES", "config/event_family_rules.yml"),
        field_rules=os.getenv("FIELD_EXTRACT_RULES", "config/field_extract_rules.yml"),
        aggregation_rules=os.getenv("EVENT_AGGREGATION_RULES", "config/event_aggregation_rules.yml"),
        template=os.getenv("ALARM_EVENTS_TEMPLATE", "deploy/elasticsearch/templates/alarm_events_template.json"),
        checkpoint=os.getenv("EVENT_AGGREGATOR_CHECKPOINT", "/data/jscn-aiops/runtime/checkpoints/event_aggregator.json"),
        out_dir=os.getenv("TASK10_OUT_DIR", "/data/jscn-aiops/reports/task10"),
        report=os.getenv("TASK10_REPORT", "/data/jscn-aiops/reports/task10/task10_worker_run_report.md"),
        lookback_minutes=args.lookback_minutes
        if args.lookback_minutes is not None
        else int(os.getenv("ALARM_EVENT_WORKER_LOOKBACK_MINUTES", "30")),
        batch_size=args.batch_size if args.batch_size is not None else int(os.getenv("EVENT_AGGREGATOR_BATCH_SIZE", "1000")),
        dry_run=args.dry_run,
        use_checkpoint=False,
    )


def log_report(report: dict, elapsed_seconds: float, error_count: int) -> None:
    payload = {
        "window_start": report.get("query_start"),
        "window_end": report.get("query_end"),
        "scanned": report.get("raw_syslog_count", 0),
        "prepared": report.get("prepared_log_count", 0),
        "generated": report.get("generated_event_count", 0),
        "written": report.get("upserted", 0),
        "failed": report.get("failed", 0),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "error_count": error_count,
        "dry_run": report.get("dry_run", False),
    }
    LOGGER.info("alarm event worker round %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    interval_seconds = args.interval_seconds
    if interval_seconds is None:
        interval_seconds = int(os.getenv("ALARM_EVENT_WORKER_INTERVAL_SECONDS", "300"))
    worker_args = build_worker_args(args)
    LOGGER.info(
        "starting alarm event worker interval_seconds=%s lookback_minutes=%s dry_run=%s es_url=%s",
        interval_seconds,
        worker_args.lookback_minutes,
        worker_args.dry_run,
        worker_args.es_url,
    )

    exit_code = 0
    while True:
        started = time.monotonic()
        try:
            report = run_once(worker_args)
            elapsed = time.monotonic() - started
            error_count = int(report.get("failed", 0)) + len(report.get("errors", []))
            log_report(report, elapsed, error_count)
            if report.get("failed"):
                exit_code = 1
        except Exception:
            elapsed = time.monotonic() - started
            exit_code = 1
            LOGGER.exception("alarm event worker round failed elapsed_seconds=%.3f", elapsed)

        if args.once:
            return exit_code
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
