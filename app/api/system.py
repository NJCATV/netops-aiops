"""Lightweight system management APIs."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import desc, func, select
from werkzeug.security import generate_password_hash

from app.api.auth import admin_required, db_session_factory, login_required, user_payload
from app.db import session_scope
from app.models import AiChatMessage, AiChatSession, AppSetting, AuditLog, PlatformIdentityAudit, User


system_bp = Blueprint("system", __name__, url_prefix="/api/system")


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status


def parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def parse_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(number, max_value))


def serialize_user(row: User) -> dict:
    payload = user_payload(row)
    payload.update(
        {
            "created_at": row.created_at.isoformat().replace("+00:00", "Z") if row.created_at else None,
            "updated_at": row.updated_at.isoformat().replace("+00:00", "Z") if row.updated_at else None,
            "last_login_at": row.last_login_at.isoformat().replace("+00:00", "Z") if row.last_login_at else None,
        }
    )
    return payload


@system_bp.get("/users")
@login_required
def list_users(current_user):
    with session_scope(db_session_factory()) as session:
        rows = session.execute(select(User).order_by(desc(User.created_at))).scalars().all()
        return jsonify({"ok": True, "items": [serialize_user(row) for row in rows]})


@system_bp.post("/users")
@admin_required
def create_user(current_user):
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not username:
        return json_error("username_required")
    if len(password) < 8:
        return json_error("password_min_length_8")
    role = str(payload.get("role") or "viewer").strip().lower()
    if role not in {"admin", "viewer"}:
        return json_error("invalid_role")
    with session_scope(db_session_factory()) as session:
        existing = session.query(User).filter(func.lower(User.username) == username.lower()).one_or_none()
        if existing:
            return json_error("username_exists", 409)
        row = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            display_name=str(payload.get("display_name") or "").strip() or None,
            email=str(payload.get("email") or "").strip() or None,
            is_active=parse_bool(payload.get("is_active"), True),
        )
        session.add(row)
        session.flush()
        return jsonify({"ok": True, "item": serialize_user(row)}), 201


@system_bp.put("/users/<int:user_id>")
@admin_required
def update_user(user_id: int, current_user):
    payload = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        row = session.get(User, user_id)
        if not row:
            return json_error("user_not_found", 404)
        if "display_name" in payload:
            row.display_name = str(payload.get("display_name") or "").strip() or None
        if "email" in payload:
            row.email = str(payload.get("email") or "").strip() or None
        if "role" in payload:
            role = str(payload.get("role") or "").strip().lower()
            if role not in {"admin", "viewer"}:
                return json_error("invalid_role")
            row.role = role
        if "is_active" in payload:
            row.is_active = parse_bool(payload.get("is_active"), row.is_active)
        if payload.get("password"):
            password = str(payload.get("password") or "")
            if len(password) < 8:
                return json_error("password_min_length_8")
            row.password_hash = generate_password_hash(password)
        return jsonify({"ok": True, "item": serialize_user(row)})


@system_bp.post("/users/<int:user_id>/toggle")
@admin_required
def toggle_user(user_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        row = session.get(User, user_id)
        if not row:
            return json_error("user_not_found", 404)
        if row.id == current_user.id and row.is_active:
            return json_error("cannot_disable_self")
        row.is_active = not row.is_active
        return jsonify({"ok": True, "item": serialize_user(row)})


@system_bp.delete("/users/<int:user_id>")
@admin_required
def delete_user(user_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        row = session.get(User, user_id)
        if not row:
            return json_error("user_not_found", 404)
        if row.id == current_user.id:
            return json_error("cannot_delete_self")
        session.query(AiChatMessage).filter(AiChatMessage.user_id == row.id).delete(synchronize_session=False)
        session.query(AiChatSession).filter(AiChatSession.user_id == row.id).delete(synchronize_session=False)
        session.delete(row)
        return jsonify({"ok": True, "deleted": user_id})


@system_bp.get("/settings")
@login_required
def get_settings(current_user):
    defaults = {
        "platform_name": "JSCN AIOps",
        "default_analysis_window": "24",
        "default_refresh_interval": "30",
        "ai_model_name": "",
        "data_retention_days": "30",
        "auto_refresh_enabled": "true",
        "analysis_done_notify_enabled": "false",
    }
    with session_scope(db_session_factory()) as session:
        rows = session.execute(select(AppSetting)).scalars().all()
        values = dict(defaults)
        values.update({row.setting_key: row.setting_value for row in rows})
        return jsonify({"ok": True, "item": values})


@system_bp.put("/settings")
@admin_required
def update_settings(current_user):
    payload = request.get_json(silent=True) or {}
    allowed = {
        "platform_name",
        "default_analysis_window",
        "default_refresh_interval",
        "ai_model_name",
        "data_retention_days",
        "auto_refresh_enabled",
        "analysis_done_notify_enabled",
    }
    with session_scope(db_session_factory()) as session:
        for key, value in payload.items():
            if key not in allowed:
                continue
            row = session.execute(select(AppSetting).where(AppSetting.setting_key == key)).scalar_one_or_none()
            if not row:
                row = AppSetting(setting_key=key, value_type="string")
                session.add(row)
            row.setting_value = str(value)
        return jsonify({"ok": True})


@system_bp.get("/operation-logs")
@login_required
def operation_logs(current_user):
    limit = parse_int(request.args.get("limit"), 50, 1, 200)
    with session_scope(db_session_factory()) as session:
        rows = session.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)).scalars().all()
        items = [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "client_ip": row.client_ip,
                "detail": row.detail,
                "created_at": row.created_at.isoformat().replace("+00:00", "Z") if row.created_at else None,
            }
            for row in rows
        ]
        return jsonify({"ok": True, "items": items})



def qq_audit_log_path() -> str:
    return os.getenv("QQ_AUDIT_LOG_PATH", "/data/jscn-aiops/qq-audit/qq_adapter_audit.jsonl")


def qq_bot_status_path() -> str:
    return os.getenv("QQ_BOT_STATUS_PATH", "/data/jscn-aiops/qq-audit/qq_bot_status.json")


def qq_adapter_internal(path: str) -> dict | None:
    base_url = os.getenv("QQ_ADAPTER_INTERNAL_URL", "").rstrip("/")
    token = os.getenv("QQ_ADAPTER_ADMIN_TOKEN", "")
    if not base_url or not token:
        return None
    req = urllib.request.Request(
        base_url + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_qq_bot_status() -> dict[str, Any]:
    remote = qq_adapter_internal("/internal/status")
    if remote and isinstance(remote.get("item"), dict):
        status = remote["item"]
        return {
            "known": True,
            "ts": status.get("ts"),
            "online": bool(status.get("online")),
            "good": bool(status.get("good")),
            "onebot_ok": bool(status.get("onebot_ok")),
            "status": "online" if status.get("online") else "offline",
            "login_url": status.get("login_url") or "",
            "email_enabled": bool(status.get("email_enabled")),
            "error": status.get("error") or status.get("napcat_login_error") or "",
            "napcat_login": status.get("napcat_login") if isinstance(status.get("napcat_login"), dict) else {},
        }
    path = qq_bot_status_path()
    if not path or not os.path.exists(path):
        return {
            "online": False,
            "known": False,
            "status": "unknown",
            "message": "QQ bot status has not been reported yet.",
            "login_url": os.getenv("NAPCAT_WEBUI_PUBLIC_URL", "").rstrip("/") + "/webui/QQLogin.html" if os.getenv("NAPCAT_WEBUI_PUBLIC_URL") else "",
        }
    try:
        with open(path, "r", encoding="utf-8") as handle:
            status = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"online": False, "known": False, "status": "unknown", "message": "QQ bot status file is unreadable."}
    if not isinstance(status, dict):
        return {"online": False, "known": False, "status": "unknown"}
    public_status = {
        "known": True,
        "ts": status.get("ts"),
        "online": bool(status.get("online")),
        "good": bool(status.get("good")),
        "onebot_ok": bool(status.get("onebot_ok")),
        "status": "online" if status.get("online") else "offline",
        "login_url": status.get("login_url") or "",
        "email_enabled": bool(status.get("email_enabled")),
        "error": status.get("error") or status.get("napcat_login_error") or "",
        "napcat_login": status.get("napcat_login") if isinstance(status.get("napcat_login"), dict) else {},
    }
    return public_status


@system_bp.get("/qq-bot-status")
@login_required
def qq_bot_status(current_user):
    return jsonify({"ok": True, "item": read_qq_bot_status()})


def read_qq_audit_records(limit: int, max_scan: int = 5000) -> list[dict[str, Any]]:
    remote = qq_adapter_internal(f"/internal/audit?limit={min(max(limit, 1), 500)}")
    if remote and isinstance(remote.get("items"), list):
        return [item for item in remote["items"] if isinstance(item, dict)][:limit]
    path = qq_audit_log_path()
    if not path or not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            buffer = bytearray()
            while position > 0 and len(records) < max_scan:
                read_size = min(8192, position)
                position -= read_size
                handle.seek(position)
                buffer[:0] = handle.read(read_size)
                while b"\n" in buffer and len(records) < max_scan:
                    line, _, rest = buffer.rpartition(b"\n")
                    buffer = bytearray(line)
                    text = rest.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        record = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        records.append(record)
            if buffer and len(records) < max_scan:
                try:
                    record = json.loads(buffer.decode("utf-8", errors="replace").strip())
                    if isinstance(record, dict):
                        records.append(record)
                except json.JSONDecodeError:
                    pass
    except OSError:
        return []
    return records[:limit]


def serialize_qq_audit_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": record.get("id") or f"qq-audit-{index}",
        "ts": record.get("ts"),
        "event": record.get("event"),
        "status": record.get("status") or record.get("reason") or record.get("event"),
        "reason": record.get("reason"),
        "group_id": record.get("group_id"),
        "user_id": record.get("user_id"),
        "message_id": record.get("message_id"),
        "sender_nickname": record.get("sender_nickname"),
        "sender_card": record.get("sender_card"),
        "question": record.get("question"),
        "answer_preview": record.get("answer_preview"),
        "answer_chars": record.get("answer_chars"),
        "reply_chunks": record.get("reply_chunks"),
        "duration_ms": record.get("duration_ms"),
        "queue_size": record.get("queue_size"),
        "error": record.get("error"),
        "session_id": record.get("session_id"),
    }


@system_bp.get("/qq-audit-logs")
@login_required
def qq_audit_logs(current_user):
    limit = parse_int(request.args.get("limit"), 100, 1, 500)
    event_filter = str(request.args.get("event") or "").strip()
    group_filter = str(request.args.get("group_id") or "").strip()
    user_filter = str(request.args.get("user_id") or "").strip()
    q = str(request.args.get("q") or "").strip().lower()
    records = read_qq_audit_records(limit=500, max_scan=5000)
    filtered: list[dict[str, Any]] = []
    for record in records:
        if event_filter and str(record.get("event") or "") != event_filter:
            continue
        if group_filter and str(record.get("group_id") or "") != group_filter:
            continue
        if user_filter and str(record.get("user_id") or "") != user_filter:
            continue
        if q:
            haystack = " ".join(str(record.get(key) or "") for key in ("question", "answer_preview", "sender_nickname", "sender_card", "reason", "error")).lower()
            if q not in haystack:
                continue
        filtered.append(record)
        if len(filtered) >= limit:
            break
    summary_source = records[:500]
    events = Counter(str(item.get("event") or "unknown") for item in summary_source)
    groups = Counter(str(item.get("group_id") or "unknown") for item in summary_source)
    users = Counter(str(item.get("user_id") or "unknown") for item in summary_source)
    summary = {
        "scanned": len(summary_source),
        "matched": len(filtered),
        "events": dict(events.most_common(10)),
        "top_groups": [{"group_id": key, "count": count} for key, count in groups.most_common(10)],
        "top_users": [{"user_id": key, "count": count} for key, count in users.most_common(10)],
        "log_path": qq_audit_log_path(),
    }
    return jsonify({"ok": True, "items": [serialize_qq_audit_record(row, index) for index, row in enumerate(filtered)], "summary": summary})
@system_bp.get("/login-logs")
@login_required
def login_logs(current_user):
    limit = parse_int(request.args.get("limit"), 100, 1, 500)
    with session_scope(db_session_factory()) as session:
        rows = session.execute(
            select(PlatformIdentityAudit).order_by(desc(PlatformIdentityAudit.authenticated_at)).limit(limit)
        ).scalars().all()
        items = [
            {
                "id": row.id,
                "username": row.username,
                "status": "accepted",
                "client_ip": row.client_ip,
                "request_id": row.request_id,
                "role_code": row.role_code,
                "org_id": row.org_id,
                "org_name": row.org_name,
                "reason": f"统一身份认证 · {row.role_code or '-'} · {row.org_name or '未分配组织'}",
                "created_at": row.authenticated_at.isoformat().replace("+00:00", "Z") if row.authenticated_at else None,
            }
            for row in rows
        ]
    return jsonify({"ok": True, "items": items})
