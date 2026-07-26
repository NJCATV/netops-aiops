"""Database-backed LLM registry helpers."""

from __future__ import annotations

import os
from typing import Iterable

from sqlalchemy import select

from app.db import create_db_engine, make_session_factory, session_scope
from app.models import LLMModel, LLMProvider, LLMUsageBinding


def _api_key(provider: LLMProvider) -> str:
    if provider.api_key:
        return provider.api_key
    if provider.api_key_env:
        for name in str(provider.api_key_env).split(","):
            value = os.getenv(name.strip())
            if value:
                return value
    return ""


def _config_from_rows(provider: LLMProvider, model: LLMModel, provider_name: str):
    from aiops.llm.client import LLMProviderConfig

    return LLMProviderConfig(
        provider=provider_name,
        enabled=bool(provider.enabled and model.enabled),
        base_url=provider.base_url,
        model=model.model_id,
        api_key=_api_key(provider),
        timeout=int(provider.timeout_seconds or os.getenv("AI_REQUEST_TIMEOUT_SECONDS") or 60),
    )


def _load_model_configs(model_ids: Iterable[int]):
    ids = [int(value) for value in model_ids if str(value).strip()]
    if not ids:
        return []
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        models = session.execute(select(LLMModel).where(LLMModel.id.in_(ids))).scalars().all()
        by_id = {row.id: row for row in models}
        providers = {row.id: row for row in session.execute(select(LLMProvider).where(LLMProvider.id.in_([row.provider_id for row in models]))).scalars().all()}
        configs = []
        for model_id in ids:
            model = by_id.get(model_id)
            provider = providers.get(model.provider_id) if model else None
            if not model or not provider or model.endpoint_type != "chat":
                continue
            configs.append(_config_from_rows(provider, model, f"registry:{provider.name}"))
        return configs


def configs_for_selector(selector: str):
    text = str(selector or "").strip()
    if text.startswith("llm_models:"):
        raw_ids = [item.strip() for item in text.split(":", 1)[1].split(",")]
        return _load_model_configs([int(item) for item in raw_ids if item.isdigit()])
    if text.startswith("llm_model:"):
        raw_id = text.split(":", 1)[1].strip()
        return _load_model_configs([int(raw_id)]) if raw_id.isdigit() else []
    if text.startswith("llm_usage:"):
        usage_key = text.split(":", 1)[1].strip()
        engine = create_db_engine()
        session_factory = make_session_factory(engine)
        with session_scope(session_factory) as session:
            bindings = (
                session.execute(
                    select(LLMUsageBinding)
                    .where(LLMUsageBinding.usage_key == usage_key, LLMUsageBinding.enabled.is_(True))
                    .order_by(LLMUsageBinding.priority.asc(), LLMUsageBinding.id.asc())
                )
                .scalars()
                .all()
            )
            model_ids = [row.model_id for row in bindings]
        return _load_model_configs(model_ids)
    return []


def display_name_for_selector(selector: str) -> str:
    configs = configs_for_selector(selector)
    if not configs:
        return selector
    return " -> ".join(config.model for config in configs)
