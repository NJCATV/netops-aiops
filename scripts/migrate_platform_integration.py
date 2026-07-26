"""Idempotently install the unified-platform identity and scope schema.

Run against a restored backup first. DDL is additive; no legacy column is
renamed or removed. DATABASE_URL selects the jscn_aiops schema.
"""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
from sqlalchemy import inspect, text

from app.db import create_db_engine
from app.models import PlatformDeviceScope, PlatformIdentityAudit

MIGRATION_ID = "20260717_platform_integration_v2"

COLUMNS = {
    "users": {
        "identity_source": "VARCHAR(32) NOT NULL DEFAULT 'local'",
        "external_subject": "VARCHAR(128) NULL",
        "external_role_code": "VARCHAR(64) NULL",
        "external_org_id": "BIGINT NULL",
        "external_org_name": "VARCHAR(128) NULL",
        "last_synced_at": "DATETIME NULL",
    },
    "ai_analysis_runs": {
        "scope_subject": "VARCHAR(128) NULL",
        "scope_org_id": "BIGINT NULL",
        "scope_regions_json": "JSON NULL",
    },
    "report_tasks": {
        "scope_subject": "VARCHAR(128) NULL",
        "scope_org_id": "BIGINT NULL",
        "scope_regions_json": "JSON NULL",
    },
}

INDEXES = {
    "users": {
        "uk_users_external_identity": (True, "identity_source, external_subject"),
        "idx_users_external_org": (False, "external_org_id"),
    },
    "ai_analysis_runs": {
        "idx_ai_analysis_runs_scope_subject": (False, "scope_subject"),
        "idx_ai_analysis_runs_scope_org": (False, "scope_org_id"),
    },
    "report_tasks": {
        "idx_report_tasks_scope_subject": (False, "scope_subject"),
        "idx_report_tasks_scope_org": (False, "scope_org_id"),
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE", "deploy/.env"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def migration_plan(engine) -> list[str]:
    inspector = inspect(engine)
    statements: list[str] = []
    tables = set(inspector.get_table_names())
    for table, wanted in COLUMNS.items():
        if table not in tables:
            raise RuntimeError(f"required legacy table is missing: {table}")
        existing = {row["name"] for row in inspector.get_columns(table)}
        for name, ddl in wanted.items():
            if name not in existing:
                statements.append(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")
    for table, wanted in INDEXES.items():
        existing = {row["name"] for row in inspector.get_indexes(table)}
        existing.update(row.get("name") for row in inspector.get_unique_constraints(table))
        for name, (unique, columns) in wanted.items():
            if name not in existing:
                statements.append(f"CREATE {'UNIQUE ' if unique else ''}INDEX `{name}` ON `{table}` ({columns})")
    return statements


def run(dry_run: bool = False) -> dict[str, object]:
    engine = create_db_engine()
    statements = migration_plan(engine)
    if dry_run:
        return {"migration": MIGRATION_ID, "dry_run": True, "statements": statements}
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    PlatformIdentityAudit.__table__.create(engine, checkfirst=True)
    PlatformDeviceScope.__table__.create(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET identity_source='local' WHERE identity_source IS NULL OR identity_source=''"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS aiops_schema_migrations (migration_id VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT IGNORE INTO aiops_schema_migrations (migration_id) VALUES (:migration_id)"), {"migration_id": MIGRATION_ID})
    remaining = migration_plan(engine)
    if remaining:
        raise RuntimeError(f"migration verification failed; remaining statements: {remaining}")
    return {"migration": MIGRATION_ID, "dry_run": False, "applied_statements": len(statements), "verified": True}


def main() -> int:
    args = parse_args()
    if args.env_file and os.path.exists(args.env_file):
        load_dotenv(args.env_file, override=False)
    result = run(args.dry_run)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
