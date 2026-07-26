#!/usr/bin/env python3
"""Check whether generated alarm events are fresh relative to source data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import pathlib
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_env_file(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def parse_time(value: Any) -> Optional[dt.datetime]:
    if value is None:
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


def iso_z(value: Optional[dt.datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def es_request(es_url: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        es_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    return json.loads(payload) if payload else {}


def max_timestamp(es_url: str, index: str, field: str) -> Optional[dt.datetime]:
    body = {"size": 0, "aggs": {"latest": {"max": {"field": field}}}}
    result = es_request(es_url, "POST", f"/{index}/_search", body)
    value = result.get("aggregations", {}).get("latest", {}).get("value_as_string")
    return parse_time(value)


def count_since(es_url: str, index: str, field: str, hours: int) -> int:
    body = {"query": {"range": {field: {"gte": f"now-{hours}h", "lte": "now"}}}}
    result = es_request(es_url, "POST", f"/{index}/_count", body)
    return int(result.get("count", 0))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=None)
    parser.add_argument("--syslog-index", default=None)
    parser.add_argument("--trap-index", default=None)
    parser.add_argument("--event-index", default=None)
    parser.add_argument("--max-lag-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE", "deploy/.env"))
    parser.add_argument("--log-level", default=os.getenv("ALARM_EVENT_FRESHNESS_LOG_LEVEL", "WARNING"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))
    es_url = args.es_url or os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
    syslog_index = args.syslog_index or os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*")
    trap_index = args.trap_index or os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*")
    event_index = args.event_index or os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*")

    latest_syslog = max_timestamp(es_url, syslog_index, "@timestamp")
    latest_alarm = max_timestamp(es_url, event_index, "last_seen")
    lag_minutes = None
    if latest_syslog and latest_alarm:
        lag_minutes = round((latest_syslog - latest_alarm).total_seconds() / 60.0, 2)

    counts = {}
    for hours in (1, 3, 24):
        counts[f"{hours}h"] = {
            "syslog": count_since(es_url, syslog_index, "@timestamp", hours),
            "trap": count_since(es_url, trap_index, "@timestamp", hours),
            "alarm_events": count_since(es_url, event_index, "last_seen", hours),
        }

    warning = bool(lag_minutes is None or lag_minutes > args.max_lag_minutes)
    result = {
        "es_url": es_url,
        "latest_syslog": iso_z(latest_syslog),
        "latest_alarm_event": iso_z(latest_alarm),
        "lag_minutes": lag_minutes,
        "max_lag_minutes": args.max_lag_minutes,
        "counts": counts,
        "warning": warning,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"latest syslog: {result['latest_syslog']}")
        print(f"latest alarm_event: {result['latest_alarm_event']}")
        print(f"lag minutes: {result['lag_minutes']}")
        for window, item in counts.items():
            print(f"{window}: syslog={item['syslog']} trap={item['trap']} alarm_events={item['alarm_events']}")
        if warning:
            print(f"WARNING: alarm_events lag exceeds {args.max_lag_minutes} minutes or cannot be calculated")
    return 1 if warning else 0


if __name__ == "__main__":
    raise SystemExit(main())
