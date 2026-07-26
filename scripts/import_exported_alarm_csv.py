#!/usr/bin/env python3
"""Import exported Syslog and Trap CSV files into Elasticsearch.

This is a Task 7 data preparation helper for historical exports. It is
idempotent: document IDs are derived from stable CSV fields, so re-running the
same import updates the same documents instead of creating duplicates.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple


CHINA_TZ = dt.timezone(dt.timedelta(hours=8))


def parse_local_time(value: str) -> Optional[dt.datetime]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=CHINA_TZ)
        except ValueError:
            continue
    return None


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def clean_text(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value.strip()


def index_date(value: dt.datetime) -> str:
    return value.astimezone(CHINA_TZ).strftime("%Y.%m.%d")


def stable_id(parts: Iterable[Any]) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def es_request(es_url: str, method: str, path: str, data: Optional[bytes] = None) -> dict:
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(es_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    if not payload:
        return {}
    return json.loads(payload)


def bulk_import(es_url: str, actions: List[Tuple[str, str, dict]]) -> Tuple[int, int]:
    if not actions:
        return 0, 0
    lines: List[str] = []
    for index, doc_id, doc in actions:
        lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps(doc, ensure_ascii=False))
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    result = es_request(es_url, "POST", "/_bulk", payload)
    items = result.get("items", [])
    failed = sum(1 for item in items if item.get("index", {}).get("error"))
    return len(items) - failed, failed


def read_csv(path: pathlib.Path, required_field: str) -> Iterable[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        header: Optional[List[str]] = None
        for raw_row in rows:
            if required_field in raw_row:
                header = raw_row
                break
        if header is None:
            return
        for raw_row in rows:
            if len(raw_row) < len(header):
                continue
            yield {field: raw_row[idx] for idx, field in enumerate(header)}


def parse_varbind_count(value: str) -> int:
    value = value or ""
    if not value.strip():
        return 0
    return len([item for item in value.split(";") if item.strip()])


def enterprise_oid(trap_oid: str) -> str:
    match = re.match(r"^((?:\d+\.){6}\d+)", trap_oid or "")
    return match.group(1) if match else ""


def syslog_actions(path: pathlib.Path, prefix: str) -> Iterable[Tuple[str, str, dict]]:
    for row in read_csv(path, "摘要"):
        event_code = clean_text(row.get("摘要", ""))
        receive_time = parse_local_time(row.get("接收时间", ""))
        if not event_code or receive_time is None:
            continue
        device_ip = clean_text(row.get("资源IP", ""))
        raw_message = clean_text(row.get("描述", ""))
        doc = {
            "@timestamp": iso_z(receive_time),
            "log_time": iso_z(receive_time),
            "ingest_time": iso_z(dt.datetime.now(dt.timezone.utc)),
            "source_ip": device_ip,
            "device_name": clean_text(row.get("系统名称", "")),
            "device_ip": device_ip,
            "module": clean_text(row.get("模块名称", "")),
            "severity": clean_text(row.get("级别", "")),
            "event_code": event_code,
            "event_family": "unknown",
            "raw_message": raw_message,
            "parse_status": "imported",
            "receiver": "task7_csv_import",
            "import_source": path.name,
        }
        doc_id = stable_id(["syslog", doc["log_time"], doc["device_ip"], doc["device_name"], event_code, raw_message])
        yield f"{prefix}-{index_date(receive_time)}", doc_id, doc


def trap_actions(path: pathlib.Path, prefix: str) -> Iterable[Tuple[str, str, dict]]:
    for row in read_csv(path, "Fault OID"):
        trap_oid = clean_text(row.get("Fault OID", ""))
        receive_time = parse_local_time(row.get("Trap接收时间", ""))
        if not trap_oid or receive_time is None:
            continue
        varbinds = clean_text(row.get("Trap参数", ""))
        source_ip = clean_text(row.get("IP地址", ""))
        raw_message = clean_text(row.get("详细信息", ""))
        doc = {
            "@timestamp": iso_z(receive_time),
            "ingest_time": iso_z(dt.datetime.now(dt.timezone.utc)),
            "source_ip": source_ip,
            "device_ip": source_ip,
            "device_name": clean_text(row.get("资源名称", "")),
            "trap_oid": trap_oid,
            "enterprise_oid": enterprise_oid(trap_oid),
            "varbind_count": parse_varbind_count(varbinds),
            "varbinds": varbinds,
            "raw_message": raw_message,
            "parse_status": "raw_only",
            "receiver": "task7_csv_import",
            "import_source": path.name,
        }
        doc_id = stable_id(["trap", doc["@timestamp"], source_ip, trap_oid, raw_message, varbinds])
        yield f"{prefix}-{index_date(receive_time)}", doc_id, doc


def import_actions(es_url: str, actions: Iterable[Tuple[str, str, dict]], batch_size: int) -> Tuple[int, int]:
    imported = 0
    failed = 0
    batch: List[Tuple[str, str, dict]] = []
    for action in actions:
        batch.append(action)
        if len(batch) >= batch_size:
            ok, bad = bulk_import(es_url, batch)
            imported += ok
            failed += bad
            batch = []
    if batch:
        ok, bad = bulk_import(es_url, batch)
        imported += ok
        failed += bad
    return imported, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--syslog-csv", required=True)
    parser.add_argument("--trap-csv", required=True)
    parser.add_argument("--syslog-index-prefix", default=os.getenv("ELASTICSEARCH_SYSLOG_PARSED_INDEX_PREFIX", "jscn-aiops-syslog-parsed"))
    parser.add_argument("--trap-index-prefix", default=os.getenv("ELASTICSEARCH_TRAP_RAW_INDEX_PREFIX", "jscn-aiops-trap-raw"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("TASK7_IMPORT_BATCH_SIZE", "500")))
    args = parser.parse_args()

    syslog_csv = pathlib.Path(args.syslog_csv)
    trap_csv = pathlib.Path(args.trap_csv)
    syslog_imported, syslog_failed = import_actions(
        args.es_url,
        syslog_actions(syslog_csv, args.syslog_index_prefix),
        args.batch_size,
    )
    trap_imported, trap_failed = import_actions(
        args.es_url,
        trap_actions(trap_csv, args.trap_index_prefix),
        args.batch_size,
    )
    print(
        json.dumps(
            {
                "syslog": {"imported_or_updated": syslog_imported, "failed": syslog_failed},
                "trap": {"imported_or_updated": trap_imported, "failed": trap_failed},
                "syslog_index_prefix": args.syslog_index_prefix,
                "trap_index_prefix": args.trap_index_prefix,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if syslog_failed or trap_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
