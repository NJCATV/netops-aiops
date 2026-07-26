"""Trusted identity envelope used by the embedded network-operations platform."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from flask import Request
from sqlalchemy import select

from app.db import session_scope
from app.models import PlatformIdentityAudit, User, utc_now


class PlatformAuthError(ValueError):
    pass


@dataclass(frozen=True)
class PlatformIdentity:
    subject: str
    username: str
    display_name: Optional[str]
    role_code: str
    user_type: str
    org_id: Optional[int]
    org_name: Optional[str]
    regions: Optional[tuple[str, ...]]
    permissions: frozenset[str]


_nonce_lock = threading.Lock()
_seen_nonces: dict[str, int] = {}


def _decode_identity(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlatformAuthError("invalid platform identity envelope") from exc
    if not isinstance(payload, dict):
        raise PlatformAuthError("invalid platform identity payload")
    return payload


def _canonical_path(request: Request) -> str:
    path = request.path or "/"
    return path[4:] if path.startswith("/api/") else path


def _check_nonce(nonce: str, timestamp: int, max_skew: int) -> None:
    now = int(time.time())
    with _nonce_lock:
        expired = [key for key, seen_at in _seen_nonces.items() if now - seen_at > max_skew]
        for key in expired:
            _seen_nonces.pop(key, None)
        if nonce in _seen_nonces:
            raise PlatformAuthError("replayed platform identity envelope")
        _seen_nonces[nonce] = timestamp


def permission_for_request(path: str, method: str) -> str:
    normalized = "/" + str(path or "").strip("/")
    if normalized.startswith((
        "/fault-kb/chat/logs",
        "/system/operation-logs",
        "/system/qq-audit-logs",
        "/system/login-logs",
    )):
        return "netops.aiops.audit.view"
    if normalized.startswith("/fault-kb/chat"):
        return "netops.ai_chat.use"
    if normalized.startswith(("/llm/providers", "/llm/models", "/llm/usage-bindings", "/llm/usage-keys")):
        return "netops.aiops.models.manage"
    if normalized.startswith("/system/settings") and method != "GET":
        return "netops.aiops.models.manage"
    if normalized.startswith("/report-tasks"):
        return "netops.aiops.tasks.manage" if method != "GET" else "netops.aiops.analysis.view"
    if normalized.startswith("/ai-analysis-rules"):
        return "netops.aiops.rules.manage" if method != "GET" else "netops.aiops.analysis.view"
    if normalized.startswith("/fault-kb") and method != "GET":
        return "netops.aiops.kb.manage"
    if normalized == "/ai-runs" and method == "POST":
        return "netops.aiops.analysis.run"
    if normalized.startswith("/findings/") and normalized.endswith("/feedback") and method == "POST":
        return "netops.aiops.analysis.run"
    if normalized.startswith(("/syslog", "/trap")):
        return "netops.aiops.logs.view"
    if normalized.startswith("/alarm-events"):
        return "netops.aiops.events.view"
    return "netops.aiops.models.manage" if method != "GET" else "netops.aiops.view"


def verify_platform_request(request: Request) -> Optional[PlatformIdentity]:
    identity_header = request.headers.get("X-AIOps-Identity")
    signature = request.headers.get("X-AIOps-Signature")
    if not identity_header and not signature:
        return None
    if not identity_header or not signature:
        raise PlatformAuthError("incomplete platform identity headers")

    secret = os.getenv("AIOPS_INTERNAL_SHARED_SECRET", "")
    if not secret:
        raise PlatformAuthError("platform identity authentication is not configured")
    timestamp_text = request.headers.get("X-AIOps-Timestamp", "")
    nonce = request.headers.get("X-AIOps-Nonce", "")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise PlatformAuthError("invalid platform identity timestamp") from exc
    max_skew = int(os.getenv("AIOPS_INTERNAL_MAX_SKEW_SECONDS", "90"))
    if abs(int(time.time()) - timestamp) > max_skew:
        raise PlatformAuthError("expired platform identity envelope")
    if len(nonce) < 16:
        raise PlatformAuthError("invalid platform identity nonce")

    raw_identity = _decode_identity(identity_header)
    identity_json = json.dumps(raw_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body = request.get_data(cache=True) or b""
    canonical = "\n".join(
        [
            timestamp_text,
            nonce,
            request.method.upper(),
            _canonical_path(request),
            hashlib.sha256(body).hexdigest(),
            hashlib.sha256(identity_json.encode("utf-8")).hexdigest(),
        ]
    )
    expected = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PlatformAuthError("invalid platform identity signature")

    subject = str(raw_identity.get("subject") or "").strip()
    username = str(raw_identity.get("username") or subject).strip()
    if not subject or not username:
        raise PlatformAuthError("platform identity subject is required")
    raw_permissions = raw_identity.get("permissions")
    if not isinstance(raw_permissions, list) or not all(isinstance(item, str) for item in raw_permissions):
        raise PlatformAuthError("invalid platform permission set")
    raw_regions = raw_identity.get("regions")
    if raw_regions is not None and (not isinstance(raw_regions, list) or not all(isinstance(item, str) for item in raw_regions)):
        raise PlatformAuthError("invalid platform region scope")
    required = permission_for_request(_canonical_path(request), request.method.upper())
    permissions = frozenset(raw_permissions)
    if required not in permissions:
        raise PlatformAuthError(f"missing platform permission: {required}")

    _check_nonce(nonce, timestamp, max_skew)
    org_id = raw_identity.get("org_id")
    try:
        org_id = int(org_id) if org_id is not None else None
    except (TypeError, ValueError) as exc:
        raise PlatformAuthError("invalid platform organization") from exc
    return PlatformIdentity(
        subject=subject,
        username=username[:64],
        display_name=(str(raw_identity.get("display_name") or "").strip() or None),
        role_code=str(raw_identity.get("role_code") or "normal_user"),
        user_type=str(raw_identity.get("user_type") or "internal"),
        org_id=org_id,
        org_name=(str(raw_identity.get("org_name") or "").strip() or None),
        regions=None if raw_regions is None else tuple(raw_regions),
        permissions=permissions,
    )


def sync_platform_user(
    session_factory,
    identity: PlatformIdentity,
    *,
    request_id: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> User:
    """Create or refresh a local identity projection while retaining stable FKs."""
    with session_scope(session_factory) as db:
        user = db.execute(
            select(User).where(User.identity_source == "netops", User.external_subject == identity.subject)
        ).scalar_one_or_none()
        if user is None:
            projected_username = f"netops:{identity.subject}"[:64]
            user = User(
                username=projected_username,
                password_hash="!platform-managed",
                role="admin" if identity.role_code in {"super_admin", "org_admin"} else "viewer",
                display_name=identity.display_name or identity.username,
                is_active=True,
                identity_source="netops",
                external_subject=identity.subject,
            )
            db.add(user)
            db.flush()
        user.display_name = identity.display_name or identity.username
        user.role = "admin" if identity.role_code in {"super_admin", "org_admin"} else "viewer"
        user.external_role_code = identity.role_code
        user.external_org_id = identity.org_id
        user.external_org_name = identity.org_name
        user.last_synced_at = utc_now()
        user.is_active = True
        db.flush()
        if request_id or client_ip:
            db.add(
                PlatformIdentityAudit(
                    aiops_user_id=user.id,
                    identity_source="netops",
                    external_subject=identity.subject,
                    username=identity.username,
                    role_code=identity.role_code,
                    org_id=identity.org_id,
                    org_name=identity.org_name,
                    regions_json=None if identity.regions is None else list(identity.regions),
                    permissions_json=sorted(identity.permissions),
                    request_id=(request_id or "")[:64] or None,
                    client_ip=(client_ip or "")[:64] or None,
                )
            )
        db.expunge(user)
    user.platform_identity = identity
    user.platform_permissions = identity.permissions
    user.platform_regions = identity.regions
    return user
