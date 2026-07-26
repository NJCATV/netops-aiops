from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from flask import Flask, request
from sqlalchemy import create_engine, select

from app.db import Base, make_session_factory
from app.models import User
from app.platform_auth import PlatformAuthError, PlatformIdentity, permission_for_request, sync_platform_user, verify_platform_request


def signed_headers(secret: str, *, path: str = "/runtime/overview", method: str = "GET", permissions=None, regions=None):
    identity = {
        "subject": "42",
        "username": "oss-42",
        "display_name": "测试用户",
        "role_code": "normal_user",
        "user_type": "internal",
        "org_id": 7,
        "org_name": "测试组织",
        "regions": regions,
        "permissions": permissions or ["netops.aiops.view"],
    }
    identity_json = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    timestamp = str(int(time.time()))
    nonce = hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:24]
    canonical = "\n".join(
        [timestamp, nonce, method, path, hashlib.sha256(b"").hexdigest(), hashlib.sha256(identity_json.encode()).hexdigest()]
    )
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-AIOps-Identity": base64.urlsafe_b64encode(identity_json.encode()).decode(),
        "X-AIOps-Timestamp": timestamp,
        "X-AIOps-Nonce": nonce,
        "X-AIOps-Signature": signature,
    }


def test_platform_identity_signature(monkeypatch):
    secret = "test-shared-secret"
    monkeypatch.setenv("AIOPS_INTERNAL_SHARED_SECRET", secret)
    app = Flask(__name__)
    with app.test_request_context("/api/runtime/overview", headers=signed_headers(secret)):
        identity = verify_platform_request(request)
    assert identity is not None
    assert identity.subject == "42"
    assert identity.regions is None
    assert "netops.aiops.view" in identity.permissions


def test_platform_identity_rejects_tampering(monkeypatch):
    secret = "test-shared-secret"
    monkeypatch.setenv("AIOPS_INTERNAL_SHARED_SECRET", secret)
    headers = signed_headers(secret)
    headers["X-AIOps-Signature"] = "0" * 64
    app = Flask(__name__)
    with app.test_request_context("/api/runtime/overview", headers=headers):
        with pytest.raises(PlatformAuthError, match="signature"):
            verify_platform_request(request)


def test_platform_identity_enforces_route_permission(monkeypatch):
    secret = "test-shared-secret"
    monkeypatch.setenv("AIOPS_INTERNAL_SHARED_SECRET", secret)
    headers = signed_headers(secret, path="/ai-runs", method="POST", permissions=["netops.aiops.view"])
    app = Flask(__name__)
    with app.test_request_context("/api/ai-runs", method="POST", headers=headers):
        with pytest.raises(PlatformAuthError, match="permission"):
            verify_platform_request(request)


@pytest.mark.parametrize(
    ("path", "method", "permission"),
    [
        ("/ai-analysis-rules", "POST", "netops.aiops.rules.manage"),
        ("/llm/providers", "GET", "netops.aiops.models.manage"),
        ("/llm/models/12/test", "POST", "netops.aiops.models.manage"),
        ("/system/operation-logs", "GET", "netops.aiops.audit.view"),
        ("/system/qq-audit-logs", "GET", "netops.aiops.audit.view"),
        ("/fault-kb/chat/logs", "GET", "netops.aiops.audit.view"),
        ("/system/settings", "PUT", "netops.aiops.models.manage"),
        ("/findings/22/feedback", "POST", "netops.aiops.analysis.run"),
        ("/unclassified-admin-route", "DELETE", "netops.aiops.models.manage"),
    ],
)
def test_management_route_permissions(path, method, permission):
    assert permission_for_request(path, method) == permission


def test_empty_region_scope_is_preserved(monkeypatch):
    secret = "test-shared-secret"
    monkeypatch.setenv("AIOPS_INTERNAL_SHARED_SECRET", secret)
    app = Flask(__name__)
    with app.test_request_context("/api/runtime/overview", headers=signed_headers(secret, regions=[])):
        identity = verify_platform_request(request)
    assert identity is not None
    assert identity.regions == ()


def test_platform_user_projection_is_stable():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    identity = PlatformIdentity(
        subject="9001",
        username="oss-9001",
        display_name="平台用户",
        role_code="org_admin",
        user_type="internal",
        org_id=12,
        org_name="测试分公司",
        regions=("jiangning",),
        permissions=frozenset({"netops.aiops.view"}),
    )
    first = sync_platform_user(factory, identity)
    second = sync_platform_user(factory, identity)
    assert first.id == second.id
    with factory() as db:
        users = db.execute(select(User).where(User.identity_source == "netops")).scalars().all()
    assert len(users) == 1
    assert users[0].external_subject == "9001"
    assert users[0].external_org_id == 12
