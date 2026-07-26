"""Scheduled AI analysis task runner."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select

from aiops.agent.light_agent import run_light_agent
from aiops.agent.persistence import save_agent_result
from aiops.context.current_window_summary import SummaryConfig, SummaryLimits, build_current_window_summary
from aiops.rules.analysis_rules import apply_ai_rules, load_enabled_rules, record_rule_hits
from app.db import create_db_engine, make_session_factory, session_scope
from app.models import AiAnalysisRun, ReportTask, utc_now


LOGGER = logging.getLogger(__name__)
DEFAULT_REPORT_DIR = "/data/jscn-aiops/reports/ai_runs"


@dataclass
class TaskRunResult:
    ok: bool
    run_uid: Optional[str] = None
    status: str = "unknown"
    error: Optional[str] = None


def parse_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def ensure_aware(value: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def isoformat(value: Optional[dt.datetime]) -> Optional[str]:
    value = ensure_aware(value)
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def task_settings(task: ReportTask) -> dict:
    settings = dict(task.settings or {})
    return {
        "task_name": task.name,
        "enabled": bool(task.enabled),
        "hours": parse_int(settings.get("hours", task.hours), 24, 1, 168),
        "task_type": str(settings.get("task_type") or "ai_analysis"),
        "max_tool_rounds": parse_int(settings.get("max_tool_rounds"), 2, 0, 6),
        "schedule_type": str(settings.get("schedule_type") or ("cron" if task.cron_expr else "interval")),
        "interval_minutes": parse_int(settings.get("interval_minutes"), 60, 1, 10080),
        "cron_expr": settings.get("cron_expr") or task.cron_expr,
        "daily_time": str(settings.get("daily_time") or "08:00"),
        "save_to_db": bool(settings.get("save_to_db", True)),
        "email_enabled": bool(settings.get("email_enabled", False)),
        "recipients": settings.get("recipients", task.recipients or []),
        "llm_usage_key": str(settings.get("llm_usage_key") or "aiops_scheduled_analysis"),
        "llm_model_ids": settings.get("llm_model_ids") or [],
        "last_status": settings.get("last_status"),
        "last_error": settings.get("last_error"),
        "last_run_uid": settings.get("last_run_uid"),
        "last_duration_ms": settings.get("last_duration_ms"),
        "remark": settings.get("remark"),
    }


def model_selector_from_settings(settings: dict) -> Optional[str]:
    model_ids = [str(item).strip() for item in (settings.get("llm_model_ids") or []) if str(item).strip()]
    if model_ids:
        return "llm_models:" + ",".join(model_ids)
    usage_key = str(settings.get("llm_usage_key") or "").strip()
    if usage_key:
        return f"llm_usage:{usage_key}"
    return os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_MODEL")


def public_task(task: ReportTask) -> dict:
    settings = task_settings(task)
    settings.update(
        {
            "id": task.id,
            "task_name": task.name,
            "enabled": bool(task.enabled),
            "created_by": task.created_by,
            "scope_org_id": task.scope_org_id,
            "scope_regions": task.scope_regions_json,
            "last_run_at": isoformat(task.last_run_at),
            "next_run_at": isoformat(task.next_run_at),
            "created_at": isoformat(task.created_at),
            "updated_at": isoformat(task.updated_at),
        }
    )
    return settings


def parse_daily_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = value.strip().split(":", 1)
        return max(0, min(int(hour), 23)), max(0, min(int(minute), 59))
    except Exception:
        return 8, 0


def next_run_from_cron(expr: str, now: dt.datetime) -> dt.datetime:
    parts = str(expr or "").split()
    if len(parts) != 5:
        return now + dt.timedelta(hours=1)
    minute_text, hour_text = parts[0], parts[1]
    if not minute_text.isdigit() or not hour_text.isdigit():
        return now + dt.timedelta(hours=1)
    hour = max(0, min(int(hour_text), 23))
    minute = max(0, min(int(minute_text), 59))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    return candidate


def compute_next_run(task: ReportTask, *, now: Optional[dt.datetime] = None) -> dt.datetime:
    now = ensure_aware(now) or utc_now()
    settings = task_settings(task)
    schedule_type = settings["schedule_type"]
    if schedule_type == "daily":
        hour, minute = parse_daily_time(settings["daily_time"])
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += dt.timedelta(days=1)
        return candidate
    if schedule_type == "cron":
        return next_run_from_cron(settings.get("cron_expr") or "", now)
    interval = settings["interval_minutes"]
    return now + dt.timedelta(minutes=interval)


def build_summary_config(hours: int, allowed_device_ips: tuple[str, ...] | None = None) -> SummaryConfig:
    limits = SummaryLimits(
        critical_alarm_candidates=parse_int(os.getenv("CURRENT_SUMMARY_CRITICAL_ALARM_CANDIDATES_LIMIT"), 50, 1, 100),
        critical_traps=parse_int(os.getenv("CURRENT_SUMMARY_CRITICAL_TRAPS_LIMIT"), 20, 1, 100),
        important_traps=parse_int(os.getenv("CURRENT_SUMMARY_IMPORTANT_TRAPS_LIMIT"), 20, 1, 100),
        open_incidents=parse_int(os.getenv("CURRENT_SUMMARY_OPEN_INCIDENTS_LIMIT"), 50, 1, 100),
        baseline_deviations=parse_int(os.getenv("CURRENT_SUMMARY_BASELINE_DEVIATIONS_LIMIT"), 30, 1, 100),
        new_anomalies=parse_int(os.getenv("CURRENT_SUMMARY_NEW_ANOMALIES_LIMIT"), 30, 1, 100),
        flapping_objects=parse_int(os.getenv("CURRENT_SUMMARY_FLAPPING_OBJECTS_LIMIT"), 30, 1, 100),
        multi_device_correlations=parse_int(os.getenv("CURRENT_SUMMARY_MULTI_DEVICE_CORRELATIONS_LIMIT"), 30, 1, 100),
        noise_candidates=parse_int(os.getenv("CURRENT_SUMMARY_NOISE_CANDIDATES_LIMIT"), 20, 1, 100),
        event_scan_size=parse_int(os.getenv("CURRENT_SUMMARY_EVENT_SCAN_SIZE"), 5000, 100, 10000),
        trap_scan_size=parse_int(os.getenv("CURRENT_SUMMARY_TRAP_SCAN_SIZE"), 500, 50, 2000),
    )
    return SummaryConfig(
        es_url=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        hours=hours,
        baseline_days=parse_int(os.getenv("CURRENT_WINDOW_BASELINE_DAYS"), 7, 1, 30),
        syslog_index=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"),
        trap_index=os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"),
        event_index=os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*"),
        allowed_device_ips=allowed_device_ips,
        env_file=os.getenv("AIOPS_ENV_FILE"),
        limits=limits,
    )


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute_task_once(task_id: int, *, trigger: str = "scheduler") -> TaskRunResult:
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    run_uid = str(uuid.uuid4())
    now = utc_now()
    with session_scope(session_factory) as session:
        task = session.get(ReportTask, task_id)
        if not task:
            return TaskRunResult(ok=False, status="failed", error="task_not_found")
        settings = task_settings(task)
        scope_subject = task.scope_subject
        scope_org_id = task.scope_org_id
        scope_regions = None if task.scope_regions_json is None else tuple(str(item) for item in task.scope_regions_json)
        # AIOps scheduled analysis always uses the global operational dataset.
        # Legacy scope columns remain only as historical audit metadata.
        allowed_device_ips = None
        settings["last_status"] = "running"
        settings["last_error"] = None
        settings["last_run_uid"] = run_uid
        task.settings = settings
        task.last_run_at = now
        report_dir = pathlib.Path(os.getenv("AI_RUN_REPORT_DIR", DEFAULT_REPORT_DIR)) / run_uid
        run = AiAnalysisRun(
            run_uid=run_uid,
            scope_subject=scope_subject,
            scope_org_id=scope_org_id,
            scope_regions_json=None if scope_regions is None else list(scope_regions),
            window_start=now - dt.timedelta(hours=settings["hours"]),
            window_end=now,
            hours=settings["hours"],
            status="running",
            summary_path=str(report_dir / "current_window_summary.json"),
            result_path=str(report_dir / "light_agent_result.json"),
        )
        session.add(run)
        session.flush()

    run_started = time.monotonic()
    try:
        report_dir = pathlib.Path(os.getenv("AI_RUN_REPORT_DIR", DEFAULT_REPORT_DIR)) / run_uid
        summary_path = report_dir / "current_window_summary.json"
        result_path = report_dir / "light_agent_result.json"
        debug_dir = report_dir / "debug"
        summary = build_current_window_summary(build_summary_config(settings["hours"], allowed_device_ips))
        summary.setdefault("metadata", {})["scheduled_task_id"] = task_id
        summary.setdefault("metadata", {})["scheduler_trigger"] = trigger
        enabled_rules = load_enabled_rules(env_file=os.getenv("AIOPS_ENV_FILE"))
        summary = apply_ai_rules(summary, enabled_rules)
        write_json(summary_path, summary)
        result = run_light_agent(
            summary,
            max_tool_rounds=settings["max_tool_rounds"],
            model=model_selector_from_settings(settings),
            temperature=float(os.getenv("LIGHT_AGENT_TEMPERATURE", "0.1")),
            env_file=os.getenv("AIOPS_ENV_FILE"),
            debug_dir=str(debug_dir),
        )
        result.setdefault("metadata", {})["run_uid"] = run_uid
        result.setdefault("metadata", {})["scheduled_task_id"] = task_id
        result["user_rule_hits"] = summary.get("user_rule_hits") or []
        result.setdefault("metadata", {})["user_rule_hits"] = summary.get("user_rule_hits") or []
        result.setdefault("metadata", {})["user_rule_hit_count"] = len(summary.get("user_rule_hits") or [])
        write_json(result_path, result)
        save_agent_result(
            result,
            summary_path=str(summary_path),
            result_path=str(result_path),
            trajectory_dir=(result.get("agent_runtime") or {}).get("trajectory_dir"),
            env_file=os.getenv("AIOPS_ENV_FILE"),
            run_uid=run_uid,
            update_existing=True,
        )
        record_rule_hits(run_uid, summary.get("user_rule_hits") or [])
        status = "success" if result.get("ok", True) is not False else "failed"
        error = result.get("error")
    except Exception as exc:
        status = "failed"
        error = f"{exc}\n{traceback.format_exc(limit=6)}"
        with session_scope(session_factory) as session:
            run = session.execute(select(AiAnalysisRun).where(AiAnalysisRun.run_uid == run_uid)).scalar_one_or_none()
            if run:
                run.status = "failed"
                run.error_message = error[:4000]

    with session_scope(session_factory) as session:
        task = session.get(ReportTask, task_id)
        if task:
            settings = task_settings(task)
            settings["last_status"] = status
            settings["last_error"] = error[:1000] if error else None
            settings["last_run_uid"] = run_uid
            settings["last_duration_ms"] = int((time.monotonic() - run_started) * 1000)
            task.settings = settings
            task.last_run_at = utc_now()
            task.next_run_at = compute_next_run(task, now=utc_now())
    return TaskRunResult(ok=status == "success", run_uid=run_uid, status=status, error=error)


def run_due_tasks_once() -> list[TaskRunResult]:
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    now = utc_now()
    due_ids: list[int] = []
    with session_scope(session_factory) as session:
        tasks = session.execute(select(ReportTask).where(ReportTask.enabled.is_(True))).scalars().all()
        for task in tasks:
            settings = task_settings(task)
            if settings.get("last_status") == "running":
                continue
            next_run = ensure_aware(task.next_run_at)
            if next_run is None:
                task.next_run_at = now
                next_run = now
            if next_run <= now:
                due_ids.append(task.id)
    results: list[TaskRunResult] = []
    for task_id in due_ids:
        LOGGER.info("Running scheduled AI task id=%s", task_id)
        results.append(execute_task_once(task_id, trigger="scheduler"))
    return results


def scheduler_loop(poll_seconds: int = 60) -> None:
    LOGGER.info("AI scheduler started poll_seconds=%s", poll_seconds)
    while True:
        try:
            results = run_due_tasks_once()
            for result in results:
                LOGGER.info("Scheduled run finished run_uid=%s status=%s", result.run_uid, result.status)
        except Exception:
            LOGGER.exception("AI scheduler loop failed")
        time.sleep(max(5, poll_seconds))
