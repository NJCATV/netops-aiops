"""Persistence for lightweight AIOps Agent runs, findings, and feedback."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from sqlalchemy import and_, delete, desc, or_, select

from app.db import Base, create_db_engine, make_session_factory, session_scope
from app.models import AiAnalysisRun, AiFinding, AiFindingFeedback


VALID_FEEDBACK_TYPES = {
    "confirmed",
    "false_positive",
    "ignored",
    "resolved",
    "suppressed",
    "escalated",
    "needs_more_data",
}

FEEDBACK_LIFECYCLE = {
    "confirmed": "active",
    "false_positive": "false_positive",
    "ignored": "ignored",
    "resolved": "resolved",
    "suppressed": "suppressed",
    "escalated": "active",
    "needs_more_data": "unknown",
}

CATEGORY_FIELDS = {
    "must_handle": "must_handle",
    "watch": "watch",
    "noise": "noise",
    "recovered": "recovered",
    "insufficient": "insufficient",
    "correlation": "correlations",
    "next_action": "next_actions",
}


def load_env_file(path: Optional[str] = None) -> None:
    if load_dotenv is None:
        return
    if path:
        load_dotenv(path, override=True)
        return
    candidates = [".env", "deploy/.env"]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            load_dotenv(candidate, override=False)


def parse_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def normalize_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").lower()).strip()
    return text[:300]


def normalized_device_identity(finding: dict) -> tuple[Optional[str], Optional[str]]:
    """Keep compact identity columns bounded while preserving the raw finding.

    LLM findings can describe a correlated group of devices in one field. Those
    values belong in ``raw_finding``; the indexed identity columns must remain
    bounded so one verbose finding cannot fail the entire scheduled report.
    """
    if finding.get("device_identity_source") == "sender_fallback":
        return None, None
    device_ip = finding.get("managed_device_ip") or finding.get("device_ip")
    device_name = finding.get("managed_device_name") or finding.get("device_name")
    compact_ip = str(device_ip or "").strip()[:512] or None
    compact_name = str(device_name or "").strip()[:128] or None
    return compact_ip, compact_name


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_fingerprint(category: str, finding: dict) -> str:
    event_types = finding.get("event_types") or finding.get("event_type") or []
    if isinstance(event_types, str):
        event_types = [event_types]
    device_ip, device_name = normalized_device_identity(finding)
    basis = {
        "category": category,
        "event_types": sorted(str(item) for item in event_types if item),
        "device_ip": device_ip,
        "device_name": device_name,
        "object_key": finding.get("object_key"),
        "title": normalize_text(finding.get("title") or finding.get("action") or finding.get("reason")),
    }
    return hashlib.sha256(stable_json(basis).encode("utf-8")).hexdigest()[:32]


def finding_title(category: str, finding: dict) -> str:
    return str(finding.get("title") or finding.get("action") or finding.get("reason") or category)[:512]


def category_lifecycle(category: str) -> str:
    if category == "noise":
        return "ignored"
    if category == "recovered":
        return "resolved"
    return "unknown"


def iter_findings(result: dict) -> Iterable[tuple[str, dict]]:
    for category, field in CATEGORY_FIELDS.items():
        rows = result.get(field) or []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield category, row


def create_engine_and_tables():
    engine = create_db_engine()
    Base.metadata.create_all(engine)
    return engine


def save_agent_result(
    result: dict,
    *,
    summary_path: Optional[str] = None,
    result_path: Optional[str] = None,
    trajectory_dir: Optional[str] = None,
    env_file: Optional[str] = None,
    run_uid: Optional[str] = None,
    update_existing: bool = False,
) -> dict:
    load_env_file(env_file)
    if not isinstance(result, dict):
        return {"ok": False, "error": "invalid_result"}
    engine = create_engine_and_tables()
    session_factory = make_session_factory(engine)

    metadata = result.get("metadata") or {}
    runtime = result.get("agent_runtime") or {}
    overall = result.get("overall_status") or {}
    run_uid = run_uid or metadata.get("run_uid") or str(uuid.uuid4())
    window_start = parse_time(metadata.get("window_start"))
    window_end = parse_time(metadata.get("window_end"))
    hours = None
    if window_start and window_end:
        hours = int(round((window_end - window_start).total_seconds() / 3600))
    status = "success" if result.get("ok", True) is not False else "failed"

    with session_scope(session_factory) as session:
        existing = session.execute(select(AiAnalysisRun).where(AiAnalysisRun.run_uid == run_uid)).scalar_one_or_none()
        if existing and not update_existing:
            return {"ok": True, "run_id": existing.id, "run_uid": existing.run_uid, "finding_count": 0, "deduplicated": True}

        run = existing or AiAnalysisRun(run_uid=run_uid)
        run.window_start = window_start
        run.window_end = window_end
        run.hours = hours
        run.model_name = metadata.get("model") or runtime.get("model")
        run.status = status
        run.overall_level = overall.get("level")
        run.overall_title = overall.get("title")
        run.summary_text = overall.get("summary")
        run.summary_path = summary_path
        run.result_path = result_path
        run.trajectory_dir = trajectory_dir or runtime.get("trajectory_dir")
        run.tool_call_count = metadata.get("tool_call_count") or runtime.get("tool_call_rounds")
        run.llm_call_count = len(runtime.get("llm_calls") or [])
        run.prompt_tokens = runtime.get("total_prompt_tokens")
        run.completion_tokens = runtime.get("total_completion_tokens")
        run.total_tokens = runtime.get("total_tokens")
        run.duration_ms = runtime.get("duration_ms")
        run.error_message = result.get("error")
        session.add(run)
        session.flush()
        if existing and update_existing:
            session.execute(delete(AiFinding).where(AiFinding.run_id == run.id))

        count = 0
        for category, finding in iter_findings(result):
            fingerprint = make_fingerprint(category, finding)
            device_ip, device_name = normalized_device_identity(finding)
            item = AiFinding(
                finding_uid=str(uuid.uuid4()),
                run_id=run.id,
                category=category,
                title=finding_title(category, finding),
                severity=finding.get("severity") or finding.get("level") or finding.get("priority"),
                confidence=finding.get("confidence") if isinstance(finding.get("confidence"), (int, float)) else None,
                device_ip=device_ip,
                device_name=device_name,
                object_key=finding.get("object_key"),
                event_types=finding.get("event_types") or finding.get("event_type") or [],
                root_cause_hypothesis=finding.get("root_cause_hypothesis") or finding.get("conclusion"),
                impact=finding.get("impact"),
                reason=finding.get("reason"),
                evidence=finding.get("evidence") or [],
                recommended_actions=finding.get("recommended_actions") or ([finding.get("action")] if finding.get("action") else []),
                missing_data=finding.get("missing_data") or finding.get("needed_data") or [],
                raw_finding=finding,
                finding_fingerprint=fingerprint,
                lifecycle_status=category_lifecycle(category),
            )
            session.add(item)
            count += 1
        session.flush()
        return {"ok": True, "run_id": run.id, "run_uid": run.run_uid, "finding_count": count, "deduplicated": False}


def save_ai_finding_feedback(finding_id: int, feedback: dict, *, env_file: Optional[str] = None) -> dict:
    load_env_file(env_file)
    feedback_type = str(feedback.get("feedback_type") or "").strip()
    if feedback_type not in VALID_FEEDBACK_TYPES:
        return {"ok": False, "error": "invalid_feedback_type", "valid_feedback_types": sorted(VALID_FEEDBACK_TYPES)}
    engine = create_engine_and_tables()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        finding = session.get(AiFinding, finding_id)
        if not finding:
            return {"ok": False, "error": "finding_not_found", "finding_id": finding_id}
        row = AiFindingFeedback(
            finding_id=finding_id,
            feedback_type=feedback_type,
            actual_root_cause=feedback.get("actual_root_cause"),
            action_taken=feedback.get("action_taken"),
            operator=feedback.get("operator"),
            comment=feedback.get("comment"),
        )
        session.add(row)
        finding.lifecycle_status = FEEDBACK_LIFECYCLE.get(feedback_type, finding.lifecycle_status)
        session.flush()
        return {"ok": True, "feedback_id": row.id, "finding_id": finding_id, "lifecycle_status": finding.lifecycle_status}


def compact_memory_row(row: dict) -> dict:
    return {
        "finding_id": row.get("finding_id"),
        "title": row.get("title"),
        "category": row.get("category"),
        "severity": row.get("severity"),
        "confidence": row.get("confidence"),
        "lifecycle_status": row.get("lifecycle_status"),
        "actual_root_cause": row.get("actual_root_cause"),
        "action_taken": row.get("action_taken"),
        "feedback_type": row.get("feedback_type"),
        "created_at": str(row.get("created_at") or ""),
        "window_start": str(row.get("window_start") or ""),
        "window_end": str(row.get("window_end") or ""),
    }


def candidate_event_types(candidate: dict) -> List[str]:
    values = candidate.get("event_types") or candidate.get("event_type") or []
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [str(item) for item in values if item]
    return []


def search_similar_findings(candidate: dict, limit: int = 5, days: int = 30, *, env_file: Optional[str] = None) -> List[dict]:
    load_env_file(env_file)
    engine = create_engine_and_tables()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, min(days, 365)))
    limit = max(1, min(int(limit or 5), 20))
    candidate = candidate or {}
    fingerprint = make_fingerprint(str(candidate.get("category") or ""), candidate)
    event_types = candidate_event_types(candidate)

    filters = [AiFinding.created_at >= since]
    should = [AiFinding.finding_fingerprint == fingerprint]
    for field in ["device_ip", "device_name", "object_key"]:
        value = candidate.get("managed_device_ip") if field == "device_ip" else candidate.get("managed_device_name") if field == "device_name" else candidate.get(field)
        if field == "device_ip" and candidate.get("device_identity_source") == "sender_fallback":
            value = None
        if value:
            should.append(getattr(AiFinding, field) == str(value))
    title = normalize_text(candidate.get("title") or candidate.get("event_type"))
    if title:
        should.append(AiFinding.title.like("%%%s%%" % title[:80]))

    stmt = (
        select(
            AiFinding.id.label("finding_id"),
            AiFinding.title,
            AiFinding.category,
            AiFinding.severity,
            AiFinding.confidence,
            AiFinding.lifecycle_status,
            AiFinding.created_at,
            AiAnalysisRun.window_start,
            AiAnalysisRun.window_end,
            AiFindingFeedback.feedback_type,
            AiFindingFeedback.actual_root_cause,
            AiFindingFeedback.action_taken,
        )
        .join(AiAnalysisRun, AiFinding.run_id == AiAnalysisRun.id)
        .outerjoin(AiFindingFeedback, AiFindingFeedback.finding_id == AiFinding.id)
        .where(and_(*filters, or_(*should)))
        .order_by(desc(AiFindingFeedback.created_at), desc(AiFinding.created_at))
        .limit(limit)
    )
    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(stmt).mappings().all()]
    if event_types and not rows:
        stmt = (
            select(
                AiFinding.id.label("finding_id"),
                AiFinding.title,
                AiFinding.category,
                AiFinding.severity,
                AiFinding.confidence,
                AiFinding.lifecycle_status,
                AiFinding.event_types,
                AiFinding.created_at,
                AiAnalysisRun.window_start,
                AiAnalysisRun.window_end,
                AiFindingFeedback.feedback_type,
                AiFindingFeedback.actual_root_cause,
                AiFindingFeedback.action_taken,
            )
            .join(AiAnalysisRun, AiFinding.run_id == AiAnalysisRun.id)
            .outerjoin(AiFindingFeedback, AiFindingFeedback.finding_id == AiFinding.id)
            .where(AiFinding.created_at >= since)
            .order_by(desc(AiFindingFeedback.created_at), desc(AiFinding.created_at))
            .limit(limit * 4)
        )
        with engine.connect() as conn:
            candidates = [dict(row) for row in conn.execute(stmt).mappings().all()]
        rows = [row for row in candidates if any(event_type in stable_json(row.get("event_types") or []) for event_type in event_types)][:limit]
    return [compact_memory_row(row) for row in rows]


def build_ai_memory_context(candidates: List[dict], limit: int = 10, *, env_file: Optional[str] = None) -> dict:
    rows: List[dict] = []
    seen = set()
    per_candidate_limit = max(1, min(5, limit))
    for candidate in candidates[: max(1, limit)]:
        for row in search_similar_findings(candidate, limit=per_candidate_limit, env_file=env_file):
            key = row.get("finding_id")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    return {
        "enabled": True,
        "records": rows,
        "notes": [] if rows else ["no historical ai findings"],
    }
