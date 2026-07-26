#!/usr/bin/env python3
"""Initialize MySQL tables for JSCN AIOps application metadata."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base, create_db_engine, make_session_factory, session_scope  # noqa: E402
from app.llm_defaults import ensure_default_llm_providers  # noqa: E402
from app.models import AppSetting, AuditLog, User  # noqa: E402,F401
import app.models  # noqa: E402,F401


def load_env(path: Optional[str]) -> None:
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def ensure_admin(session_factory, username: str, password: Optional[str]) -> bool:
    with session_scope(session_factory) as session:
        existing = session.query(User).filter(User.username == username).one_or_none()
        if existing:
            return False
        if not password:
            raise ValueError("ADMIN_PASSWORD is required when the admin user does not exist")
        session.add(
            User(
                username=username,
                password_hash=generate_password_hash(password),
                role="admin",
                display_name="Default Administrator",
                is_active=True,
            )
        )
        session.add(AuditLog(actor="system", action="init_admin_user", resource_type="users", resource_id=username))
        return True


def ensure_defaults(session_factory) -> None:
    defaults = {
        "report.default_hours": ("24", "integer", "Default AI report lookback hours"),
        "report.baseline_days": ("7", "integer", "Default baseline days for AI context"),
        "mail.enabled": ("false", "boolean", "Whether scheduled email sending is enabled"),
    }
    with session_scope(session_factory) as session:
        for key, (value, value_type, description) in defaults.items():
            existing = session.query(AppSetting).filter(AppSetting.setting_key == key).one_or_none()
            if not existing:
                session.add(AppSetting(setting_key=key, setting_value=value, value_type=value_type, description=description))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--admin-username", default=os.getenv("ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD"))
    args = parser.parse_args()

    load_env(args.env_file)
    admin_username = args.admin_username or os.getenv("ADMIN_USERNAME", "admin")
    admin_password = args.admin_password or os.getenv("ADMIN_PASSWORD")

    engine = create_db_engine()
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    admin_created = ensure_admin(session_factory, admin_username, admin_password)
    ensure_defaults(session_factory)
    llm_providers_created = ensure_default_llm_providers(session_factory)

    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())
    result = {
        "database_url": str(engine.url).replace(engine.url.password or "", "****") if engine.url.password else str(engine.url),
        "tables": tables,
        "admin_username": admin_username,
        "admin_created": admin_created,
        "llm_providers_created": llm_providers_created,
    }
    with engine.connect() as conn:
        result["server_version"] = conn.execute(text("SELECT VERSION()")).scalar_one()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
