"""Validate a JSCN-233 application plane or JSCN-20 data plane before cutover."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("app", "data"))
    parser.add_argument("--env-file", required=True)
    return parser.parse_args()


def http_check(url: str, accepted=(200,), headers: dict[str, str] | None = None) -> dict:
    try:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(request, timeout=8) as response:
            code = response.status
            body = response.read(1000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        code = exc.code
        body = exc.read(1000).decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    return {"ok": code in accepted, "url": url, "status": code, "body_preview": body[:160]}


def app_checks() -> list[dict]:
    checks: list[dict] = []
    secret = os.getenv("AIOPS_INTERNAL_SHARED_SECRET", "")
    checks.append({"name": "shared_secret", "ok": len(secret) >= 64, "detail": "configured" if secret else "missing"})
    checks.append({"name": "local_auth_disabled", "ok": os.getenv("AIOPS_LOCAL_AUTH_ENABLED", "").lower() == "false"})
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        checks.append({"name": "database", "ok": False, "detail": "DATABASE_URL missing"})
    else:
        try:
            engine = create_engine(database_url, pool_pre_ping=True, future=True)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            inspector = inspect(engine)
            required = {
                "users": {"identity_source", "external_subject", "external_org_id"},
                "ai_analysis_runs": {"scope_subject", "scope_org_id", "scope_regions_json"},
                "report_tasks": {"scope_subject", "scope_org_id", "scope_regions_json"},
                "platform_identity_audit": set(),
                "platform_device_scope": set(),
            }
            missing = {}
            tables = set(inspector.get_table_names())
            for table, columns in required.items():
                if table not in tables:
                    missing[table] = ["<table>"]
                    continue
                actual = {row["name"] for row in inspector.get_columns(table)}
                absent = sorted(columns - actual)
                if absent:
                    missing[table] = absent
            checks.append({"name": "database_schema", "ok": not missing, "missing": missing})
        except Exception as exc:
            checks.append({"name": "database", "ok": False, "detail": str(exc)})
    es = os.getenv("ELASTICSEARCH_URL", "http://172.25.60.20:9200").rstrip("/")
    checks.append({"name": "elasticsearch", **http_check(es + "/_cluster/health")})
    qq_url = os.getenv("QQ_ADAPTER_INTERNAL_URL", "").rstrip("/")
    qq_token = os.getenv("QQ_ADAPTER_ADMIN_TOKEN", "")
    if qq_url and qq_token:
        checks.append({"name": "qq_adapter", **http_check(qq_url + "/internal/status", headers={"Authorization": f"Bearer {qq_token}"})})
    else:
        checks.append({"name": "qq_adapter", "ok": False, "detail": "QQ adapter internal URL/token missing"})
    return checks


def data_checks() -> list[dict]:
    secret = os.getenv("AIOPS_INTERNAL_SHARED_SECRET", "")
    es = os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200").rstrip("/")
    api = os.getenv("AIOPS_API_BASE", "http://172.25.60.20:18080").rstrip("/")
    return [
        {"name": "shared_secret", "ok": len(secret) >= 64, "detail": "configured" if secret else "missing"},
        {"name": "elasticsearch", **http_check(es + "/_cluster/health")},
        {"name": "app_plane_api", **http_check(api + "/api/auth/me", accepted=(401, 403))},
        {"name": "qq_service_identity", "ok": bool(os.getenv("AIOPS_BOT_SERVICE_SUBJECT", ""))},
        {"name": "qq_admin_token", "ok": len(os.getenv("QQ_ADAPTER_ADMIN_TOKEN", "")) >= 32},
    ]


def main() -> int:
    parsed = args()
    load_dotenv(parsed.env_file, override=False)
    checks = app_checks() if parsed.role == "app" else data_checks()
    result = {"role": parsed.role, "ok": all(item.get("ok") for item in checks), "checks": checks}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
