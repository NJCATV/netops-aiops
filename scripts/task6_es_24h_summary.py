#!/usr/bin/env python3
"""Generate Task 6 Elasticsearch query validation summaries.

This script is intentionally read-only. It queries the last 24 hours of
Syslog and Trap data from Elasticsearch and writes JSON plus Markdown
summary files for Task 6 validation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def es_request(es_url: str, method: str, path: str, body: dict | None = None) -> dict:
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
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    return json.loads(payload)


def terms_agg(field: str, size: int) -> dict:
    return {
        "terms": {
            "field": field,
            "size": size,
            "missing": "__missing__",
        }
    }


def bucket_list(response: dict, name: str) -> list[dict]:
    return [
        {"key": bucket["key"], "count": bucket["doc_count"]}
        for bucket in response.get("aggregations", {}).get(name, {}).get("buckets", [])
    ]


def search_aggs(es_url: str, index: str, start: str, aggs: dict) -> dict:
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "range": {
                "@timestamp": {
                    "gte": start,
                    "lte": "now",
                }
            }
        },
        "aggs": aggs,
    }
    return es_request(es_url, "POST", f"/{index}/_search", body)


def total_hits(response: dict) -> int:
    total = response.get("hits", {}).get("total", {})
    if isinstance(total, dict):
        return int(total.get("value", 0))
    return int(total or 0)


def markdown_table(rows: list[dict], key_header: str) -> str:
    if not rows:
        return "| " + key_header + " | Count |\n| --- | ---: |\n| (none) | 0 |"
    lines = ["| " + key_header + " | Count |", "| --- | ---: |"]
    for row in rows:
        lines.append(f"| `{row['key']}` | {row['count']} |")
    return "\n".join(lines)


def write_markdown(summary: dict) -> str:
    syslog = summary["syslog"]
    trap = summary["trap"]
    lines = [
        "# Task 6 Elasticsearch 24h Summary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Window start: `{summary['window_start']}`",
        f"- Window end: `{summary['window_end']}`",
        f"- Elasticsearch: `{summary['elasticsearch_url']}`",
        "",
        "## Syslog",
        "",
        f"- Index pattern: `{syslog['index']}`",
        f"- Total documents: `{syslog['total']}`",
        "",
        "### Top device_ip",
        "",
        markdown_table(syslog["top_device_ip"], "device_ip"),
        "",
        "### Top device_name",
        "",
        markdown_table(syslog["top_device_name"], "device_name"),
        "",
        "### Top event_code",
        "",
        markdown_table(syslog["top_event_code"], "event_code"),
        "",
        "### Top event_family",
        "",
        markdown_table(syslog["top_event_family"], "event_family"),
        "",
        "### Top severity",
        "",
        markdown_table(syslog["top_severity"], "severity"),
        "",
        "## Trap",
        "",
        f"- Index pattern: `{trap['index']}`",
        f"- Total documents: `{trap['total']}`",
        "",
        "### Top trap_oid",
        "",
        markdown_table(trap["top_trap_oid"], "trap_oid"),
        "",
        "### Top source_ip",
        "",
        markdown_table(trap["top_source_ip"], "source_ip"),
        "",
        "### Top enterprise_oid",
        "",
        markdown_table(trap["top_enterprise_oid"], "enterprise_oid"),
        "",
        "## Notes",
        "",
        "- Trap statistics intentionally do not perform MIB translation.",
        "- `__missing__` means the field was absent in matching documents.",
        "- Single-node Elasticsearch indices may show yellow due to unassigned replicas.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--out-dir", default=os.getenv("TASK6_OUT_DIR", "/data/jscn-aiops/reports/task6"))
    parser.add_argument("--top-n", type=int, default=int(os.getenv("TASK6_TOP_N", "10")))
    args = parser.parse_args()

    now = utc_now()
    start = now - dt.timedelta(hours=24)
    generated_at = iso_z(now)
    window_start = iso_z(start)
    window_end = iso_z(now)

    syslog_index = "jscn-aiops-syslog-parsed-*"
    trap_index = "jscn-aiops-trap-raw-*"

    syslog_response = search_aggs(
        args.es_url,
        syslog_index,
        window_start,
        {
            "top_device_ip": terms_agg("device_ip.keyword", args.top_n),
            "top_device_name": terms_agg("device_name.keyword", args.top_n),
            "top_event_code": terms_agg("event_code.keyword", args.top_n),
            "top_event_family": terms_agg("event_family.keyword", args.top_n),
            "top_severity": terms_agg("severity.keyword", args.top_n),
        },
    )
    trap_response = search_aggs(
        args.es_url,
        trap_index,
        window_start,
        {
            "top_trap_oid": terms_agg("trap_oid.keyword", args.top_n),
            "top_source_ip": terms_agg("source_ip.keyword", args.top_n),
            "top_enterprise_oid": terms_agg("enterprise_oid.keyword", args.top_n),
        },
    )

    summary = {
        "generated_at": generated_at,
        "window_start": window_start,
        "window_end": window_end,
        "lookback_hours": 24,
        "elasticsearch_url": args.es_url,
        "syslog": {
            "index": syslog_index,
            "total": total_hits(syslog_response),
            "top_device_ip": bucket_list(syslog_response, "top_device_ip"),
            "top_device_name": bucket_list(syslog_response, "top_device_name"),
            "top_event_code": bucket_list(syslog_response, "top_event_code"),
            "top_event_family": bucket_list(syslog_response, "top_event_family"),
            "top_severity": bucket_list(syslog_response, "top_severity"),
        },
        "trap": {
            "index": trap_index,
            "total": total_hits(trap_response),
            "top_trap_oid": bucket_list(trap_response, "top_trap_oid"),
            "top_source_ip": bucket_list(trap_response, "top_source_ip"),
            "top_enterprise_oid": bucket_list(trap_response, "top_enterprise_oid"),
        },
    }

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "task6-24h-summary.json"
    md_path = out_dir / "task6-24h-summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(write_markdown(summary), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
