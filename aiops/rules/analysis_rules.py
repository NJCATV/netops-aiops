"""Natural-language AI analysis rules for pre-Agent scoring."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from typing import Any, Iterable, Optional

from sqlalchemy import select

from app.db import create_db_engine, make_session_factory, session_scope
from app.models import AiAnalysisRule, AiAnalysisRuleHit, AiAnalysisRun, utc_now
from aiops.llm.client import call_llm, sanitize_error


LOGGER = logging.getLogger(__name__)
OPTICAL_FAMILIES = ["OPTICAL_FAULT", "TRANSCEIVER_WARNING", "LINK_OPTICAL_ALARM"]
RADIUS_FAMILIES = ["RADIUS_SERVER_ABNORMAL", "RADIUS_AUTH_FAILURE", "RADIUS_ACCOUNTING_FAILURE"]
BFD_FAMILIES = ["BFD_SESSION_FLAP", "BFD_ABNORMAL"]
PACKET_LOSS_FAMILIES = ["LINK_PACKET_LOSS", "PACKET_LOSS_ALARM"]
PPP_FAMILIES = ["PPP_AUTH_FAILURE"]
TRAP_FAMILIES = ["MIB_UNTRANSLATED", "UNKNOWN_TRAP", "FAKE_MODULE_WARNING"]
SAFETY_EXCEPTIONS = ["multi_device_same_server", "open_duration_over_2h", "severity_critical", "affects_core_auth_or_accounting"]
ATTENTION_WORDS = ["必须关注", "重点看", "重点关注", "优先处理", "提醒我", "必须看"]
ANTI_NOISE_WORDS = ["不能忽略", "不要忽略", "必须关注", "重点关注", "优先处理", "提醒我", "不能不管"]
NOISE_WORDS = ["不用管", "不管", "忽略", "忽视", "不关注", "不报", "不提示", "降噪", "屏蔽", "过滤掉", "压低", "不用关注", "不用处理"]
OPTICAL_WORDS = ["光模块", "光口", "transceiver", "optical", "los", "收光", "发光"]
RADIUS_WORDS = ["radius", "认证", "计费"]
BFD_WORDS = ["bfd", "session flap", "会话抖动"]
PACKET_LOSS_WORDS = ["丢包", "packet loss", "loss"]
TRAP_WORDS = ["伪造模块", "fake module", "mib", "trap", "未翻译"]


def list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def contains_any(text: str, words: Iterable[str]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def extract_threshold(text: str) -> Optional[int]:
    match = re.search(r"(?:超过|大于|>=|＞|>)\s*(\d+)\s*(?:次)?", text)
    return int(match.group(1)) if match else None


def extract_known_targets(text: str) -> tuple[list[str], list[str]]:
    devices: list[str] = []
    objects: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}(?:-[A-Za-z0-9]+)*", text):
        upper = token.upper()
        if any(marker in upper for marker in ["16K", "CR", "CN", "YGM", "HEXIN"]):
            devices.append(token)
    for token in re.findall(r"(?:XGE|GE|GigabitEthernet|Ten-GigabitEthernet|Route-Aggregation)[A-Za-z0-9/.-]+", text, flags=re.I):
        objects.append(token)
    if "链路丢包" in text or "丢包" in text:
        objects.append("packet_loss")
    return sorted(set(devices)), sorted(set(objects))


def deterministic_parse_ai_rule(raw_text: str) -> dict:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("raw_text_required")
    target_event_families: list[str] = []
    target_keywords: list[str] = []
    target_devices, target_objects = extract_known_targets(text)
    rule_type = "attention"
    action = "boost_priority"
    priority = 50
    safety_exceptions: list[str] = []

    has_optical = contains_any(text, OPTICAL_WORDS)
    lower_text = text.lower()
    has_ppp = "ppp" in lower_text
    has_radius = "radius" in lower_text or "计费" in text or ("认证" in text and not has_ppp)
    has_attention = contains_any(text, ATTENTION_WORDS)
    has_noise = contains_any(text, NOISE_WORDS)

    if has_optical:
        target_event_families.extend(OPTICAL_FAMILIES)
        target_keywords.extend(["光模块", "光口", "transceiver", "optical"])
        rule_type = "attention"
        action = "boost_priority"
        priority = 80
    if has_radius:
        target_event_families.extend(RADIUS_FAMILIES)
        target_keywords.extend(["radius", "认证", "计费"])
        if has_noise:
            rule_type = "noise_reduction"
            action = "downgrade_or_suppress"
            priority = 30
            safety_exceptions = SAFETY_EXCEPTIONS[:]
    if has_attention:
        rule_type = "attention"
        action = "boost_priority"
        priority = max(priority, 70)
    if has_noise:
        rule_type = "noise_reduction"
        action = "downgrade_or_suppress"
        priority = min(priority, 40)
        if has_radius:
            safety_exceptions = SAFETY_EXCEPTIONS[:]
    if has_ppp:
        target_event_families.append("PPP_AUTH_FAILURE")
        target_keywords.extend(["PPP", "认证失败"])
    if "丢包" in text:
        target_event_families.extend(["PACKET_LOSS", "LINK_PACKET_LOSS", "QOS_CONGESTION", "BFD_FLAP"])
        target_keywords.extend(["丢包", "packet loss"])
    threshold = extract_threshold(text)

    target_event_families = sorted(set(target_event_families))
    target_keywords = sorted(set(target_keywords), key=str.lower)
    parsed_rule = {
        "raw_text": text,
        "rule_type": rule_type,
        "action": action,
        "target_event_families": target_event_families,
        "target_keywords": target_keywords,
        "target_devices": target_devices,
        "target_objects": target_objects,
        "priority": priority,
        "scope": "global",
        "threshold_count": threshold,
        "safety_exceptions": safety_exceptions,
    }
    return parsed_rule


def ai_rule_system_prompt() -> str:
    return """
