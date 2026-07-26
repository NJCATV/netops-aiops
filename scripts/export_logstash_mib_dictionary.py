#!/usr/bin/env python3
"""Export MIB OID mappings from MySQL into Logstash translate dictionaries."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import select

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import create_db_engine  # noqa: E402
from app.models import MibOidMapping  # noqa: E402


def load_env(path: Optional[str]) -> None:
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
    parser.add_argument("--output-dir", default=os.getenv("LOGSTASH_MIB_DICTIONARY_DIR", "/data/jscn-aiops/logstash/mib"))
    parser.add_argument("--notifications-only", action="store_true", help="Export only NOTIFICATION-TYPE rows")
    args = parser.parse_args()

    load_env(args.env_file)
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = create_db_engine()
    stmt = select(
        MibOidMapping.oid,
        MibOidMapping.name,
        MibOidMapping.module,
        MibOidMapping.object_type,
    ).order_by(MibOidMapping.oid)
    if args.notifications_only:
        stmt = stmt.where(MibOidMapping.is_notification.is_(True))

    names = {}
    modules = {}
    object_types = {}
    with engine.connect() as conn:
        for row in conn.execute(stmt):
            oid = row.oid
            names[oid] = row.name or ""
            modules[oid] = row.module or ""
            object_types[oid] = row.object_type or ""

    write_dictionary(output_dir / "h3c_oid_name.json", names)
    write_dictionary(output_dir / "h3c_oid_module.json", modules)
    write_dictionary(output_dir / "h3c_oid_type.json", object_types)

    result = {
        "output_dir": str(output_dir),
        "entries": len(names),
        "files": [
            str(output_dir / "h3c_oid_name.json"),
            str(output_dir / "h3c_oid_module.json"),
            str(output_dir / "h3c_oid_type.json"),
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
