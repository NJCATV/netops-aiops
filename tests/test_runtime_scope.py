from __future__ import annotations

from types import SimpleNamespace

from flask import Flask
from app.api.runtime import platform_region_filter
from app.platform_auth import PlatformIdentity


def make_user(regions):
    return SimpleNamespace(
        platform_identity=PlatformIdentity(
            subject="1",
            username="tester",
            display_name="Tester",
            role_code="normal_user",
            user_type="internal",
            org_id=1,
            org_name="Org",
            regions=regions,
            permissions=frozenset({"netops.aiops.view"}),
        )
    )


def test_empty_region_scope_is_ignored_for_global_aiops_data():
    app = Flask(__name__)
    with app.app_context():
        assert platform_region_filter(make_user(()), ["device_ip"]) is None


def test_region_scope_is_ignored_for_global_aiops_data():
    app = Flask(__name__)
    with app.app_context():
        result = platform_region_filter(make_user(("jiangning",)), ["device_ip", "managed_device_ip"])
    assert result is None
