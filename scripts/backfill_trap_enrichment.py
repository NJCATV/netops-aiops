#!/usr/bin/env python3
"""Backfill compact Trap enrichment fields into historical ES Trap documents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.context.current_window_summary import iso_z, utc_now  # noqa: E402
from aiops.mib.trap_enrichment import enrich_traps  # noqa: E402


BACKFILL_FIELDS = [
    "alarm_name",
    "alarm_severity",
    "alarm_lifecycle_status",
    "alarm_vendor",
    "alarm_enterprise_id",
    "alarm_enterprise_name",
    "alarm_fault_reason",
    "alarm_suggestion",
    "alarm_definition_matched",
    "alarm_lookup_source",
    "trap_oid_name",
    "trap_oid_module",
    "trap_oid_type",
    "trap_oid_description",
    "mib_translated",
    "mib_lookup_source",
    "trap_sender_ip",
    "collector_source_ip",
    "snmp_agent_addr",
    "managed_device_name",
    "managed_device_ip",
    "managed_object_name",
    "managed_object_address",
    "endpoint_device_names",
    "endpoint_interfaces",
    "topology_object_key",
    "object_identity_source",
    "object_identity_confidence",
    "topology_match",
    "matched_link",
    "related_device_roles",
    "topology_correlation_status",
    "device_identity_source",
    "device_identity_confidence",
    "device_name",
    "device_ip",
]


def load_env(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def es_request(es_url: str, method: str, path: str, body: Any = None, content_type: str = "application/json") -> dict:
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(es_url.rstrip("/") + path, data=data, headers={"Content-Type": content_type}, method=method)
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else {}


def build_query(args: argparse.Namespace) -> dict:
    filters = []
    if not args.all:
        end = utc_now()
        start = end - dt.timedelta(days=args.days)
        filters.append({"range": {"@timestamp": {"gte": iso_z(start), "lt": iso_z(end)}}})
    return {"bool": {"filter": filters}} if filters else {"match_all": {}}


def search_first_batch(es_url: str, index: str, query: dict, size: int) -> Tuple[Optional[str], List[dict]]:
    body: Dict[str, Any] = {
        "size": size,
        "track_total_hits": True,
        "query": query,
        "sort": [{"@timestamp": {"order": "asc", "unmapped_type": "date"}}],
    }
    response = es_request(es_url, "POST", "/%s/_search?scroll=2m" % index, body)
    return response.get("_scroll_id"), response.get("hits", {}).get("hits", [])


def search_next_batch(es_url: str, scroll_id: str) -> Tuple[Optional[str], List[dict]]:
    response = es_request(es_url, "POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
    return response.get("_scroll_id"), response.get("hits", {}).get("hits", [])


def pick_update_fields(row: dict) -> dict:
    update = {}
    for field in BACKFILL_FIELDS:
        if field in row:
            value = row.get(field)
            if value is not None or field in {"device_ip", "device_name", "snmp_agent_addr", "managed_device_ip", "managed_device_name"}:
                update[field] = value
    if not update.get("managed_device_ip"):
        update["device_ip"] = None
    if not update.get("managed_device_name"):
        update["device_name"] = None
    return update


def bulk_update(es_url: str, rows: Iterable[Tuple[str, str, dict]]) -> dict:
    lines = []
    for index, doc_id, doc in rows:
        lines.append(json.dumps({"update": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps({"doc": doc, "doc_as_upsert": False}, ensure_ascii=False))
    if not lines:
        return {"errors": False, "items": []}
    data = ("\n".join(lines) + "\n").encode("utf-8")
    return es_request(es_url, "POST", "/_bulk", data, "application/x-ndjson")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--index", default=os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"))
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE"))
    args = parser.parse_args()

    load_env(args.env_file)
    query = build_query(args)
    scroll_id = None
    scanned = 0
    prepared = 0
    updated = 0
    error_items = 0
    error_samples: List[dict] = []
    counters: Counter = Counter()
    first = True
    while True:
        if first:
            scroll_id, hits = search_first_batch(args.es_url, args.index, query, args.batch_size)
            first = False
        elif scroll_id:
            scroll_id, hits = search_next_batch(args.es_url, scroll_id)
        else:
            hits = []
        if not hits:
            break
        docs = [hit.get("_source", {}) for hit in hits]
        enriched, _stats = enrich_traps(docs)
        updates = []
        for hit, row in zip(hits, enriched):
            scanned += 1
            update = pick_update_fields(row)
            prepared += 1 if update else 0
            counters["alarm_definition_matched" if row.get("alarm_definition_matched") else "alarm_definition_unmatched"] += 1
            counters["mib_translated" if row.get("mib_translated") else "mib_untranslated"] += 1
            counters["object_extracted" if row.get("managed_object_name") else "object_unresolved"] += 1
            counters["topology_link_matched" if row.get("topology_match") else "topology_link_unmatched"] += 1
            if update:
                updates.append((hit.get("_index"), hit.get("_id"), update))
        if not args.dry_run and updates:
            response = bulk_update(args.es_url, updates)
            if response.get("errors"):
                for item in response.get("items", []):
                    update_result = item.get("update", {})
                    if update_result.get("error"):
                        error_items += 1
                        if len(error_samples) < 5:
                            error_samples.append(
                                {
                                    "index": update_result.get("_index"),
                                    "id": update_result.get("_id"),
                                    "status": update_result.get("status"),
                                    "error": update_result.get("error"),
                                }
                            )
            updated += len(updates)

    print(
        json.dumps(
            {
                "index": args.index,
                "days": args.days,
                "all": args.all,
                "dry_run": args.dry_run,
                "scanned": scanned,
                "prepared_updates": prepared,
                "updated": updated,
                "bulk_error_items": error_items,
                "bulk_error_samples": error_samples,
                "counters": dict(counters),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if error_items else 0


if __name__ == "__main__":
    raise SystemExit(main())