你是一个 AIOps 运维规则解析器。你的任务是将用户输入的自然语言规则解析为结构化 JSON。
规则用于电信城域网 AI 告警分析，包括设备、链路、光模块、BFD、RADIUS、PPP、Trap、Syslog 等事件。
你必须准确判断用户意图是：重点关注、降噪忽略、阈值控制、报告格式要求、未知。
特别注意：
- “不管、不用管、忽略、忽视、不关注、不报、不提示、降噪、屏蔽、过滤、压低”表示降噪或抑制，不是重点关注。
- “必须关注、重点看、优先处理、提醒我、不能忽略、不要忽略”表示重点关注。
- 降噪类规则不能完全屏蔽重大故障，必须带安全例外。
只输出 JSON，不要输出 Markdown，不要输出解释。
""".strip()


def ai_rule_user_prompt(raw_text: str) -> str:
    schema = {
        "rule_type": "attention | noise_reduction | threshold | report_preference | unknown",
        "action": "boost_priority | downgrade_or_suppress | threshold_control | format_control | unknown",
        "confidence": 0.0,
        "reason": "一句话解释系统如何理解这条规则",
        "target": {"event_families": [], "keywords": [], "devices": [], "objects": [], "severity": [], "scope": "global | device | link | service | unknown"},
        "conditions": {"threshold": None, "duration": None, "status": None},
        "effect": {"priority_delta": 0, "hide_from_main_report": False, "min_report_section": None},
        "safety_exceptions": [],
        "human_readable_summary": "",
    }
    return f"""
请解析以下用户规则：

raw_text: {raw_text}

请只输出以下 JSON，字段必须固定：
{json.dumps(schema, ensure_ascii=False, indent=2)}

