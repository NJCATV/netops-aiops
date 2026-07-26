"""Synchronize OLT/CMTS device region scope from the collector inventory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text

from app.db import create_db_engine, make_session_factory, session_scope
from app.models import PlatformDeviceScope


INVENTORY_QUERIES = {
    "olt": """
        SELECT CAST(olt_device_id AS CHAR) AS source_device_id, name AS device_name,
               primary_ip AS ip_address, region AS region_code, is_active
        FROM olt_devices
        WHERE COALESCE(primary_ip, '') <> '' AND COALESCE(region, '') <> ''
    """,
    "cmts": """
        SELECT CAST(cmts_device_id AS CHAR) AS source_device_id, name AS device_name,
               primary_ip AS ip_address, region AS region_code, is_active
        FROM cmts_devices
        WHERE COALESCE(primary_ip, '') <> '' AND COALESCE(region, '') <> ''
    """,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE", "deploy/.env"))
    parser.add_argument("--source-system", default="go_collector")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_inventory(source_url: str) -> list[dict]:
    engine = create_engine(source_url, pool_pre_ping=True, future=True)
    rows: list[dict] = []
    with engine.connect() as conn:
        for device_type, query in INVENTORY_QUERIES.items():
            for row in conn.execute(text(query)).mappings():
                item = dict(row)
                item["device_type"] = device_type
                rows.append(item)
    return rows


def sync_scope(rows: list[dict], source_system: str, dry_run: bool = False) -> dict[str, int]:
    factory = make_session_factory(create_db_engine())
    counters = {"source_rows": len(rows), "inserted": 0, "updated": 0, "deactivated": 0}
    with session_scope(factory) as db:
        existing = db.execute(select(PlatformDeviceScope).where(PlatformDeviceScope.source_system == source_system)).scalars().all()
        by_key = {(row.device_type, row.source_device_id): row for row in existing}
        seen: set[tuple[str, str]] = set()
        for raw in rows:
            key = (str(raw["device_type"]), str(raw["source_device_id"]))
            seen.add(key)
            row = by_key.get(key)
            if row is None:
                row = PlatformDeviceScope(source_system=source_system, device_type=key[0], source_device_id=key[1])
                db.add(row)
                counters["inserted"] += 1
            else:
                counters["updated"] += 1
            row.device_name = str(raw.get("device_name") or "").strip() or None
            row.ip_address = str(raw.get("ip_address") or "").strip()
            row.region_code = str(raw.get("region_code") or "").strip()
            row.is_active = bool(raw.get("is_active"))
        for key, row in by_key.items():
            if key not in seen and row.is_active:
                row.is_active = False
                counters["deactivated"] += 1
        if dry_run:
            db.rollback()
    return counters


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(env_path, override=False)
    source_url = os.getenv("PLATFORM_INVENTORY_DATABASE_URL", "").strip()
    if not source_url:
        raise SystemExit("PLATFORM_INVENTORY_DATABASE_URL is required")
    result = sync_scope(load_inventory(source_url), args.source_system, args.dry_run)
    print(" ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
