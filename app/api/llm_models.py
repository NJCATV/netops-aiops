"""LLM provider, model, and usage-binding management APIs."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import asc, desc, select

from app.api.auth import admin_required, db_session_factory, login_required
from app.db import session_scope
from app.models import AuditLog, LLMModel, LLMProvider, LLMUsageBinding, utc_now


llm_models_bp = Blueprint("llm_models", __name__, url_prefix="/api/llm")

USAGE_KEYS = {
    "aiops_scheduled_analysis": "AIOps 定时分析",
    "aiops_manual_analysis": "AIOps 手动分析",
    "fault_kb_qa": "AI问答助手",
    "vision_understanding": "图片理解",
    "embedding": "向量检索",
    "rerank": "重排序",
}


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status


def parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def parse_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def isoformat(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 10:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def provider_api_key(row: LLMProvider) -> str:
    if row.api_key:
        return row.api_key
    if row.api_key_env:
        for name in str(row.api_key_env).split(","):
            value = os.getenv(name.strip())
            if value:
                return value
    return ""


def serialize_provider(row: LLMProvider, model_count: int = 0) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "provider_type": row.provider_type,
        "base_url": row.base_url,
        "api_key": "",
        "api_key_masked": mask_secret(provider_api_key(row)),
        "api_key_env": row.api_key_env,
        "enabled": bool(row.enabled),
        "timeout_seconds": row.timeout_seconds,
        "capabilities": row.capabilities or {},
        "status": row.status,
        "last_checked_at": isoformat(row.last_checked_at),
        "last_error": row.last_error,
        "remark": row.remark,
        "model_count": model_count,
        "created_at": isoformat(row.created_at),
        "updated_at": isoformat(row.updated_at),
    }


def serialize_model(row: LLMModel, provider: Optional[LLMProvider] = None) -> dict:
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "provider_name": provider.name if provider else None,
        "provider_base_url": provider.base_url if provider else None,
        "model_id": row.model_id,
        "display_name": row.display_name or row.model_id,
        "endpoint_type": row.endpoint_type,
        "input_types": row.input_types or [],
        "output_types": row.output_types or [],
        "max_context_tokens": row.max_context_tokens,
        "max_input_size": row.max_input_size,
        "max_output_tokens": row.max_output_tokens,
        "supports_streaming": bool(row.supports_streaming),
        "supports_tools": bool(row.supports_tools),
        "enabled": bool(row.enabled),
        "status": row.status,
        "last_checked_at": isoformat(row.last_checked_at),
        "last_error": row.last_error,
        "raw_metadata": row.raw_metadata or {},
        "remark": row.remark,
        "created_at": isoformat(row.created_at),
        "updated_at": isoformat(row.updated_at),
    }


def serialize_binding(row: LLMUsageBinding, model: LLMModel, provider: LLMProvider) -> dict:
    return {
        "id": row.id,
        "usage_key": row.usage_key,
        "usage_label": USAGE_KEYS.get(row.usage_key, row.usage_key),
        "model_pk": model.id,
        "model_id": model.model_id,
        "display_name": model.display_name or model.model_id,
        "provider_id": provider.id,
        "provider_name": provider.name,
        "provider_base_url": provider.base_url,
        "endpoint_type": model.endpoint_type,
        "priority": row.priority,
        "enabled": bool(row.enabled),
        "purpose_note": row.purpose_note,
        "status": model.status,
        "updated_at": isoformat(row.updated_at),
    }


def normalize_base_url(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    if not text.endswith("/v1"):
        text = f"{text}/v1"
    return text


def provider_values(payload: dict[str, Any], existing: Optional[LLMProvider] = None) -> tuple[dict, Optional[str]]:
    name = str(payload.get("name") or (existing.name if existing else "")).strip()
    base_url = normalize_base_url(payload.get("base_url") or (existing.base_url if existing else ""))
    if not name:
        return {}, "provider_name_required"
    if not base_url:
        return {}, "base_url_required"
    values = {
        "name": name,
        "provider_type": str(payload.get("provider_type") or (existing.provider_type if existing else "openai_compatible")).strip(),
        "base_url": base_url,
        "api_key_env": str(payload.get("api_key_env") or (existing.api_key_env if existing else "")).strip() or None,
        "enabled": parse_bool(payload.get("enabled"), existing.enabled if existing else True),
        "timeout_seconds": parse_int(payload.get("timeout_seconds"), existing.timeout_seconds if existing else 60, 3, 600),
        "capabilities": payload.get("capabilities", existing.capabilities if existing else {}) or {},
        "remark": str(payload.get("remark") or "").strip() or None,
    }
    api_key = str(payload.get("api_key") or "").strip()
    if api_key:
        values["api_key"] = api_key
    return values, None


def model_values(payload: dict[str, Any], existing: Optional[LLMModel] = None) -> tuple[dict, Optional[str]]:
    model_id = str(payload.get("model_id") or (existing.model_id if existing else "")).strip()
    if not model_id:
        return {}, "model_id_required"
    values = {
        "model_id": model_id,
        "display_name": str(payload.get("display_name") or "").strip() or None,
        "endpoint_type": str(payload.get("endpoint_type") or (existing.endpoint_type if existing else "chat")).strip() or "chat",
        "input_types": payload.get("input_types", existing.input_types if existing else ["text"]) or [],
        "output_types": payload.get("output_types", existing.output_types if existing else ["text"]) or [],
        "max_context_tokens": payload.get("max_context_tokens"),
        "max_input_size": str(payload.get("max_input_size") or "").strip() or None,
        "max_output_tokens": payload.get("max_output_tokens"),
        "supports_streaming": parse_bool(payload.get("supports_streaming"), existing.supports_streaming if existing else False),
        "supports_tools": parse_bool(payload.get("supports_tools"), existing.supports_tools if existing else False),
        "enabled": parse_bool(payload.get("enabled"), existing.enabled if existing else True),
        "remark": str(payload.get("remark") or "").strip() or None,
    }
    for key in ("max_context_tokens", "max_output_tokens"):
        if values[key] in ("", None):
            values[key] = None
        else:
            values[key] = parse_int(values[key], 0, 0, 10000000) or None
    return values, None


def endpoint_from_metadata(item: dict[str, Any]) -> str:
    endpoint_types = item.get("supported_endpoint_types") or []
    if isinstance(endpoint_types, str):
        endpoint_types = [endpoint_types]
    lowered = {str(value).lower() for value in endpoint_types}
    if "embeddings" in lowered or "embedding" in lowered:
        return "embeddings"
    if "rerank" in lowered:
        return "rerank"
    return "chat"


def input_types_from_metadata(model_id: str, item: dict[str, Any], endpoint_type: str) -> list[str]:
    text = f"{model_id} {json.dumps(item, ensure_ascii=False)}".lower()
    if endpoint_type == "embeddings":
        return ["text"]
    if endpoint_type == "rerank":
        return ["text_pair"]
    if any(token in text for token in ("vl", "vision", "image", "minicpm-o", "qwen-vl")):
        return ["text", "image"]
    return ["text"]


def model_from_metadata(item: dict[str, Any]) -> dict:
    model_id = str(item.get("id") or "").strip()
    endpoint_type = endpoint_from_metadata(item)
    return {
        "model_id": model_id,
        "display_name": model_id,
        "endpoint_type": endpoint_type,
        "input_types": input_types_from_metadata(model_id, item, endpoint_type),
        "output_types": ["embedding"] if endpoint_type == "embeddings" else ["ranking"] if endpoint_type == "rerank" else ["text"],
        "max_context_tokens": item.get("max_model_len") or item.get("context_length"),
        "max_input_size": None,
        "max_output_tokens": None,
        "supports_streaming": endpoint_type == "chat",
        "supports_tools": False,
        "raw_metadata": item,
        "status": "listed",
        "last_error": None,
    }


def fetch_models(provider: LLMProvider) -> list[dict[str, Any]]:
    url = f"{provider.base_url.rstrip('/')}/models"
    headers = {"Content-Type": "application/json"}
    key = provider_api_key(provider)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=provider.timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("models_response_missing_data")
    return [item for item in data if isinstance(item, dict) and item.get("id")]


def test_model_call(provider: LLMProvider, model: LLMModel) -> tuple[bool, Optional[str]]:
    key = provider_api_key(provider)
    if not key:
        return False, "api_key_missing"
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=provider.base_url, timeout=min(provider.timeout_seconds, 60))
        start = time.monotonic()
        if model.endpoint_type == "embeddings":
            client.embeddings.create(model=model.model_id, input="测试")
        elif model.endpoint_type == "chat":
            client.chat.completions.create(model=model.model_id, messages=[{"role": "user", "content": "只回复 OK"}], temperature=0)
        else:
            return False, f"{model.endpoint_type}_test_not_implemented"
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return True, f"ok {elapsed_ms}ms"
    except Exception as exc:
        return False, str(exc)[:600]


def audit(session, current_user, action: str, resource_type: str, resource_id: str, detail: Optional[dict] = None) -> None:
    session.add(AuditLog(actor=current_user.username, action=action, resource_type=resource_type, resource_id=resource_id, detail=detail or {}))


@llm_models_bp.get("/usage-keys")
@login_required
def list_usage_keys(current_user):
    return jsonify({"ok": True, "items": [{"key": key, "label": label} for key, label in USAGE_KEYS.items()]})


@llm_models_bp.get("/providers")
@login_required
def list_providers(current_user):
    with session_scope(db_session_factory()) as session:
        rows = session.execute(select(LLMProvider).order_by(desc(LLMProvider.updated_at))).scalars().all()
        counts = {row.id: session.query(LLMModel).filter(LLMModel.provider_id == row.id).count() for row in rows}
        return jsonify({"ok": True, "items": [serialize_provider(row, counts.get(row.id, 0)) for row in rows]})


@llm_models_bp.post("/providers")
@admin_required
def create_provider(current_user):
    payload = request.get_json(silent=True) or {}
    values, error = provider_values(payload)
    if error:
        return json_error(error)
    with session_scope(db_session_factory()) as session:
        row = LLMProvider(**values)
        session.add(row)
        session.flush()
        audit(session, current_user, "create_llm_provider", "llm_provider", str(row.id), {"name": row.name})
        return jsonify({"ok": True, "item": serialize_provider(row)}), 201


@llm_models_bp.put("/providers/<int:provider_id>")
@admin_required
def update_provider(provider_id: int, current_user):
    payload = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        row = session.get(LLMProvider, provider_id)
        if not row:
            return json_error("provider_not_found", 404)
        values, error = provider_values(payload, row)
        if error:
            return json_error(error)
        for key, value in values.items():
            setattr(row, key, value)
        audit(session, current_user, "update_llm_provider", "llm_provider", str(row.id), {"name": row.name})
        return jsonify({"ok": True, "item": serialize_provider(row)})


@llm_models_bp.delete("/providers/<int:provider_id>")
@admin_required
def delete_provider(provider_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        row = session.get(LLMProvider, provider_id)
        if not row:
            return json_error("provider_not_found", 404)
        model_ids = [item.id for item in session.execute(select(LLMModel).where(LLMModel.provider_id == row.id)).scalars().all()]
        if model_ids:
            session.query(LLMUsageBinding).filter(LLMUsageBinding.model_id.in_(model_ids)).delete(synchronize_session=False)
            session.query(LLMModel).filter(LLMModel.provider_id == row.id).delete(synchronize_session=False)
        audit(session, current_user, "delete_llm_provider", "llm_provider", str(row.id), {"name": row.name})
        session.delete(row)
        return jsonify({"ok": True, "deleted": provider_id})


@llm_models_bp.post("/providers/<int:provider_id>/refresh")
@admin_required
def refresh_provider(provider_id: int, current_user):
    with session_scope(db_session_factory()) as session:
        provider = session.get(LLMProvider, provider_id)
        if not provider:
            return json_error("provider_not_found", 404)
        try:
            raw_models = fetch_models(provider)
            seen = set()
            created = 0
            updated = 0
            for item in raw_models:
                values = model_from_metadata(item)
                seen.add(values["model_id"])
                model = session.execute(select(LLMModel).where(LLMModel.provider_id == provider.id, LLMModel.model_id == values["model_id"])).scalar_one_or_none()
                if not model:
                    model = LLMModel(provider_id=provider.id, **values)
                    session.add(model)
                    created += 1
                else:
                    for key, value in values.items():
                        if key in {"display_name", "max_input_size", "max_output_tokens", "supports_tools"} and getattr(model, key) not in (None, "", False):
                            continue
                        setattr(model, key, value)
                    updated += 1
            provider.status = "ok"
            provider.last_error = None
            provider.last_checked_at = utc_now()
            audit(session, current_user, "refresh_llm_provider", "llm_provider", str(provider.id), {"created": created, "updated": updated, "listed": len(seen)})
            return jsonify({"ok": True, "created": created, "updated": updated, "listed": len(seen)})
        except urllib.error.URLError as exc:
            provider.status = "failed"
            provider.last_error = str(exc)[:1000]
            provider.last_checked_at = utc_now()
            return json_error(provider.last_error, 502)
        except Exception as exc:
            provider.status = "failed"
            provider.last_error = str(exc)[:1000]
            provider.last_checked_at = utc_now()
            return json_error(provider.last_error, 502)


@llm_models_bp.get("/models")
@login_required
def list_models(current_user):
    provider_filter = request.args.get("provider_id")
    endpoint_type = request.args.get("endpoint_type")
    with session_scope(db_session_factory()) as session:
        query = select(LLMModel).order_by(desc(LLMModel.updated_at))
        if provider_filter:
            query = query.where(LLMModel.provider_id == int(provider_filter))
        if endpoint_type:
            query = query.where(LLMModel.endpoint_type == endpoint_type)
        models = session.execute(query).scalars().all()
        providers = {row.id: row for row in session.execute(select(LLMProvider)).scalars().all()}
        return jsonify({"ok": True, "items": [serialize_model(row, providers.get(row.provider_id)) for row in models]})


@llm_models_bp.post("/models")
@admin_required
def create_model(current_user):
    payload = request.get_json(silent=True) or {}
    provider_id = payload.get("provider_id")
    if not provider_id:
        return json_error("provider_id_required")
    values, error = model_values(payload)
    if error:
        return json_error(error)
    with session_scope(db_session_factory()) as session:
        provider = session.get(LLMProvider, int(provider_id))
        if not provider:
            return json_error("provider_not_found", 404)
        row = LLMModel(provider_id=provider.id, status="manual", **values)
        session.add(row)
        session.flush()
        audit(session, current_user, "create_llm_model", "llm_model", str(row.id), {"model_id": row.model_id})
        return jsonify({"ok": True, "item": serialize_model(row, provider)}), 201


@llm_models_bp.put("/models/<int:model_pk>")
@admin_required
def update_model(model_pk: int, current_user):
    payload = request.get_json(silent=True) or {}
    with session_scope(db_session_factory()) as session:
        row = session.get(LLMModel, model_pk)
        if not row:
            return json_error("model_not_found", 404)
        values, error = model_values(payload, row)
        if error:
            return json_error(error)
        for key, value in values.items():
            setattr(row, key, value)
        provider = session.get(LLMProvider, row.provider_id)
        audit(session, current_user, "update_llm_model", "llm_model", str(row.id), {"model_id": row.model_id})
        return jsonify({"ok": True, "item": serialize_model(row, provider)})


@llm_models_bp.delete("/models/<int:model_pk>")
@admin_required
def delete_model(model_pk: int, current_user):
    with session_scope(db_session_factory()) as session:
        row = session.get(LLMModel, model_pk)
        if not row:
            return json_error("model_not_found", 404)
        session.query(LLMUsageBinding).filter(LLMUsageBinding.model_id == row.id).delete(synchronize_session=False)
        audit(session, current_user, "delete_llm_model", "llm_model", str(row.id), {"model_id": row.model_id})
        session.delete(row)
        return jsonify({"ok": True, "deleted": model_pk})


@llm_models_bp.post("/models/<int:model_pk>/test")
@admin_required
def test_model(model_pk: int, current_user):
    with session_scope(db_session_factory()) as session:
        row = session.get(LLMModel, model_pk)
        if not row:
            return json_error("model_not_found", 404)
        provider = session.get(LLMProvider, row.provider_id)
        if not provider:
            return json_error("provider_not_found", 404)
        ok, detail = test_model_call(provider, row)
        row.status = "ok" if ok else "failed"
        row.last_error = None if ok else detail
        row.last_checked_at = utc_now()
        audit(session, current_user, "test_llm_model", "llm_model", str(row.id), {"ok": ok, "detail": detail})
        return jsonify({"ok": ok, "detail": detail, "item": serialize_model(row, provider)}), 200 if ok else 502


@llm_models_bp.get("/usage-bindings")
@login_required
def list_usage_bindings(current_user):
    usage_key = request.args.get("usage_key")
    with session_scope(db_session_factory()) as session:
        query = select(LLMUsageBinding).order_by(asc(LLMUsageBinding.usage_key), asc(LLMUsageBinding.priority), asc(LLMUsageBinding.id))
        if usage_key:
            query = query.where(LLMUsageBinding.usage_key == usage_key)
        bindings = session.execute(query).scalars().all()
        models = {row.id: row for row in session.execute(select(LLMModel)).scalars().all()}
        providers = {row.id: row for row in session.execute(select(LLMProvider)).scalars().all()}
        items = []
        for binding in bindings:
            model = models.get(binding.model_id)
            provider = providers.get(model.provider_id) if model else None
            if model and provider:
                items.append(serialize_binding(binding, model, provider))
        return jsonify({"ok": True, "items": items})


@llm_models_bp.put("/usage-bindings/<usage_key>")
@admin_required
def replace_usage_bindings(usage_key: str, current_user):
    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    with session_scope(db_session_factory()) as session:
        session.query(LLMUsageBinding).filter(LLMUsageBinding.usage_key == usage_key).delete(synchronize_session=False)
        created = []
        for index, item in enumerate(raw_items):
            model_pk = item.get("model_pk") or item.get("model_id")
            model = session.get(LLMModel, int(model_pk)) if model_pk else None
            if not model:
                continue
            row = LLMUsageBinding(
                usage_key=usage_key,
                model_id=model.id,
                priority=parse_int(item.get("priority"), (index + 1) * 10, 1, 10000),
                enabled=parse_bool(item.get("enabled"), True),
                purpose_note=str(item.get("purpose_note") or "").strip() or None,
            )
            session.add(row)
            created.append(row)
        session.flush()
        audit(session, current_user, "replace_llm_usage_bindings", "llm_usage", usage_key, {"count": len(created)})
        return jsonify({"ok": True, "items": [{"id": row.id, "usage_key": row.usage_key, "model_pk": row.model_id, "priority": row.priority, "enabled": row.enabled, "purpose_note": row.purpose_note} for row in created]})
