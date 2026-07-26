#!/usr/bin/env python3
"""Import private NMS Trap alarm definitions into MySQL."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base, create_db_engine  # noqa: E402
from app.models import TrapAlarmDefinition, TrapAlarmOidAlias  # noqa: E402
from aiops.mib.lookup import normalize_oid  # noqa: E402
from aiops.trap.alarm_definition_lookup import infer_lifecycle_status, truncate_text  # noqa: E402


HUAWEI_PREFIX = "1.3.6.1.4.1.2011"
H3C_PREFIX = "1.3.6.1.4.1.25506"


def load_env(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\t", " ").split())


def parse_json_payload(text: str) -> dict:
    stripped = text.strip().lstrip("\ufeff")
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("source does not contain a JSON object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    return payload


def detect_vendor(enterprise_id: Any, requested: str) -> str:
    if requested and requested != "auto":
        return requested
    enterprise = normalize_oid(enterprise_id)
    if enterprise.startswith(HUAWEI_PREFIX):
        return "huawei"
    if enterprise.startswith(H3C_PREFIX):
        return "h3c"
    return "unknown"


def scalar(value: Any) -> Optional[str]:
    text = clean_text(value)
    return text or None


def iter_recover_oids(value: Any) -> Iterable[str]:
    if not value:
        return []
    rows: List[str] = []
    if isinstance(value, str):
        rows.extend(re.findall(r"(?:\d+\.)+\d+", value))
    elif isinstance(value, dict):
        for key in ("faultOid", "faultOidV1", "faultOidV2", "recoverOid", "oid"):
            oid = normalize_oid(value.get(key))
            if oid:
                rows.append(oid)
        for item in value.values():
            rows.extend(iter_recover_oids(item))
    elif isinstance(value, list):
        for item in value:
            rows.extend(iter_recover_oids(item))
    return rows


def normalize_definition(row: dict, source_file: str, vendor_arg: str) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    enterprise = row.get("trapEnterprise") or {}
    enterprise_id = scalar(row.get("enterpriseId") or enterprise.get("enterpriseId"))
    vendor = detect_vendor(enterprise_id, vendor_arg)
    fault_oid = normalize_oid(row.get("faultOid")) or None
    fault_oid_v1 = normalize_oid(row.get("faultOidV1")) or None
    fault_oid_v2 = normalize_oid(row.get("faultOidV2")) or None
    fault_name = scalar(row.get("faultName"))
    fault_type = scalar(row.get("faultType"))
    lifecycle = infer_lifecycle_status(fault_type, fault_name)
    definition = {
        "vendor": vendor,
        "enterprise_id": enterprise_id,
        "enterprise_name": scalar(enterprise.get("enterpriseName")),
        "fault_oid": fault_oid,
        "fault_oid_v1": fault_oid_v1,
        "fault_oid_v2": fault_oid_v2,
        "fault_name": fault_name,
        "severity": scalar(row.get("severity")),
        "custom_severity": scalar(row.get("customSeverity")),
        "fault_type": fault_type,
        "lifecycle_status": lifecycle,
        "recover_flag": scalar(row.get("recoverFlag")),
        "desc_info": truncate_text(row.get("descInfo"), 2000),
        "fault_reason": truncate_text(row.get("faultReason"), 2000),
        "suggestion": truncate_text(row.get("suggestion"), 2000),
        "category_main_id": scalar(row.get("categoryMainId")),
        "category_base_id": scalar(row.get("categoryBaseId")),
        "category_sub_id": scalar(row.get("categorySubId")),
        "source_file": source_file,
    }
    aliases: List[Tuple[str, str]] = []
    for oid_type, oid in (("faultOid", fault_oid), ("faultOidV1", fault_oid_v1), ("faultOidV2", fault_oid_v2)):
        if oid:
            aliases.append((oid, oid_type))
    for oid in iter_recover_oids(row.get("recoverTraps")):
        if oid:
            aliases.append((normalize_oid(oid), "recoverOid"))
    deduped = []
    seen = set()
    for oid, oid_type in aliases:
        if oid and oid not in seen:
            seen.add(oid)
            deduped.append((oid, oid_type))
    return definition, deduped


def upsert_definitions(engine, definitions: List[Dict[str, Any]], dry_run: bool) -> None:
    if dry_run or not definitions:
        return
    now = dt.datetime.now(dt.timezone.utc)
    payload = []
    for item in definitions:
        row = dict(item)
        row["created_at"] = now
        row["updated_at"] = now
        row["imported_at"] = now
        payload.append(row)
    stmt = mysql_insert(TrapAlarmDefinition.__table__).values(payload)
    update_columns = {
        "vendor": stmt.inserted.vendor,
        "enterprise_id": stmt.inserted.enterprise_id,
        "enterprise_name": stmt.inserted.enterprise_name,
        "fault_oid_v1": stmt.inserted.fault_oid_v1,
        "fault_oid_v2": stmt.inserted.fault_oid_v2,
        "fault_name": stmt.inserted.fault_name,
        "severity": stmt.inserted.severity,
        "custom_severity": stmt.inserted.custom_severity,
        "fault_type": stmt.inserted.fault_type,
        "lifecycle_status": stmt.inserted.lifecycle_status,
        "recover_flag": stmt.inserted.recover_flag,
        "desc_info": stmt.inserted.desc_info,
        "fault_reason": stmt.inserted.fault_reason,
        "suggestion": stmt.inserted.suggestion,
        "category_main_id": stmt.inserted.category_main_id,
        "category_base_id": stmt.inserted.category_base_id,
        "category_sub_id": stmt.inserted.category_sub_id,
        "imported_at": stmt.inserted.imported_at,
        "updated_at": now,
    }
    with engine.begin() as conn:
        conn.execute(stmt.on_duplicate_key_update(**update_columns))


def fetch_definition_ids(engine, source_file: str) -> Dict[Tuple[str, str], int]:
    stmt = select(TrapAlarmDefinition.id, TrapAlarmDefinition.source_file, TrapAlarmDefinition.fault_oid).where(TrapAlarmDefinition.source_file == source_file)
    result = {}
    with engine.connect() as conn:
        for row in conn.execute(stmt):
            result[(row.source_file, row.fault_oid)] = row.id
    return result


def upsert_aliases(engine, aliases: List[Dict[str, Any]], dry_run: bool) -> None:
    if dry_run or not aliases:
        return
    now = dt.datetime.now(dt.timezone.utc)
    payload = []
    for item in aliases:
        row = dict(item)
        row["created_at"] = now
        row["updated_at"] = now
        payload.append(row)
    stmt = mysql_insert(TrapAlarmOidAlias.__table__).values(payload)
    with engine.begin() as conn:
        conn.execute(
            stmt.on_duplicate_key_update(
                definition_id=stmt.inserted.definition_id,
                oid_type=stmt.inserted.oid_type,
                vendor=stmt.inserted.vendor,
                enterprise_id=stmt.inserted.enterprise_id,
                updated_at=now,
            )
        )


def replace_source(engine, source_file: str, dry_run: bool) -> int:
    stmt = select(TrapAlarmDefinition.id).where(TrapAlarmDefinition.source_file == source_file)
    with engine.connect() as conn:
        ids = [row.id for row in conn.execute(stmt)]
    if not ids or dry_run:
        return len(ids)
    with engine.begin() as conn:
        conn.execute(delete(TrapAlarmOidAlias).where(TrapAlarmOidAlias.definition_id.in_(ids)))
        conn.execute(delete(TrapAlarmDefinition).where(TrapAlarmDefinition.id.in_(ids)))
    return len(ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="JSON export file or text containing JSON")
    parser.add_argument("--vendor", default="auto", help="auto, huawei, h3c, or a vendor label")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--replace", action="store_true", help="Delete definitions from the same source_file before importing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    load_env(args.env_file)
    source = pathlib.Path(args.source)
    payload = parse_json_payload(source.read_text(encoding="utf-8", errors="replace"))
    records = payload.get("data")
    if not isinstance(records, list):
        raise ValueError("top-level JSON must contain data: [...]")

    source_file = source.name
    definitions: List[Dict[str, Any]] = []
    alias_pairs: List[Tuple[Dict[str, Any], List[Tuple[str, str]]]] = []
    vendor_counts: Counter = Counter()
    lifecycle_counts: Counter = Counter()
    for item in records:
        if not isinstance(item, dict):
            continue
        definition, aliases = normalize_definition(item, source_file, args.vendor)
        definitions.append(definition)
        alias_pairs.append((definition, aliases))
        vendor_counts[definition["vendor"]] += 1
        lifecycle_counts[definition["lifecycle_status"]] += 1

    engine = create_db_engine()
    Base.metadata.create_all(engine)
    replaced = 0
    if args.replace:
        replaced = replace_source(engine, source_file, args.dry_run)
    for index in range(0, len(definitions), args.batch_size):
        upsert_definitions(engine, definitions[index : index + args.batch_size], args.dry_run)

    definition_ids = {} if args.dry_run else fetch_definition_ids(engine, source_file)
    aliases_payload: List[Dict[str, Any]] = []
    for definition, aliases in alias_pairs:
        definition_id = definition_ids.get((source_file, definition["fault_oid"]))
        for oid, oid_type in aliases:
            aliases_payload.append(
                {
                    "definition_id": definition_id or 0,
                    "oid": oid,
                    "oid_type": oid_type,
                    "vendor": definition["vendor"],
                    "enterprise_id": definition["enterprise_id"],
                }
            )
    if not args.dry_run:
        aliases_payload = [item for item in aliases_payload if item["definition_id"]]
    for index in range(0, len(aliases_payload), args.batch_size):
        upsert_aliases(engine, aliases_payload[index : index + args.batch_size], args.dry_run)

    print(
        json.dumps(
            {
                "source": str(source),
                "source_total": payload.get("total"),
                "definitions_seen": len(definitions),
                "aliases_seen": len(aliases_payload),
                "vendor_counts": dict(vendor_counts),
                "lifecycle_counts": dict(lifecycle_counts),
                "replace_matched_existing_definitions": replaced,
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