事件族参考：
RADIUS_ACCOUNTING_FAILURE, RADIUS_AUTH_FAILURE, RADIUS_SERVER_ABNORMAL
OPTICAL_FAULT, TRANSCEIVER_WARNING, LINK_OPTICAL_ALARM
BFD_SESSION_FLAP, BFD_ABNORMAL
LINK_PACKET_LOSS, PACKET_LOSS_ALARM
PPP_AUTH_FAILURE
MIB_UNTRANSLATED, UNKNOWN_TRAP, FAKE_MODULE_WARNING
""".strip()


def extract_json_object(text: str) -> dict:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", flags=re.S)
    if not match:
        raise ValueError("ai_rule_parse_non_json")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("ai_rule_parse_not_object")
    return value


def safe_scalar(value, default=None):
    if isinstance(value, list):
        return value[0] if value else default
    if isinstance(value, dict):
        return default
    return value if value is not None else default


def safe_int(value, default: int = 0) -> int:
    try:
        return int(float(safe_scalar(value, default)))
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(safe_scalar(value, default))
    except (TypeError, ValueError):
        return default


def parse_ai_rule_with_llm(raw_text: str) -> dict:
    messages = [
        {"role": "system", "content": ai_rule_system_prompt()},
        {"role": "user", "content": ai_rule_user_prompt(raw_text)},
    ]
    result = call_llm(
        messages,
        temperature=0,
        timeout=int(os.getenv("AI_RULE_LLM_TIMEOUT", "30")),
        response_format={"type": "json_object"},
    )
    content = getattr(result.response.choices[0].message, "content", "") or ""
    parsed = extract_json_object(content)
    parsed["_llm_provider"] = result.provider
    parsed["_llm_model"] = result.model
    return parsed


def normalize_ai_rule_shape(parsed: dict, raw_text: str) -> dict:
    target = parsed.get("target") if isinstance(parsed.get("target"), dict) else {}
    conditions = parsed.get("conditions") if isinstance(parsed.get("conditions"), dict) else {}
    effect = parsed.get("effect") if isinstance(parsed.get("effect"), dict) else {}
    flat = {
        "raw_text": raw_text,
        "rule_type": parsed.get("rule_type") or "unknown",
        "action": parsed.get("action") or "unknown",
        "target_event_families": list_value(parsed.get("target_event_families") or target.get("event_families")),
        "target_keywords": list_value(parsed.get("target_keywords") or target.get("keywords")),
        "target_devices": list_value(parsed.get("target_devices") or target.get("devices")),
        "target_objects": list_value(parsed.get("target_objects") or target.get("objects")),
        "priority": safe_int(parsed.get("priority"), 50 + safe_int(effect.get("priority_delta"), 0)),
        "scope": str(parsed.get("scope") or target.get("scope") or "global"),
        "threshold_count": safe_scalar(parsed.get("threshold_count") or conditions.get("threshold")),
        "duration": safe_scalar(conditions.get("duration")),
        "status": safe_scalar(conditions.get("status")),
        "safety_exceptions": list_value(parsed.get("safety_exceptions")),
        "confidence": safe_float(parsed.get("confidence"), 0),
        "reason": safe_scalar(parsed.get("reason")),
        "effect": effect,
        "human_readable_summary": safe_scalar(parsed.get("human_readable_summary")) or safe_scalar(parsed.get("reason")) or "",
        "llm_provider": safe_scalar(parsed.get("_llm_provider")),
        "llm_model": safe_scalar(parsed.get("_llm_model")),
    }
    return flat


def add_unique(values: list[str], additions: Iterable[str]) -> list[str]:
    seen = {str(item).lower() for item in values}
    for item in additions:
        key = str(item).lower()
        if key not in seen:
            values.append(str(item))
            seen.add(key)
    return values


def validate_and_normalize_rule(parsed_rule: dict, raw_text: str) -> dict:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("raw_text_required")
    parsed = normalize_ai_rule_shape(parsed_rule or {}, text)
    fallback = deterministic_parse_ai_rule(text)

    lower_text = text.lower()
    keyword_text = " ".join(parsed.get("target_keywords") or []).lower()
    has_noise = contains_any(text, NOISE_WORDS)
    has_anti_noise = contains_any(text, ANTI_NOISE_WORDS)
    has_attention = contains_any(text, ATTENTION_WORDS) or has_anti_noise
    has_threshold = extract_threshold(text) is not None

    if has_threshold and ("才关注" in text or "超过" in text or "大于" in text):
        parsed["rule_type"] = "threshold"
        parsed["action"] = "threshold_control"
        parsed["priority"] = 60
        parsed["threshold_count"] = extract_threshold(text)
    elif has_noise and not has_anti_noise:
        parsed["rule_type"] = "noise_reduction"
        parsed["action"] = "downgrade_or_suppress"
        parsed["priority"] = 30
    elif has_attention:
        parsed["rule_type"] = "attention"
        parsed["action"] = "boost_priority"
        parsed["priority"] = max(safe_int(parsed.get("priority"), 70), 70)

    combined = f"{lower_text} {keyword_text}"
    if contains_any(combined, RADIUS_WORDS):
        add_unique(parsed["target_event_families"], RADIUS_FAMILIES)
        add_unique(parsed["target_keywords"], ["radius", "RADIUS", "认证", "计费"])
        if parsed.get("scope") in {"global", "unknown", ""}:
            parsed["scope"] = "service"
    if contains_any(combined, OPTICAL_WORDS):
        add_unique(parsed["target_event_families"], OPTICAL_FAMILIES)
        add_unique(parsed["target_keywords"], ["光模块", "光口", "transceiver", "optical", "收光", "发光", "LOS"])
    if contains_any(combined, BFD_WORDS):
        add_unique(parsed["target_event_families"], BFD_FAMILIES)
        add_unique(parsed["target_keywords"], ["BFD", "session flap", "会话抖动"])
    if contains_any(combined, PACKET_LOSS_WORDS):
        add_unique(parsed["target_event_families"], PACKET_LOSS_FAMILIES)
        add_unique(parsed["target_keywords"], ["丢包", "packet loss", "loss"])
    if "ppp" in lower_text:
        add_unique(parsed["target_event_families"], PPP_FAMILIES)
        add_unique(parsed["target_keywords"], ["PPP", "认证失败"])
    if contains_any(combined, TRAP_WORDS):
        add_unique(parsed["target_event_families"], TRAP_FAMILIES)
        add_unique(parsed["target_keywords"], ["Trap", "MIB", "伪造模块"])

    if not parsed["target_event_families"]:
        add_unique(parsed["target_event_families"], fallback.get("target_event_families") or [])
    if not parsed["target_keywords"]:
        add_unique(parsed["target_keywords"], fallback.get("target_keywords") or [])
    if not parsed["target_devices"]:
        parsed["target_devices"] = fallback.get("target_devices") or []
    if not parsed["target_objects"]:
        parsed["target_objects"] = fallback.get("target_objects") or []

    if parsed["rule_type"] == "noise_reduction" or parsed["action"] == "downgrade_or_suppress":
        parsed["rule_type"] = "noise_reduction"
        parsed["action"] = "downgrade_or_suppress"
        parsed["priority"] = 30
        add_unique(parsed["safety_exceptions"], SAFETY_EXCEPTIONS)
        parsed.setdefault("effect", {})
        parsed["effect"]["priority_delta"] = min(safe_int(parsed["effect"].get("priority_delta"), -30), -30)
        parsed["effect"]["hide_from_main_report"] = True
        parsed["effect"].setdefault("min_report_section", "噪声过滤")
    elif parsed["rule_type"] == "threshold" or parsed["action"] == "threshold_control":
        parsed["rule_type"] = "threshold"
        parsed["action"] = "threshold_control"
        parsed["priority"] = safe_int(parsed.get("priority"), 60)
    elif parsed["rule_type"] == "attention" or parsed["action"] == "boost_priority":
        parsed["rule_type"] = "attention"
        parsed["action"] = "boost_priority"
        parsed["priority"] = max(safe_int(parsed.get("priority"), 70), 70)

    confidence = safe_float(parsed.get("confidence"), 0.92 if parsed["rule_type"] != "unknown" else 0.4)
    parsed["confidence"] = max(0.0, min(1.0, confidence))
    parsed["requires_confirmation"] = parsed["confidence"] < 0.6 or parsed["rule_type"] == "unknown"
    if parsed["requires_confirmation"]:
        parsed["enabled_recommended"] = False
        parsed["warning"] = "系统无法明确理解该规则，请修改描述或手动选择规则类型。"
    parsed["target_event_families"] = sorted(set(parsed["target_event_families"]))
    parsed["target_keywords"] = sorted(set(parsed["target_keywords"]), key=str.lower)
    return parsed


def parse_ai_rule(raw_text: str) -> dict:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("raw_text_required")
    parsed: dict
    if os.getenv("AI_RULE_LLM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        try:
            parsed = parse_ai_rule_with_llm(text)
        except Exception as exc:
            LOGGER.warning("AI rule LLM parse failed, using deterministic parser: %s", sanitize_error(exc))
            parsed = deterministic_parse_ai_rule(text)
    else:
        parsed = deterministic_parse_ai_rule(text)
    return validate_and_normalize_rule(parsed, text)


def rule_to_payload(rule: AiAnalysisRule) -> dict:
    return {
        "id": rule.id,
        "rule_name": rule.rule_name,
        "raw_text": rule.raw_text,
        "rule_type": rule.rule_type,
        "action": rule.action,
        "target_event_families": rule.target_event_families or [],
        "target_keywords": rule.target_keywords or [],
        "target_devices": rule.target_devices or [],
        "target_objects": rule.target_objects or [],
        "parsed_rule": rule.parsed_rule or {},
        "priority": rule.priority,
        "enabled": rule.enabled,
        "scope": rule.scope,
        "created_by": rule.created_by,
        "hit_count": rule.hit_count,
        "last_hit_at": rule.last_hit_at.isoformat().replace("+00:00", "Z") if rule.last_hit_at else None,
        "created_at": rule.created_at.isoformat().replace("+00:00", "Z") if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat().replace("+00:00", "Z") if rule.updated_at else None,
    }


def candidate_text(candidate: dict) -> str:
    parts = [
        candidate.get("event_type"),
        candidate.get("alarm_name"),
        candidate.get("trap_oid_name"),
        candidate.get("device_name"),
        candidate.get("managed_device_name"),
        candidate.get("object_key"),
        candidate.get("managed_object_name"),
        candidate.get("event_summary"),
        candidate.get("priority_reason"),
        candidate.get("display_name"),
        candidate.get("sample_message"),
    ]
    return " ".join(str(item) for item in parts if item).lower()


def candidate_count(candidate: dict) -> int:
    for key in ("event_count", "count", "total_count", "flap_count", "current_count"):
        try:
            return int(float(candidate.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return 0


def parse_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def event_family_matches(rule: dict, candidate: dict) -> bool:
    families = [item.upper() for item in list_value(rule.get("target_event_families"))]
    if not families:
        return False
    event_type = str(candidate.get("event_type") or "").upper()
    text = candidate_text(candidate).upper()
    return any(family in event_type or family in text for family in families)


def keyword_matches(rule: dict, candidate: dict) -> bool:
    text = candidate_text(candidate)
    return any(keyword.lower() in text for keyword in list_value(rule.get("target_keywords")))


def target_matches(rule: dict, candidate: dict) -> bool:
    text = candidate_text(candidate)
    devices = [item.lower() for item in list_value(rule.get("target_devices"))]
    objects = [item.lower() for item in list_value(rule.get("target_objects"))]
    return (not devices or any(item in text for item in devices)) and (not objects or any(item in text for item in objects))


def threshold_matches(rule: dict, candidate: dict) -> bool:
    threshold = rule.get("threshold_count")
    return not threshold or candidate_count(candidate) >= int(threshold)


def rule_matches(rule: dict, candidate: dict) -> bool:
    has_specific = bool(rule.get("target_event_families") or rule.get("target_keywords") or rule.get("target_devices") or rule.get("target_objects"))
    if has_specific and not (event_family_matches(rule, candidate) or keyword_matches(rule, candidate)):
        return False
    if not target_matches(rule, candidate):
        return False
    return threshold_matches(rule, candidate)


def safety_exception_reasons(rule: dict, candidate: dict, summary: dict) -> list[str]:
    if rule.get("action") != "downgrade_or_suppress":
        return []
    reasons: list[str] = []
    severity = str(candidate.get("severity_max") or candidate.get("alarm_severity") or candidate.get("severity") or "").lower()
    if severity in {"critical", "4", "5"}:
        reasons.append("severity_critical")
    start = parse_time(candidate.get("first_seen"))
    end = parse_time(candidate.get("last_seen")) or parse_time(summary.get("metadata", {}).get("window_end"))
    if start and end and (end - start).total_seconds() >= 7200:
        reasons.append("open_duration_over_2h")
    text = candidate_text(candidate)
    if "radius" in text or "认证" in text or "计费" in text:
        reasons.append("affects_core_auth_or_accounting")
        object_key = str(candidate.get("object_key") or candidate.get("managed_object_name") or "")
        device_count = 0
        for row in summary.get("multi_device_correlations") or []:
            if object_key and object_key in str(row.get("object_key") or ""):
                device_count = max(device_count, int(row.get("device_count") or 0))
            if "radius" in str(row.get("correlation_type") or "").lower():
                device_count = max(device_count, int(row.get("device_count") or 0))
        if device_count >= 2:
            reasons.append("multi_device_same_server")
    return sorted(set(reasons))


def iter_candidate_sections(summary: dict):
    for section in [
        "critical_alarm_candidates",
        "open_incidents",
        "critical_traps",
        "important_trap_candidates",
        "important_traps",
        "flapping_objects",
        "multi_device_correlations",
        "new_anomalies",
        "baseline_deviations",
        "noise_candidates",
    ]:
        rows = summary.get(section)
        if isinstance(rows, list):
            for index, candidate in enumerate(rows):
                if isinstance(candidate, dict):
                    yield section, index, candidate


def load_enabled_rules(env_file: Optional[str] = None) -> list[dict]:
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        rows = session.execute(select(AiAnalysisRule).where(AiAnalysisRule.enabled.is_(True)).order_by(AiAnalysisRule.priority.desc(), AiAnalysisRule.id)).scalars().all()
        return [rule_to_payload(row) for row in rows]


def apply_ai_rules(summary: dict, rules: list[dict]) -> dict:
    if not rules:
        summary.setdefault("user_rule_hits", [])
        return summary
    hits: list[dict] = []
    for section, index, candidate in iter_candidate_sections(summary):
        for rule in rules:
            parsed = rule.get("parsed_rule") or rule
            if not rule_matches(parsed, candidate):
                continue
            safety = safety_exception_reasons(parsed, candidate, summary)
            result = "boosted"
            score_delta = int(parsed.get("priority") or rule.get("priority") or 50)
            if parsed.get("action") == "downgrade_or_suppress":
                if safety:
                    result = "downgrade_blocked_by_safety_exception"
                    candidate["suppression_blocked"] = True
                else:
                    result = "suppressed"
                    candidate["suppressed"] = True
                score_delta = -abs(score_delta)
            else:
                candidate["attention_boosted"] = True
            candidate["score_adjustment"] = int(candidate.get("score_adjustment") or 0) + score_delta
            hit = {
                "rule_id": rule.get("id"),
                "rule_name": rule.get("rule_name"),
                "raw_text": rule.get("raw_text"),
                "rule_type": parsed.get("rule_type"),
                "action": parsed.get("action"),
                "section": section,
                "index": index,
                "matched_target": candidate.get("event_summary") or candidate.get("alarm_name") or candidate.get("display_name") or candidate.get("event_type") or candidate.get("object_key"),
                "device_name": candidate.get("device_name") or candidate.get("managed_device_name"),
                "object_key": candidate.get("object_key") or candidate.get("managed_object_name"),
                "action_result": result,
                "safety_exception": safety,
            }
            candidate.setdefault("user_rule_hits", []).append(hit)
            hits.append(hit)
    summary["user_rule_hits"] = hits
    summary.setdefault("metadata", {})["user_rule_hit_count"] = len(hits)
    return summary


def record_rule_hits(run_uid: str, hits: list[dict]) -> None:
    if not hits:
        return
    engine = create_db_engine()
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        run = session.execute(select(AiAnalysisRun).where(AiAnalysisRun.run_uid == run_uid)).scalar_one_or_none()
        now = utc_now()
        for hit in hits:
            rule_id = hit.get("rule_id")
            if not rule_id:
                continue
            rule = session.get(AiAnalysisRule, int(rule_id))
            if rule:
                rule.hit_count = int(rule.hit_count or 0) + 1
                rule.last_hit_at = now
            session.add(
                AiAnalysisRuleHit(
                    rule_id=int(rule_id),
                    run_id=run.id if run else None,
                    run_uid=run_uid,
                    matched_target=str(hit.get("matched_target") or "")[:512],
                    action_result=hit.get("action_result"),
                    safety_exception=hit.get("safety_exception") or [],
                    detail=hit,
                )
            )
