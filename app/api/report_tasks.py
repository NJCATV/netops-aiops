"""Scheduled AI analysis task APIs."""

from __future__ import annotations

import threading
from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import desc, select

from aiops.scheduler.ai_scheduler import compute_next_run, execute_task_once, parse_int, public_task, task_settings
from app.api.auth import admin_required, db_session_factory, login_required
from app.db import session_scope
from app.models import ReportTask


report_tasks_bp = Blueprint("report_tasks", __name__, url_prefix="/api")

VALID_SCHEDULE_TYPES = {"interval", "daily", "cron"}


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def visible_task_query(current_user):
    """Page permission grants access to the shared AIOps task catalogue."""
    return select(ReportTask)


def load_visible_task(session, task_id: int, current_user):
    return session.execute(visible_task_query(current_user).where(ReportTask.id == task_id)).scalar_one_or_none()


def normalize_task_payload(payload: dict[str, Any], existing: ReportTask | None = None) -> tuple[dict, dict | None]:
    name = str(payload.get("task_name") or payload.get("name") or (existing.name if existing else "")).strip()
    if not name:
        return {}, {"error": "task_name_required"}
    schedule_type = str(payload.get("schedule_type") or (task_settings(existing)["schedule_type"] if existing else "interval")).strip()
    if schedule_type not in VALID_SCHEDULE_TYPES:
        return {}, {"error": "invalid_schedule_type"}
    settings = dict(existing.settings or {}) if existing else {}
    settings.update(
        {
            "hours": parse_int(payload.get("hours", settings.get("hours", existing.hours if existing else 24)), 24, 1, 168),
            "task_type": str(payload.get("task_type", settings.get("task_type", "ai_analysis")) or "ai_analysis"),
            "max_tool_rounds": parse_int(payload.get("max_tool_rounds", settings.get("max_tool_rounds", 2)), 2, 0, 6),
            "schedule_type": schedule_type,
            "interval_minutes": parse_int(payload.get("interval_minutes", settings.get("interval_minutes", 60)), 60, 1, 10080),
            "cron_expr": payload.get("cron_expr", settings.get("cron_expr")),
            "daily_time": str(payload.get("daily_time", settings.get("daily_time", "08:00"))),
            "save_to_db": bool(payload.get("save_to_db", settings.get("save_to_db", True))),
            "email_enabled": bool(payload.get("email_enabled", settings.get("email_enabled", False))),
            "recipients": payload.get("recipients", settings.get("recipients", [])),
            "llm_usage_key": str(payload.get("llm_usage_key", settings.get("llm_usage_key", "aiops_scheduled_analysis")) or "aiops_scheduled_analysis"),
            "llm_model_ids": payload.get("llm_model_ids", settings.get("llm_model_ids", [])) or [],
            "remark": str(payload.get("remark", settings.get("remark", "")) or ""),
        }
    )
    enabled = bool(payload.get("enabled", existing.enabled if existing else True))
    return {"name": name, "enabled": enabled, "settings": settings, "hours": settings["hours"], "cron_expr": settings.get("cron_expr")}, None


@report_tasks_bp.get("/report-tasks")
@login_required
def list_report_tasks(current_user):
    with session_scope(db_session_factory()) as session:
        rows = session.execute(visible_task_query(current_user).order_by(desc(ReportTask.created_at))).scalars().all()
        return jsonify({"ok": True, "items": [public_task(row) for row in rows]})


@report_tasks_bp.post("/report-tasks")
@admin_required
def create_report_task(current_user):
    payload = request.get_json(silent=True) or {}
    values, error = normalize_task_payload(payload)
    if error:
        return json_error(error["error"], 400)
    with session_scope(db_session_factory()) as session:
        task = ReportTask(
            scope_subject=None,
            scope_org_id=None,
            scope_regions_json=None,
            name=values["name"],
            enabled=values["enabled"],
            hours=values["hours"],
            cron_expr=values["cron_expr"],
            recipients=values["settings"].get("recipients"),
            settings=values["settings"],
            created_by=current_user.username,
        )
        task.next_run_at = compute_next_run(task)
        session.add(task)
        session.flush()
        return jsonify({"ok": True, "item": public_task(task)}), 201


@report_tasks_bp.get("/report-tasks/<int:task_id>")
@login_required
def get_report_task(task_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        task = load_visible_task(session, task_id, current_user)
        if not task:
            return json_error("task_not_found", 404)
        return jsonify({"ok": True, "item": public_task(task)})


@report_tasks_bp.put("/report-tasks/<int:task_id>")
@admin_required
def update_report_task(task_id: int, current_user):
    payload = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        task = load_visible_task(session, task_id, current_user)
        if not task:
            return json_error("task_not_found", 404)
        values, error = normalize_task_payload(payload, task)
        if error:
            return json_error(error["error"], 400)
        task.name = values["name"]
        task.enabled = values["enabled"]
        task.hours = values["hours"]
        task.cron_expr = values["cron_expr"]
        task.recipients = values["settings"].get("recipients")
        task.settings = values["settings"]
        task.next_run_at = compute_next_run(task)
        return jsonify({"ok": True, "item": public_task(task)})


@report_tasks_bp.delete("/report-tasks/<int:task_id>")
@admin_required
def delete_report_task(task_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        task = load_visible_task(session, task_id, current_user)
        if not task:
            return json_error("task_not_found", 404)
        session.delete(task)
        return jsonify({"ok": True, "deleted": task_id})


@report_tasks_bp.post("/report-tasks/<int:task_id>/enable")
@admin_required
def enable_report_task(task_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        task = load_visible_task(session, task_id, current_user)
        if not task:
            return json_error("task_not_found", 404)
        task.enabled = True
        task.next_run_at = compute_next_run(task)
        return jsonify({"ok": True, "item": public_task(task)})


@report_tasks_bp.post("/report-tasks/<int:task_id>/disable")
@admin_required
def disable_report_task(task_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        task = load_visible_task(session, task_id, current_user)
        if not task:
            return json_error("task_not_found", 404)
        task.enabled = False
        return jsonify({"ok": True, "item": public_task(task)})


@report_tasks_bp.post("/report-tasks/<int:task_id>/run-now")
@admin_required
def run_report_task_now(task_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        if not load_visible_task(session, task_id, current_user):
            return json_error("task_not_found", 404)
    thread = threading.Thread(target=execute_task_once, kwargs={"task_id": task_id, "trigger": "api_run_now"}, daemon=True)
    thread.start()
    return jsonify({"ok": True, "status": "running", "task_id": task_id}), 202
