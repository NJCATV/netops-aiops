"""AI analysis run, finding, and feedback APIs."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import threading
import traceback
import uuid
from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import desc, select

from aiops.agent.light_agent import run_light_agent
from aiops.agent.persistence import save_agent_result, save_ai_finding_feedback
from aiops.context.current_window_summary import SummaryConfig, SummaryLimits, build_current_window_summary
from aiops.rules.analysis_rules import apply_ai_rules, load_enabled_rules, record_rule_hits
from app.api.auth import admin_required, current_user_id, db_session_factory, load_current_user, login_required
from app.api.runtime import platform_device_ips
from app.db import create_db_engine, make_session_factory, session_scope
from app.models import AiAnalysisRun, AiFinding, AiFindingFeedback, utc_now


ai_bp = Blueprint("ai", __name__, url_prefix="/api")

DEFAULT_REPORT_DIR = "/data/jscn-aiops/reports/ai_runs"
VALID_FINDING_CATEGORIES = {"must_handle", "watch", "noise", "recovered", "insufficient", "correlation", "next_action"}


def json_error(message: str, status: int = 400, **extra: Any):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def parse_positive_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def safe_read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def compact_provider_name(provider: Any) -> str:
    text = str(provider or "").strip()
    if text.startswith("registry:"):
        text = text.split(":", 1)[1].strip()
    return text


def run_model_summary(run: AiAnalysisRun, result: dict | None = None) -> dict:
    result = result if isinstance(result, dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    runtime = result.get("agent_runtime") if isinstance(result.get("agent_runtime"), dict) else {}
    calls = runtime.get("llm_calls") if isinstance(runtime.get("llm_calls"), list) else []
    trace: list[str] = []
    providers: list[str] = []

    for call in calls:
        if not isinstance(call, dict):
            continue
        provider = compact_provider_name(call.get("provider") or call.get("llm_provider"))
        model = str(call.get("model") or call.get("model_name") or "").strip()
        label = " / ".join(part for part in (provider, model) if part)
        if label and (not trace or trace[-1] != label):
            trace.append(label)
        if provider:
            providers.append(provider)

    metadata_provider = compact_provider_name(metadata.get("llm_provider"))
    fallback_model = str(metadata.get("model") or runtime.get("model") or run.model_name or "").strip()
    if not trace and fallback_model:
        provider = metadata_provider or (providers[-1] if providers else "")
        trace.append(" / ".join(part for part in (provider, fallback_model) if part))

    return {
        "llm_provider": metadata_provider or (providers[-1] if providers else None),
        "model_selector": runtime.get("model_selector"),
        "model_trace": " -> ".join(trace) if trace else None,
    }


def serialize_run(run: AiAnalysisRun, include_result: bool = False) -> dict:
    result = safe_read_json(run.result_path)
    payload = {
        "id": run.id,
        "run_uid": run.run_uid,
        "scope_org_id": run.scope_org_id,
        "scope_regions": run.scope_regions_json,
        "status": run.status,
        "hours": run.hours,
        "window_start": isoformat(run.window_start),
        "window_end": isoformat(run.window_end),
        "overall_level": run.overall_level,
        "overall_title": run.overall_title,
        "summary_text": run.summary_text,
        "model_name": run.model_name,
        "tool_call_count": run.tool_call_count,
        "llm_call_count": run.llm_call_count,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "total_tokens": run.total_tokens,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "created_at": isoformat(run.created_at),
        "summary_path": run.summary_path,
        "result_path": run.result_path,
    }
    payload.update(run_model_summary(run, result))
    if include_result:
        payload.update(compact_agent_result(result))
    return payload


def visible_run_predicate(current_user):
    """AI analysis reports are global once the caller has AIOps page permission."""
    return None


def visible_run_query(current_user):
    stmt = select(AiAnalysisRun)
    boundary = visible_run_predicate(current_user)
    return stmt.where(boundary) if boundary is not None else stmt


def load_visible_run(session, run_uid: str, current_user):
    return session.execute(visible_run_query(current_user).where(AiAnalysisRun.run_uid == run_uid)).scalar_one_or_none()


def serialize_finding(row: AiFinding, include_raw: bool = False) -> dict:
    payload = {
        "id": row.id,
        "finding_uid": row.finding_uid,
        "run_id": row.run_id,
        "category": row.category,
        "title": row.title,
        "severity": row.severity,
        "confidence": row.confidence,
        "device_ip": row.device_ip,
        "device_name": row.device_name,
        "object_key": row.object_key,
        "event_types": row.event_types,
        "root_cause_hypothesis": row.root_cause_hypothesis,
        "impact": row.impact,
        "reason": row.reason,
        "evidence": row.evidence,
        "recommended_actions": row.recommended_actions,
        "missing_data": row.missing_data,
        "finding_fingerprint": row.finding_fingerprint,
        "lifecycle_status": row.lifecycle_status,
        "created_at": isoformat(row.created_at),
        "updated_at": isoformat(row.updated_at),
    }
    if include_raw:
        payload["raw_finding"] = row.raw_finding
    return payload


def serialize_feedback(row: AiFindingFeedback) -> dict:
    return {
        "id": row.id,
        "finding_id": row.finding_id,
        "feedback_type": row.feedback_type,
        "actual_root_cause": row.actual_root_cause,
        "action_taken": row.action_taken,
        "operator": row.operator,
        "comment": row.comment,
        "created_at": isoformat(row.created_at),
    }


def compact_agent_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return {}
    return {
        "overall_status": result.get("overall_status"),
        "summary_cards": result.get("summary_cards") or [],
        "must_handle": result.get("must_handle") or [],
        "watch": result.get("watch") or [],
        "noise": result.get("noise") or [],
        "recovered": result.get("recovered") or [],
        "insufficient": result.get("insufficient") or [],
        "correlations": result.get("correlations") or [],
        "next_actions": result.get("next_actions") or [],
        "data_quality": result.get("data_quality") or {},
        "user_rule_hits": result.get("user_rule_hits") or (result.get("metadata") or {}).get("user_rule_hits") or [],
        "metadata": result.get("metadata") or {},
        "agent_runtime": result.get("agent_runtime") or {},
    }


def build_summary_config(hours: int, allowed_device_ips: tuple[str, ...] | None = None) -> SummaryConfig:
    env_file = os.getenv("AIOPS_ENV_FILE")
    limits = SummaryLimits(
        critical_alarm_candidates=parse_positive_int(os.getenv("CURRENT_SUMMARY_CRITICAL_ALARM_CANDIDATES_LIMIT"), 50, 1, 100),
        critical_traps=parse_positive_int(os.getenv("CURRENT_SUMMARY_CRITICAL_TRAPS_LIMIT"), 20, 1, 100),
        important_traps=parse_positive_int(os.getenv("CURRENT_SUMMARY_IMPORTANT_TRAPS_LIMIT"), 20, 1, 100),
        open_incidents=parse_positive_int(os.getenv("CURRENT_SUMMARY_OPEN_INCIDENTS_LIMIT"), 50, 1, 100),
        baseline_deviations=parse_positive_int(os.getenv("CURRENT_SUMMARY_BASELINE_DEVIATIONS_LIMIT"), 30, 1, 100),
        new_anomalies=parse_positive_int(os.getenv("CURRENT_SUMMARY_NEW_ANOMALIES_LIMIT"), 30, 1, 100),
        flapping_objects=parse_positive_int(os.getenv("CURRENT_SUMMARY_FLAPPING_OBJECTS_LIMIT"), 30, 1, 100),
        multi_device_correlations=parse_positive_int(os.getenv("CURRENT_SUMMARY_MULTI_DEVICE_CORRELATIONS_LIMIT"), 30, 1, 100),
        noise_candidates=parse_positive_int(os.getenv("CURRENT_SUMMARY_NOISE_CANDIDATES_LIMIT"), 20, 1, 100),
        event_scan_size=parse_positive_int(os.getenv("CURRENT_SUMMARY_EVENT_SCAN_SIZE"), 5000, 100, 10000),
        trap_scan_size=parse_positive_int(os.getenv("CURRENT_SUMMARY_TRAP_SCAN_SIZE"), 500, 50, 2000),
    )
    return SummaryConfig(
        es_url=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        hours=hours,
        baseline_days=parse_positive_int(os.getenv("CURRENT_WINDOW_BASELINE_DAYS"), 7, 1, 30),
        syslog_index=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"),
        trap_index=os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"),
        event_index=os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*"),
        allowed_device_ips=allowed_device_ips,
        env_file=env_file,
        limits=limits,
    )


def mark_run_failed(run_uid: str, message: str) -> None:
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        run = session.execute(select(AiAnalysisRun).where(AiAnalysisRun.run_uid == run_uid)).scalar_one_or_none()
        if run:
            run.status = "failed"
            run.error_message = message[:4000]


def update_run_metadata_without_findings(run_uid: str, result: dict, summary_path: pathlib.Path, result_path: pathlib.Path) -> None:
    metadata = result.get("metadata") or {}
    runtime = result.get("agent_runtime") or {}
    overall = result.get("overall_status") or {}
    summary_meta = metadata
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        run = session.execute(select(AiAnalysisRun).where(AiAnalysisRun.run_uid == run_uid)).scalar_one_or_none()
        if not run:
            return
        run.status = "success" if result.get("ok", True) is not False else "failed"
        run.overall_level = overall.get("level")
        run.overall_title = overall.get("title")
        run.summary_text = overall.get("summary")
        run.model_name = summary_meta.get("model") or runtime.get("model")
        run.summary_path = str(summary_path)
        run.result_path = str(result_path)
        run.trajectory_dir = runtime.get("trajectory_dir")
        run.tool_call_count = summary_meta.get("tool_call_count") or runtime.get("tool_call_rounds")
        run.llm_call_count = len(runtime.get("llm_calls") or [])
        run.prompt_tokens = runtime.get("total_prompt_tokens")
        run.completion_tokens = runtime.get("total_completion_tokens")
        run.total_tokens = runtime.get("total_tokens")
        run.duration_ms = runtime.get("duration_ms")
        run.error_message = result.get("error")


def run_analysis_background(
    run_uid: str,
    hours: int,
    max_tool_rounds: int,
    save_to_db: bool,
    model_selector: str | None = None,
    allowed_device_ips: tuple[str, ...] | None = None,
) -> None:
    run_dir = pathlib.Path(os.getenv("AI_RUN_REPORT_DIR", DEFAULT_REPORT_DIR)) / run_uid
    summary_path = run_dir / "current_window_summary.json"
    result_path = run_dir / "light_agent_result.json"
    debug_dir = run_dir / "debug"
    env_file = os.getenv("AIOPS_ENV_FILE")
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = build_current_window_summary(build_summary_config(hours, allowed_device_ips))
        summary.setdefault("metadata", {})["api_run_uid"] = run_uid
        enabled_rules = load_enabled_rules(env_file=env_file)
        summary = apply_ai_rules(summary, enabled_rules)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = run_light_agent(
            summary,
            max_tool_rounds=max_tool_rounds,
            model=model_selector or os.getenv("AI_MANUAL_LLM_SELECTOR") or "llm_usage:aiops_manual_analysis",
            temperature=float(os.getenv("LIGHT_AGENT_TEMPERATURE", "0.1")),
            env_file=env_file,
            debug_dir=str(debug_dir),
        )
        result.setdefault("metadata", {})["run_uid"] = run_uid
        result["user_rule_hits"] = summary.get("user_rule_hits") or []
        result.setdefault("metadata", {})["user_rule_hits"] = summary.get("user_rule_hits") or []
        result.setdefault("metadata", {})["user_rule_hit_count"] = len(summary.get("user_rule_hits") or [])
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if save_to_db:
            save_result = save_agent_result(
                result,
                summary_path=str(summary_path),
                result_path=str(result_path),
                trajectory_dir=(result.get("agent_runtime") or {}).get("trajectory_dir"),
                env_file=env_file,
                run_uid=run_uid,
                update_existing=True,
            )
            if not save_result.get("ok"):
                mark_run_failed(run_uid, str(save_result.get("error") or "save_to_db_failed"))
        else:
            update_run_metadata_without_findings(run_uid, result, summary_path, result_path)
        record_rule_hits(run_uid, summary.get("user_rule_hits") or [])
    except Exception as exc:
        detail = f"{exc}\n{traceback.format_exc(limit=6)}"
        mark_run_failed(run_uid, detail)


@ai_bp.post("/ai-runs")
@admin_required
def create_ai_run(current_user):
    data = request.get_json(silent=True) or {}
    hours = parse_positive_int(data.get("hours"), 24, 1, 168)
    max_tool_rounds = parse_positive_int(data.get("max_tool_rounds"), 2, 0, 6)
    save_to_db = bool(data.get("save_to_db", True))
    model_ids = [str(item).strip() for item in (data.get("llm_model_ids") or []) if str(item).strip()]
    model_selector = f"llm_models:{','.join(model_ids)}" if model_ids else str(data.get("llm_selector") or "").strip() or None
    run_uid = str(uuid.uuid4())
    identity = getattr(current_user, "platform_identity", None)
    allowed_device_ips = platform_device_ips(current_user)
    now = utc_now()
    report_dir = pathlib.Path(os.getenv("AI_RUN_REPORT_DIR", DEFAULT_REPORT_DIR)) / run_uid
    summary_path = report_dir / "current_window_summary.json"
    result_path = report_dir / "light_agent_result.json"

    session_factory = db_session_factory()
    with session_scope(session_factory) as session:
        run = AiAnalysisRun(
            run_uid=run_uid,
            scope_subject=identity.subject if identity else None,
            scope_org_id=identity.org_id if identity else None,
            scope_regions_json=None if identity is None or identity.regions is None else list(identity.regions),
            window_start=now - dt.timedelta(hours=hours),
            window_end=now,
            hours=hours,
            status="running",
            summary_path=str(summary_path),
            result_path=str(result_path),
            error_message=None if save_to_db else "save_to_db=false requested; result will not be persisted",
        )
        session.add(run)

    thread = threading.Thread(
        target=run_analysis_background,
        args=(run_uid, hours, max_tool_rounds, save_to_db, model_selector, allowed_device_ips),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "run_uid": run_uid, "status": "running", "hours": hours, "max_tool_rounds": max_tool_rounds}), 202


@ai_bp.get("/ai-runs")
@login_required
def list_ai_runs(current_user):
    limit = parse_positive_int(request.args.get("limit"), 50, 1, 200)
    status = (request.args.get("status") or "").strip()
    stmt = visible_run_query(current_user)
    if status:
        stmt = stmt.where(AiAnalysisRun.status == status)
    stmt = stmt.order_by(desc(AiAnalysisRun.created_at)).limit(limit)
    with session_scope(db_session_factory()) as session:
        rows = session.execute(stmt).scalars().all()
        return jsonify({"ok": True, "items": [serialize_run(row) for row in rows], "limit": limit})


@ai_bp.get("/ai-runs/<run_uid>")
@login_required
def get_ai_run(run_uid: str, current_user):
    with session_scope(db_session_factory()) as session:
        run = load_visible_run(session, run_uid, current_user)
        if not run:
            return json_error("run_not_found", 404)
        return jsonify({"ok": True, "item": serialize_run(run, include_result=True)})


@ai_bp.get("/ai-runs/<run_uid>/findings")
@login_required
def get_ai_run_findings(run_uid: str, current_user):
    with session_scope(db_session_factory()) as session:
        run = load_visible_run(session, run_uid, current_user)
        if not run:
            return json_error("run_not_found", 404)
        rows = session.execute(select(AiFinding).where(AiFinding.run_id == run.id).order_by(AiFinding.category, desc(AiFinding.created_at))).scalars().all()
        return jsonify({"ok": True, "run_uid": run_uid, "items": [serialize_finding(row) for row in rows]})


@ai_bp.get("/findings")
@login_required
def list_findings(current_user):
    limit = parse_positive_int(request.args.get("limit"), 100, 1, 500)
    category = (request.args.get("category") or "").strip()
    lifecycle_status = (request.args.get("status") or "").strip()
    stmt = select(AiFinding).join(AiAnalysisRun, AiAnalysisRun.id == AiFinding.run_id)
    boundary = visible_run_predicate(current_user)
    if boundary is not None:
        stmt = stmt.where(boundary)
    if category:
        if category not in VALID_FINDING_CATEGORIES:
            return json_error("invalid_category", 400)
        stmt = stmt.where(AiFinding.category == category)
    if lifecycle_status:
        stmt = stmt.where(AiFinding.lifecycle_status == lifecycle_status)
    stmt = stmt.order_by(desc(AiFinding.created_at)).limit(limit)
    with session_scope(db_session_factory()) as session:
        rows = session.execute(stmt).scalars().all()
        return jsonify({"ok": True, "items": [serialize_finding(row) for row in rows], "limit": limit})


@ai_bp.get("/findings/<int:finding_id>")
@login_required
def get_finding(finding_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        stmt = select(AiFinding).join(AiAnalysisRun, AiAnalysisRun.id == AiFinding.run_id).where(AiFinding.id == finding_id)
        boundary = visible_run_predicate(current_user)
        if boundary is not None:
            stmt = stmt.where(boundary)
        finding = session.execute(stmt).scalar_one_or_none()
        if not finding:
            return json_error("finding_not_found", 404)
        feedback = session.execute(select(AiFindingFeedback).where(AiFindingFeedback.finding_id == finding_id).order_by(desc(AiFindingFeedback.created_at))).scalars().all()
        payload = serialize_finding(finding, include_raw=True)
        payload["feedback"] = [serialize_feedback(row) for row in feedback]
        return jsonify({"ok": True, "item": payload})


@ai_bp.post("/findings/<int:finding_id>/feedback")
@admin_required
def add_finding_feedback(finding_id: int, current_user):
    data = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        stmt = select(AiFinding.id).join(AiAnalysisRun, AiAnalysisRun.id == AiFinding.run_id).where(AiFinding.id == finding_id)
        boundary = visible_run_predicate(current_user)
        if boundary is not None:
            stmt = stmt.where(boundary)
        if session.execute(stmt).scalar_one_or_none() is None:
            return json_error("finding_not_found", 404)
    user = load_current_user()
    data.setdefault("operator", user.username if user else f"user:{current_user_id()}")
    result = save_ai_finding_feedback(finding_id, data, env_file=os.getenv("AIOPS_ENV_FILE"))
    if not result.get("ok"):
        status = 404 if result.get("error") == "finding_not_found" else 400
        return jsonify(result), status
    return jsonify(result), 201
