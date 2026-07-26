"""LLM provider health APIs."""

from __future__ import annotations

from flask import Blueprint, jsonify

from aiops.llm.client import check_internal_llm_available
from app.api.auth import login_required


llm_bp = Blueprint("llm", __name__, url_prefix="/api")


@llm_bp.get("/llm/internal-health")
@login_required
def internal_llm_health(current_user):
    return jsonify(check_internal_llm_available())
