#!/usr/bin/env python3
"""Import formal fault ledgers and investigation reports into Elasticsearch."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from aiops.kb.formal_fault_records import index_date, iter_formal_fault_records, summarize_records


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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


def install_template(es_url: str, template_path: pathlib.Path, template_name: str) -> dict:
    body = json.loads(template_path.read_text(encoding="utf-8"))
    return es_request(es_url, "PUT", f"/_index_template/{template_name}", body)


def bulk_upsert(es_url: str, records: list[dict[str, Any]], index_prefix: str, batch_size: int) -> dict:
    now = iso_z(utc_now())
    upserted = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    def flush(items: list[dict[str, Any]]) -> None:
        nonlocal upserted, failed
        lines: list[str] = []
        for record in items:
            doc = dict(record)
            doc["created_at"] = doc.get("created_at") or now
            doc["updated_at"] = now
            record_id = doc.get("record_id")
            if not record_id:
                failed += 1
                errors.append({"error": "missing record_id", "record": record})
                continue
            lines.append(json.dumps({"update": {"_index": f"{index_prefix}-{index_date(doc)}", "_id": record_id}}, ensure_ascii=False))
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
                upserted += 1

    batch: list[dict[str, Any]] = []
    for record in records:
        batch.append(record)
        if len(batch) >= batch_size:
            flush(batch)
            batch = []
    flush(batch)
    return {"upserted": upserted, "failed": failed, "errors": errors[:20]}


def count_docs(es_url: str, index_pattern: str) -> int:
    result = es_request(es_url, "GET", f"/{index_pattern}/_count")
    return int(result.get("count", 0))


def table(rows: list[dict[str, Any]], key_header: str) -> str:
    if not rows:
        return f"| {key_header} | Count |\n| --- | ---: |\n| (none) | 0 |"
    lines = [f"| {key_header} | Count |", "| --- | ---: |"]
    for row in rows:
        lines.append(f"| `{row['key']}` | {row['count']} |")
    return "\n".join(lines)


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_report(path: pathlib.Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    sample_lines = [
        "- `%s` `%s` `%s`: %s"
        % (item.get("occurred_date"), item.get("service"), item.get("canonical_symptom"), (item.get("title") or item.get("fault_content") or "")[:90])
        for item in summary.get("samples", [])
    ]
    lines = [
        "# Formal Fault KB Import Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Source root: `{report['source_root']}`",
        f"- Elasticsearch: `{report['elasticsearch_url']}`",
        f"- Index prefix: `{report['index_prefix']}`",
        f"- Dry run: `{report['dry_run']}`",
        f"- Parsed records: `{report['parsed_records']}`",
        f"- Embedding candidates: `{summary['embedding_candidates']}`",
        f"- Upserted records: `{report['upserted']}`",
        f"- Failed records: `{report['failed']}`",
        f"- Indexed document count: `{report['indexed_doc_count']}`",
        "",
        "## Canonical Symptom",
        "",
        table(summary["top_canonical_symptom"], "canonical_symptom"),
        "",
        "## Aggregation Key",
        "",
        table(summary["top_aggregation_key"], "aggregation_key"),
        "",
        "## Samples",
        "",
        *(sample_lines or ["- (none)"]),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def import_formal_fault_kb(
    es_url: str,
    source_root: pathlib.Path,
    index_prefix: str,
    template_path: pathlib.Path,
    report_path: pathlib.Path,
    output_json: Optional[pathlib.Path],
    batch_size: int,
    dry_run: bool,
    install_index_template: bool,
) -> dict[str, Any]:
    records = list(iter_formal_fault_records(source_root))
    summary = summarize_records(records)
    if output_json:
        write_json(output_json, {"records": records, "summary": summary})
    result = {"upserted": 0, "failed": 0, "errors": []}
    if install_index_template and not dry_run:
        install_template(es_url, template_path, "jscn-aiops-fault-kb")
    if not dry_run:
        result = bulk_upsert(es_url, records, index_prefix, batch_size)
        es_request(es_url, "POST", f"/{index_prefix}-*/_refresh")
    report = {
        "generated_at": iso_z(utc_now()),
        "source_root": str(source_root),
        "elasticsearch_url": es_url,
        "index_prefix": index_prefix,
        "dry_run": dry_run,
        "parsed_records": len(records),
        "summary": summary,
        "upserted": result["upserted"],
        "failed": result["failed"],
        "errors": result["errors"],
        "indexed_doc_count": 0 if dry_run else count_docs(es_url, f"{index_prefix}-*"),
    }
    write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--index-prefix", default=os.getenv("FAULT_KB_INDEX_PREFIX", "jscn-aiops-fault-kb"))
    parser.add_argument("--template", default=os.getenv("FAULT_KB_TEMPLATE", "deploy/elasticsearch/templates/fault_kb_template.json"))
    parser.add_argument("--report", default=os.getenv("FAULT_KB_IMPORT_REPORT", "reports/fault_kb/formal_fault_import_report.md"))
    parser.add_argument("--output-json", default=os.getenv("FAULT_KB_OUTPUT_JSON", "reports/fault_kb/formal_fault_records.json"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("FAULT_KB_BATCH_SIZE", "200")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-template", action="store_true")
    args = parser.parse_args()
    report = import_formal_fault_kb(
        args.es_url,
        pathlib.Path(args.source_root),
        args.index_prefix,
        pathlib.Path(args.template),
        pathlib.Path(args.report),
        pathlib.Path(args.output_json) if args.output_json else None,
        args.batch_size,
        args.dry_run,
        not args.skip_template,
    )
    print(
        json.dumps(
            {
                "source_root": report["source_root"],
                "dry_run": report["dry_run"],
                "parsed_records": report["parsed_records"],
                "embedding_candidates": report["summary"]["embedding_candidates"],
                "upserted": report["upserted"],
                "failed": report["failed"],
                "report": args.report,
                "output_json": args.output_json,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
