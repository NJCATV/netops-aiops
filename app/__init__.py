"""Flask API application factory."""

from __future__ import annotations

import os
import importlib
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify

from app.db import create_db_engine, make_session_factory


def create_app(config: dict[str, Any] | None = None) -> Flask:
    for candidate in (".env", "deploy/.env"):
        if os.path.exists(candidate):
            load_dotenv(candidate, override=False)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "dev-only-change-me",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        JSON_AS_ASCII=False,
    )
    if config:
        app.config.update(config)

    engine = create_db_engine()
    app.extensions["db_engine"] = engine
    app.extensions["session_factory"] = make_session_factory(engine)
    try:
        from app.db import Base
        importlib.import_module("app.models")

        Base.metadata.create_all(engine)
        from app.llm_defaults import ensure_default_llm_providers

        ensure_default_llm_providers(app.extensions["session_factory"])
    except Exception:
        pass

    @app.get("/api/health")
    def health():
        db_ok = True
        db_error = None
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
        except Exception as exc:  # pragma: no cover
            db_ok = False
            db_error = str(exc)
        payload = {"status": "ok" if db_ok else "degraded", "service": "aiops-api", "database": {"ok": db_ok}}
        if db_error:
            payload["database"]["error"] = db_error
        return jsonify(payload), 200 if db_ok else 503

    from app.api.ai import ai_bp
    from app.api.analysis_rules import analysis_rules_bp
    from app.api.fault_kb import fault_kb_bp
    from app.api.llm import llm_bp
    from app.api.llm_models import llm_models_bp
    from app.api.auth import auth_bp
    from app.api.report_tasks import report_tasks_bp
    from app.api.runtime import runtime_bp
    from app.api.system import system_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(runtime_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(fault_kb_bp)
    app.register_blueprint(analysis_rules_bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(llm_models_bp)
    app.register_blueprint(report_tasks_bp)
    app.register_blueprint(system_bp)
    return app
