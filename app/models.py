"""SQLAlchemy models for application metadata.

Elasticsearch remains the store for large operational time-series data. These
tables are only for app users, report configuration, report metadata, send
records, settings, and audit records.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("identity_source", "external_subject", name="uk_users_external_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_source: Mapped[str] = mapped_column(String(32), nullable=False, default="local", index=True)
    external_subject: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    external_role_code: Mapped[Optional[str]] = mapped_column(String(64))
    external_org_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    external_org_name: Mapped[Optional[str]] = mapped_column(String(128))
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class ReportTask(TimestampMixin, Base):
    __tablename__ = "report_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_subject: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    scope_org_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    scope_regions_json: Mapped[Optional[list]] = mapped_column(JSON)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    cron_expr: Mapped[Optional[str]] = mapped_column(String(128))
    recipients: Mapped[Optional[dict]] = mapped_column(JSON)
    settings: Mapped[Optional[dict]] = mapped_column(JSON)
    created_by: Mapped[Optional[str]] = mapped_column(String(64))
    last_run_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class ReportRecord(TimestampMixin, Base):
    __tablename__ = "report_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    report_title: Mapped[Optional[str]] = mapped_column(String(255))
    time_window_start: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    time_window_end: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    hours: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    file_path: Mapped[Optional[str]] = mapped_column(String(512))
    es_index: Mapped[Optional[str]] = mapped_column(String(128))
    es_document_id: Mapped[Optional[str]] = mapped_column(String(128))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON)


class EmailSendLog(TimestampMixin, Base):
    __tablename__ = "email_send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_record_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    recipients: Mapped[Optional[dict]] = mapped_column(JSON)
    subject: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("setting_key", name="uq_app_settings_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    setting_value: Mapped[Optional[str]] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False, default="string")
    description: Mapped[Optional[str]] = mapped_column(String(255))


class LLMProvider(TimestampMixin, Base):
    __tablename__ = "llm_providers"
    __table_args__ = (
        UniqueConstraint("name", name="uq_llm_providers_name"),
        Index("idx_llm_providers_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(Text)
    api_key_env: Mapped[Optional[str]] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    capabilities: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    last_checked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    remark: Mapped[Optional[str]] = mapped_column(Text)


class LLMModel(TimestampMixin, Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="uq_llm_models_provider_model"),
        Index("idx_llm_models_enabled", "enabled"),
        Index("idx_llm_models_endpoint_type", "endpoint_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("llm_providers.id"), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    endpoint_type: Mapped[str] = mapped_column(String(64), nullable=False, default="chat")
    input_types: Mapped[Optional[dict]] = mapped_column(JSON)
    output_types: Mapped[Optional[dict]] = mapped_column(JSON)
    max_context_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    max_input_size: Mapped[Optional[str]] = mapped_column(String(128))
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    last_checked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    raw_metadata: Mapped[Optional[dict]] = mapped_column(JSON)
    remark: Mapped[Optional[str]] = mapped_column(Text)


class LLMUsageBinding(TimestampMixin, Base):
    __tablename__ = "llm_usage_bindings"
    __table_args__ = (
        UniqueConstraint("usage_key", "model_id", name="uq_llm_usage_bindings_usage_model"),
        Index("idx_llm_usage_bindings_usage", "usage_key", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_key: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("llm_models.id"), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    purpose_note: Mapped[Optional[str]] = mapped_column(Text)


class AiChatSession(TimestampMixin, Base):
    __tablename__ = "ai_chat_sessions"
    __table_args__ = (
        Index("idx_ai_chat_sessions_user_last", "user_id", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="fault_kb_qa", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AiChatMessage(TimestampMixin, Base):
    __tablename__ = "ai_chat_messages"
    __table_args__ = (
        Index("idx_ai_chat_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("ai_chat_sessions.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    model_name: Mapped[Optional[str]] = mapped_column(String(255))
    provider_name: Mapped[Optional[str]] = mapped_column(String(255))
    model_error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)


class PlatformDeviceScope(TimestampMixin, Base):
    """Device-to-region projection used to enforce platform data boundaries in ES queries."""

    __tablename__ = "platform_device_scope"
    __table_args__ = (
        UniqueConstraint("source_system", "device_type", "source_device_id", name="uk_platform_device_scope_source"),
        Index("idx_platform_device_scope_region_active", "region_code", "is_active"),
        Index("idx_platform_device_scope_ip", "ip_address"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="go_collector")
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(255))
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PlatformIdentityAudit(Base):
    """Immutable trace of identities accepted through the platform trust boundary."""

    __tablename__ = "platform_identity_audit"
    __table_args__ = (
        Index("idx_platform_identity_audit_subject", "identity_source", "external_subject", "authenticated_at"),
        Index("idx_platform_identity_audit_user", "aiops_user_id", "authenticated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aiops_user_id: Mapped[Optional[int]] = mapped_column(Integer)
    identity_source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(128))
    role_code: Mapped[Optional[str]] = mapped_column(String(64))
    org_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    org_name: Mapped[Optional[str]] = mapped_column(String(128))
    regions_json: Mapped[Optional[list]] = mapped_column(JSON)
    permissions_json: Mapped[Optional[list]] = mapped_column(JSON)
    request_id: Mapped[Optional[str]] = mapped_column(String(64))
    client_ip: Mapped[Optional[str]] = mapped_column(String(64))
    authenticated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MibOidMapping(TimestampMixin, Base):
    __tablename__ = "mib_oid_mappings"
    __table_args__ = (UniqueConstraint("oid", name="uq_mib_oid_mappings_oid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oid: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    module: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    object_type: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    syntax: Mapped[Optional[str]] = mapped_column(String(255))
    max_access: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[Optional[str]] = mapped_column(String(64))
    description_short: Mapped[Optional[str]] = mapped_column(Text)
    source_file: Mapped[Optional[str]] = mapped_column(String(512))
    source_line: Mapped[Optional[int]] = mapped_column(Integer)
    is_notification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)


class TrapAlarmDefinition(TimestampMixin, Base):
    __tablename__ = "trap_alarm_definitions"
    __table_args__ = (
        UniqueConstraint("source_file", "fault_oid", name="uq_trap_alarm_def_source_fault_oid"),
        Index("idx_trap_alarm_def_vendor", "vendor"),
        Index("idx_trap_alarm_def_enterprise_id", "enterprise_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    enterprise_id: Mapped[Optional[str]] = mapped_column(String(255))
    enterprise_name: Mapped[Optional[str]] = mapped_column(String(255))
    fault_oid: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    fault_oid_v1: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    fault_oid_v2: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    fault_name: Mapped[Optional[str]] = mapped_column(String(512), index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    custom_severity: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    fault_type: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    recover_flag: Mapped[Optional[str]] = mapped_column(String(64))
    desc_info: Mapped[Optional[str]] = mapped_column(Text)
    fault_reason: Mapped[Optional[str]] = mapped_column(Text)
    suggestion: Mapped[Optional[str]] = mapped_column(Text)
    category_main_id: Mapped[Optional[str]] = mapped_column(String(64))
    category_base_id: Mapped[Optional[str]] = mapped_column(String(64))
    category_sub_id: Mapped[Optional[str]] = mapped_column(String(64))
    source_file: Mapped[Optional[str]] = mapped_column(String(512), index=True)
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TrapAlarmOidAlias(TimestampMixin, Base):
    __tablename__ = "trap_alarm_oid_aliases"
    __table_args__ = (
        UniqueConstraint("oid", name="uq_trap_alarm_oid_aliases_oid"),
        Index("idx_trap_alarm_oid_alias_vendor", "vendor"),
        Index("idx_trap_alarm_oid_alias_enterprise_id", "enterprise_id"),
        Index("idx_trap_alarm_oid_alias_definition_id", "definition_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("trap_alarm_definitions.id"), nullable=False)
    oid: Mapped[str] = mapped_column(String(255), nullable=False)
    oid_type: Mapped[str] = mapped_column(String(64), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    enterprise_id: Mapped[Optional[str]] = mapped_column(String(255))


class AiAnalysisRun(Base):
    __tablename__ = "ai_analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    scope_subject: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    scope_org_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    scope_regions_json: Mapped[Optional[list]] = mapped_column(JSON)
    window_start: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), index=True)
    window_end: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), index=True)
    hours: Mapped[Optional[int]] = mapped_column(Integer)
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    overall_level: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    overall_title: Mapped[Optional[str]] = mapped_column(String(512))
    summary_text: Mapped[Optional[str]] = mapped_column(Text)
    summary_path: Mapped[Optional[str]] = mapped_column(String(512))
    result_path: Mapped[Optional[str]] = mapped_column(String(512))
    trajectory_dir: Mapped[Optional[str]] = mapped_column(String(512))
    tool_call_count: Mapped[Optional[int]] = mapped_column(Integer)
    llm_call_count: Mapped[Optional[int]] = mapped_column(Integer)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AiFinding(TimestampMixin, Base):
    __tablename__ = "ai_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512))
    severity: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    device_ip: Mapped[Optional[str]] = mapped_column(String(512), index=True)
    device_name: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    object_key: Mapped[Optional[str]] = mapped_column(String(512), index=True)
    event_types: Mapped[Optional[dict]] = mapped_column(JSON)
    root_cause_hypothesis: Mapped[Optional[str]] = mapped_column(Text)
    impact: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    recommended_actions: Mapped[Optional[dict]] = mapped_column(JSON)
    missing_data: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_finding: Mapped[Optional[dict]] = mapped_column(JSON)
    finding_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)


class AiFindingFeedback(Base):
    __tablename__ = "ai_finding_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("ai_findings.id"), nullable=False, index=True)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actual_root_cause: Mapped[Optional[str]] = mapped_column(Text)
    action_taken: Mapped[Optional[str]] = mapped_column(Text)
    operator: Mapped[Optional[str]] = mapped_column(String(128))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AiAnalysisRule(TimestampMixin, Base):
    __tablename__ = "ai_analysis_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_event_families: Mapped[Optional[dict]] = mapped_column(JSON)
    target_keywords: Mapped[Optional[dict]] = mapped_column(JSON)
    target_devices: Mapped[Optional[dict]] = mapped_column(JSON)
    target_objects: Mapped[Optional[dict]] = mapped_column(JSON)
    parsed_rule: Mapped[Optional[dict]] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="global", index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_hit_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class AiAnalysisRuleHit(Base):
    __tablename__ = "ai_analysis_rule_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_rules.id"), nullable=False, index=True)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_analysis_runs.id"), index=True)
    run_uid: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    matched_target: Mapped[Optional[str]] = mapped_column(String(512))
    action_result: Mapped[Optional[str]] = mapped_column(String(128))
    safety_exception: Mapped[Optional[dict]] = mapped_column(JSON)
    detail: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(128))
    client_ip: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[dict]] = mapped_column(JSON)
