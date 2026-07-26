"""Authentication endpoints and access-control helpers."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional

from flask import Blueprint, current_app, g, jsonify, request, session

from app.models import User
from app.platform_auth import PlatformAuthError, sync_platform_user, verify_platform_request


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def db_session_factory():
    return current_app.extensions["session_factory"]


def user_payload(user: User) -> dict[str, Any]:
    payload = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "email": user.email,
        "is_active": user.is_active,
    }
    identity = getattr(user, "platform_identity", None)
    if identity:
        payload["identity_source"] = "netops"
        payload["external_subject"] = identity.subject
        payload["role_code"] = identity.role_code
        payload["org_id"] = identity.org_id
        payload["org_name"] = identity.org_name
        payload["regions"] = None if identity.regions is None else list(identity.regions)
        payload["permissions"] = sorted(identity.permissions)
    return payload


def current_user_id() -> Optional[int]:
    cached = getattr(g, "_aiops_current_user", None)
    if cached is not None:
        return int(cached.id)
    return None


def load_current_user() -> Optional[User]:
    cached = getattr(g, "_aiops_current_user", None)
    if cached is not None:
        return cached
    identity = verify_platform_request(request)
    if identity is not None:
        forwarded_for = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        user = sync_platform_user(
            db_session_factory(),
            identity,
            request_id=request.headers.get("X-Request-ID"),
            client_ip=forwarded_for or request.remote_addr,
        )
        g._aiops_current_user = user
        return user
    return None


def error_response(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status


def login_required(func: Callable):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            user = load_current_user()
        except PlatformAuthError as exc:
            return error_response(str(exc), 401 if "permission" not in str(exc) else 403)
        if not user:
            return error_response("authentication required", 401)
        return func(*args, current_user=user, **kwargs)

    return wrapper


def admin_required(func: Callable):
    @wraps(func)
    @login_required
    def wrapper(*args, current_user: User, **kwargs):
        if current_user.role != "admin":
            return error_response("admin role required", 403)
        return func(*args, current_user=current_user, **kwargs)

    return wrapper


@auth_bp.post("/register")
def register():
    return error_response("local account registration was removed; use the network platform identity", 410)


@auth_bp.post("/login")
def login():
    return error_response("local login was removed; enter AIOps from the network platform", 410)


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.get("/me")
@login_required
def me(current_user: User):
    return jsonify({"ok": True, "user": user_payload(current_user)})
