"""AI analysis rule management APIs."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import delete, desc, select

from aiops.rules.analysis_rules import parse_ai_rule, rule_to_payload
from app.api.auth import admin_required, db_session_factory, login_required
from app.db import Base, create_db_engine, session_scope
from app.models import AiAnalysisRule, AiAnalysisRuleHit, AuditLog


analysis_rules_bp = Blueprint("analysis_rules", __name__, url_prefix="/api")


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def ensure_rule_tables() -> None:
    Base.metadata.create_all(create_db_engine())


def rule_values(payload: dict[str, Any], current_user, existing: AiAnalysisRule | None = None) -> tuple[dict, dict | None]:
    raw_text = str(payload.get("raw_text") or (existing.raw_text if existing else "")).strip()
    if not raw_text:
        return {}, {"error": "raw_text_required"}
    try:
        parsed = parse_ai_rule(raw_text)
    except ValueError as exc:
        return {}, {"error": str(exc)}
    rule_name = str(payload.get("rule_name") or (existing.rule_name if existing else "") or raw_text[:32]).strip()
    enabled = bool(payload.get("enabled", existing.enabled if existing else True))
    if parsed.get("requires_confirmation"):
        enabled = False
    values = {
        "rule_name": rule_name[:128],
        "raw_text": raw_text,
        "rule_type": parsed["rule_type"],
        "action": parsed["action"],
        "target_event_families": parsed["target_event_families"],
        "target_keywords": parsed["target_keywords"],
        "target_devices": parsed["target_devices"],
        "target_objects": parsed["target_objects"],
        "parsed_rule": parsed,
        "priority": int(payload.get("priority", parsed["priority"])),
        "enabled": enabled,
        "scope": str(payload.get("scope") or parsed.get("scope") or "global")[:64],
        "created_by": existing.created_by if existing else current_user.username,
    }
    return values, None


@analysis_rules_bp.post("/ai-analysis-rules/parse")
@login_required
def parse_rule(current_user):
    payload = request.get_json(silent=True) or {}
    raw_text = str(payload.get("raw_text") or "").strip()
    if not raw_text:
        return json_error("raw_text_required", 400)
    try:
        parsed = parse_ai_rule(raw_text)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({"ok": True, "parsed_rule": parsed})


@analysis_rules_bp.get("/ai-analysis-rules")
@login_required
def list_rules(current_user):
    ensure_rule_tables()
    with session_scope(db_session_factory()) as session:
        rows = session.execute(select(AiAnalysisRule).order_by(desc(AiAnalysisRule.enabled), desc(AiAnalysisRule.priority), desc(AiAnalysisRule.updated_at))).scalars().all()
        return jsonify({"ok": True, "items": [rule_to_payload(row) for row in rows]})


@analysis_rules_bp.post("/ai-analysis-rules")
@admin_required
def create_rule(current_user):
    ensure_rule_tables()
    payload = request.get_json(silent=True) or {}
    values, error = rule_values(payload, current_user)
    if error:
        return json_error(error["error"], 400)
    with session_scope(db_session_factory()) as session:
        row = AiAnalysisRule(**values)
        session.add(row)
        session.flush()
        session.add(AuditLog(actor=current_user.username, action="create_ai_analysis_rule", resource_type="ai_analysis_rules", resource_id=str(row.id), detail={"raw_text": row.raw_text}))
        return jsonify({"ok": True, "item": rule_to_payload(row)}), 201


@analysis_rules_bp.put("/ai-analysis-rules/<int:rule_id>")
@admin_required
def update_rule(rule_id: int, current_user):
    ensure_rule_tables()
    payload = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        row = session.get(AiAnalysisRule, rule_id)
        if not row:
            return json_error("rule_not_found", 404)
        values, error = rule_values(payload, current_user, row)
        if error:
            return json_error(error["error"], 400)
        for key, value in values.items():
            setattr(row, key, value)
        session.add(AuditLog(actor=current_user.username, action="update_ai_analysis_rule", resource_type="ai_analysis_rules", resource_id=str(row.id), detail={"raw_text": row.raw_text}))
        return jsonify({"ok": True, "item": rule_to_payload(row)})


@analysis_rules_bp.post("/ai-analysis-rules/<int:rule_id>/toggle")
@admin_required
def toggle_rule(rule_id: int, current_user):
    ensure_rule_tables()
    payload = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        row = session.get(AiAnalysisRule, rule_id)
        if not row:
            return json_error("rule_not_found", 404)
        row.enabled = bool(payload.get("enabled", not row.enabled))
        session.add(AuditLog(actor=current_user.username, action="toggle_ai_analysis_rule", resource_type="ai_analysis_rules", resource_id=str(row.id), detail={"enabled": row.enabled}))
        return jsonify({"ok": True, "item": rule_to_payload(row)})


@analysis_rules_bp.delete("/ai-analysis-rules/<int:rule_id>")
@admin_required
def delete_rule(rule_id: int, current_user):
    ensure_rule_tables()
    with session_scope(db_session_factory()) as session:
        row = session.get(AiAnalysisRule, rule_id)
        if not row:
            return json_error("rule_not_found", 404)
        session.add(AuditLog(actor=current_user.username, action="delete_ai_analysis_rule", resource_type="ai_analysis_rules", resource_id=str(row.id), detail={"raw_text": row.raw_text}))
        session.execute(delete(AiAnalysisRuleHit).where(AiAnalysisRuleHit.rule_id == rule_id))
        session.delete(row)
        return jsonify({"ok": True, "deleted": rule_id})
