"""Read-only production runtime report for AIOps database state."""

from __future__ import annotations

import json

from sqlalchemy import text

from app.db import create_db_engine


def rows(connection, sql: str) -> list[dict]:
    return [dict(item._mapping) for item in connection.execute(text(sql))]


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as connection:
        tasks = rows(
            connection,
            "SELECT id, name, enabled, hours, cron_expr, last_run_at, next_run_at, settings "
            "FROM report_tasks ORDER BY id",
        )
        for task in tasks:
            settings = task.pop("settings", None) or {}
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except json.JSONDecodeError:
                    settings = {}
            task["last_status"] = settings.get("last_status")
            task["last_run_uid"] = settings.get("last_run_uid")
            task["last_error"] = settings.get("last_error")
        payload = {
            "database_time": connection.execute(text("SELECT UTC_TIMESTAMP()" )).scalar_one(),
            "counts": {
                table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                for table in (
                    "report_tasks",
                    "report_records",
                    "ai_analysis_runs",
                    "ai_findings",
                    "ai_analysis_rules",
                    "llm_providers",
                    "llm_models",
                    "llm_usage_bindings",
                    "ai_chat_sessions",
                    "ai_chat_messages",
                    "audit_logs",
                )
            },
            "tasks": tasks,
            "latest_runs": rows(
                connection,
                "SELECT run_uid, status, hours, model_name, overall_level, tool_call_count, llm_call_count, "
                "total_tokens, duration_ms, error_message, created_at FROM ai_analysis_runs ORDER BY id DESC LIMIT 5",
            ),
            "latest_reports": rows(
                connection,
                "SELECT id, task_id, status, hours, error_message, created_at FROM report_records ORDER BY id DESC LIMIT 5",
            ),
            "models": rows(
                connection,
                "SELECT m.id, p.name AS provider, p.status AS provider_status, m.model_id, m.display_name, "
                "m.endpoint_type, m.enabled, m.status, m.last_checked_at, m.last_error "
                "FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id ORDER BY m.id",
            ),
            "bindings": rows(
                connection,
                "SELECT b.usage_key, b.model_id, b.priority, b.enabled, m.model_id AS model_name "
                "FROM llm_usage_bindings b JOIN llm_models m ON m.id=b.model_id "
                "ORDER BY b.usage_key, b.priority",
            ),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
