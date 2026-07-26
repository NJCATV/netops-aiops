"""Default LLM provider bootstrap data."""

from __future__ import annotations

from app.db import session_scope
from app.models import LLMProvider


DEFAULT_LLM_PROVIDERS = [
    {
        "name": "官方 DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY,AI_API_KEY,PUBLIC_LLM_API_KEY",
        "remark": "项目公网 fallback；也可用 PUBLIC_LLM_API_KEY / AI_API_KEY 手工配置。",
    },
    {
        "name": "省公司 modelrouter",
        "base_url": "http://modelrouter.js96296.com/v1",
        "api_key_env": "MODELROUTER_API_KEY",
        "remark": "省公司统一模型路由，包含 DeepSeek/Qwen/GLM/BGE 等模型。",
    },
    {
        "name": "本公司 OneAPI",
        "base_url": "http://172.25.60.72:23000/v1",
        "api_key_env": "BRANCH_ONEAPI_API_KEY,INTERNAL_LLM_API_KEY",
        "remark": "本公司 oneapi，当前已验证 deepseek-v4-pro、qwen2.5-32b、qwen3.5-27b。",
    },
    {
        "name": "本地 GPU MiniCPM",
        "base_url": "http://172.25.60.72:8013/v1",
        "api_key_env": "MINICPM_API_KEY",
        "remark": "内网 GPU vLLM MiniCPM-o-4_5，支持图片理解。",
    },
]


def ensure_default_llm_providers(session_factory) -> int:
    created = 0
    with session_scope(session_factory) as session:
        for item in DEFAULT_LLM_PROVIDERS:
            existing = session.query(LLMProvider).filter(LLMProvider.name == item["name"]).one_or_none()
            if existing:
                continue
            session.add(
                LLMProvider(
                    name=item["name"],
                    base_url=item["base_url"],
                    api_key_env=item["api_key_env"],
                    provider_type="openai_compatible",
                    enabled=True,
                    timeout_seconds=60,
                    remark=item["remark"],
                    status="unknown",
                )
            )
            created += 1
    return created
