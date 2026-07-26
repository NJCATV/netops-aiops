from __future__ import annotations

import json

from app.api import system


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_internal_bridge_sends_admin_token(monkeypatch):
    captured = {}
    monkeypatch.setenv("QQ_ADAPTER_INTERNAL_URL", "http://172.25.60.20:18088")
    monkeypatch.setenv("QQ_ADAPTER_ADMIN_TOKEN", "bridge-secret")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse({"ok": True, "item": {"online": True}})

    monkeypatch.setattr(system.urllib.request, "urlopen", fake_urlopen)
    payload = system.qq_adapter_internal("/internal/status")
    assert payload == {"ok": True, "item": {"online": True}}
    assert captured == {
        "url": "http://172.25.60.20:18088/internal/status",
        "authorization": "Bearer bridge-secret",
        "timeout": 8,
    }


def test_remote_status_is_preferred_over_local_file(monkeypatch):
    monkeypatch.setattr(system, "qq_adapter_internal", lambda path: {"ok": True, "item": {"online": True, "good": True, "onebot_ok": True, "ts": "now"}})
    status = system.read_qq_bot_status()
    assert status["online"] is True
    assert status["onebot_ok"] is True


def test_remote_audit_records_are_bounded(monkeypatch):
    monkeypatch.setattr(system, "qq_adapter_internal", lambda path: {"ok": True, "items": [{"id": 1}, {"id": 2}, {"id": 3}]})
    assert system.read_qq_audit_records(2) == [{"id": 1}, {"id": 2}]
