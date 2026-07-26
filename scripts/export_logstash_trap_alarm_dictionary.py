#!/usr/bin/env python3
"""Export Trap alarm definitions into Logstash translate dictionaries."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Optional

from sqlalchemy import select

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import create_db_engine  # noqa: E402
from app.models import TrapAlarmDefinition, TrapAlarmOidAlias  # noqa: E402
from aiops.trap.alarm_definition_lookup import truncate_text  # noqa: E402


def load_env(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def write_dictionary(path: pathlib.Path, mapping: dict) -> None:
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--output-dir", default=os.getenv("LOGSTASH_TRAP_ALARM_DICTIONARY_DIR", os.getenv("AIOPS_LOGSTASH_MIB_DIR", "/data/jscn-aiops/logstash/mib")))
    parser.add_argument("--suggestion-limit", type=int, default=160)
    args = parser.parse_args()

    load_env(args.env_file)
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine()
    stmt = (
        select(
            TrapAlarmOidAlias.oid,
            TrapAlarmDefinition.fault_name,
            TrapAlarmDefinition.severity,
            TrapAlarmDefinition.custom_severity,
            TrapAlarmDefinition.lifecycle_status,
            TrapAlarmDefinition.vendor,
            TrapAlarmDefinition.enterprise_name,
            TrapAlarmDefinition.suggestion,
        )
        .join(TrapAlarmDefinition, TrapAlarmDefinition.id == TrapAlarmOidAlias.definition_id)
        .order_by(TrapAlarmOidAlias.oid)
    )
    names = {}
    severities = {}
    lifecycles = {}
    vendors = {}
    enterprise_names = {}
    suggestions = {}
    with engine.connect() as conn:
        for row in conn.execute(stmt):
            oid = row.oid
            names[oid] = row.fault_name or ""
            severities[oid] = row.custom_severity or row.severity or ""
            lifecycles[oid] = row.lifecycle_status or "unknown"
            vendors[oid] = row.vendor or "unknown"
            enterprise_names[oid] = row.enterprise_name or ""
            suggestion = truncate_text(row.suggestion, args.suggestion_limit)
            if suggestion:
                suggestions[oid] = suggestion

    files = {
        "trap_alarm_name.json": names,
        "trap_alarm_severity.json": severities,
        "trap_alarm_lifecycle.json": lifecycles,
        "trap_alarm_vendor.json": vendors,
        "trap_alarm_enterprise_name.json": enterprise_names,
        "trap_alarm_suggestion.json": suggestions,
    }
    for name, mapping in files.items():
        write_dictionary(output_dir / name, mapping)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "entries": len(names),
                "files": [str(output_dir / name) for name in files],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
