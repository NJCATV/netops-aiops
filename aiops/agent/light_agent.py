"""Lightweight AIOps Agent call flow."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from aiops.tools.ai_tools import execute_ai_tool, get_tool_schemas
from aiops.llm.client import call_llm, preferred_model


LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TOOL_RESULT_CHARS = 24000
MAX_TOOL_RESULT_SUMMARY_CHARS = 9000
DEFAULT_AGENT_TOOL_LIMIT = 5
RAW_DEBUG_DIR = pathlib.Path(os.getenv("LIGHT_AGENT_DEBUG_DIR", "outputs/debug"))
REQUIRED_ARRAY_FIELDS = ["summary_cards", "must_handle", "watch", "noise", "recovered", "insufficient", "correlations", "next_actions"]


class LightAgentError(RuntimeError):
    pass


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def json_size_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value or "", encoding="utf-8")


def create_trajectory_dir(debug_dir: Optional[str]) -> pathlib.Path:
    base = pathlib.Path(debug_dir) if debug_dir else RAW_DEBUG_DIR
    run_id = "%s-%s" % (utc_now().strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8])
    path = base / "agent_runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_env(path: Optional[str]) -> None:
    if load_dotenv is None:
        return
    candidates: List[pathlib.Path] = []
    if path:
        candidates.append(pathlib.Path(path))
    else:
        root = pathlib.Path(__file__).resolve().parents[2]
        candidates.extend([root / ".env", root / "deploy" / ".env"])
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate, override=False)


def is_llm_selector(model: Optional[str]) -> bool:
    return bool(model and str(model).startswith(("llm_model:", "llm_models:", "llm_usage:")))


def api_config(model: Optional[str]) -> Tuple[str, str, str, str, int]:
    requested_model = model or os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_MODEL") or DEFAULT_MODEL
    selected_model = preferred_model(requested_model)
    call_model = str(requested_model) if is_llm_selector(requested_model) else selected_model
    timeout = int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    return "", "", call_model, selected_model, timeout


def compact_summary(summary: dict) -> dict:
    return {
        "metadata": summary.get("metadata", {}),
        "overview": summary.get("overview", {}),
        "critical_alarm_candidates": (summary.get("critical_alarm_candidates") or [])[:50],
        "critical_traps": (summary.get("critical_traps") or [])[:20],
        "important_trap_candidates": (summary.get("important_trap_candidates") or summary.get("important_traps") or [])[:20],
        "open_incidents": (summary.get("open_incidents") or [])[:50],
        "baseline_deviations": (summary.get("baseline_deviations") or [])[:30],
        "new_anomalies": (summary.get("new_anomalies") or [])[:30],
        "flapping_objects": (summary.get("flapping_objects") or [])[:30],
        "multi_device_correlations": (summary.get("multi_device_correlations") or [])[:30],
        "noise_candidates": (summary.get("noise_candidates") or [])[:20],
        "user_rule_hits": (summary.get("user_rule_hits") or [])[:80],
        "data_quality": summary.get("data_quality", {}),
    }


def build_system_prompt() -> str:
    return """
Trap topology rules:
- Never treat trap_sender_ip, collector_source_ip, source_ip from a Trap relay, or 172.25.131.3 as the faulty device.
- If a Trap has matched_link or topology_match=true, analyze it as a topology link with source_device/source_interface and target_device/target_interface.
- If only managed_object_name is known, describe that object; do not invent managed_device_ip.
- If a Trap has alarm_name, alarm_fault_reason, or alarm_suggestion from the private alarm definition library, use it as semantic context only and verify it against alarm_events, syslog evidence, and topology.
- recovered, Clear, Resume, Up, or 恢复 Trap records should not be described as unrecovered faults unless other current evidence proves the fault is still active.
- If topology matching fails, put the Trap in insufficient or watch with the missing topology evidence.
你是城域网 AIOps 轻量分析 Agent。
你不是 Markdown 报告生成器。
你只能基于 current_window_summary 和工具返回结果分析。
你不能编造设备、链路、接口、业务影响。
你不能直接生成 ES DSL 或 SQL。
你只能通过可用工具查询更多证据。

你需要判断：哪些必须处置、哪些持续观察、哪些可能是长期噪声、哪些已经恢复、哪些数据不足、哪些存在多设备关联或公共服务异常。

优先调查：
1. critical_alarm_candidates
2. open_incidents
3. critical_traps / important_trap_candidates
4. multi_device_correlations
5. flapping_objects
6. new_anomalies
7. baseline_deviations
8. noise_candidates

必须遵守：
- 每个 must_handle 结论至少需要 2 条证据。
- 如果证据不足，放入 insufficient。
- 如果存在 critical_alarm_candidates，最终 JSON 必须逐条覆盖；可以归入 must_handle、watch 或 insufficient，但不能完全忽略。
- 当前窗口 Trap 已由上游过滤为紧急/重要；即使 Trap 未完成 MIB 翻译，也必须覆盖，证据不足时放入 insufficient。
- 当前窗口每个重要 Trap 候选最终必须落入 must_handle、watch、recovered 或 insufficient。
- Trap 身份必须优先使用 managed_device_ip / managed_device_name；不得把 trap_sender_ip、collector_source_ip 或 relay IP 当成故障设备。
- 如果 Trap 没有 managed_device_ip，只能按 managed_object_name、endpoint_device_names、matched_link 或 managed_device_name 表述，不能声称 trap_sender_ip 对应设备故障。
- Trap sender/relay IP 只能写入 data_quality；设备身份不确定的 Trap 放入 insufficient。
- 告警定义库的 suggestion 不能机械照抄为结论，必须结合 related_alarm_events、syslog、topology 后再给处置建议。
- 未恢复接口 Down、物理 Down、Line protocol Down、光路、板卡、风扇、电源、温度类告警不得被 PPP、PTP 等长期噪声挤掉。
- 不要把所有高频事件都判定为严重故障。
- 对长期稳定、低于基线、无 open 状态的事件，可判为 noise 或 watch。
- 如果 current_window_summary 包含 user_rule_hits，最终 JSON 必须解释这些用户规则如何影响结论；降噪规则触发 safety_exception 时不能屏蔽重大故障。
- 输出必须是合法 JSON。
- 不输出 Markdown，不要在 JSON 外输出说明文字。
- 首选调用 investigate_candidates 批量调查 Top 候选；如果 summary 没有候选项，可以直接输出 normal。
""".strip()


def final_json_schema_text() -> str:
    return """
最终 JSON 必须包含这些字段，所有数组即使为空也必须存在：
{
  "metadata": {"analysis_time": "...", "window_start": "...", "window_end": "...", "model": "...", "tool_call_count": 0, "data_sources": ["current_window_summary", "ai_tools"]},
  "overall_status": {"level": "critical|major|minor|normal|unknown", "title": "...", "summary": "不超过150字"},
  "summary_cards": [{"name": "...", "value": 0, "level": "normal|minor|major|critical", "description": "..."}],
  "must_handle": [{"title": "...", "severity": "critical|major|minor", "confidence": 0.0, "device_ip": "...", "device_name": "...", "object_key": "...", "event_types": ["..."], "root_cause_hypothesis": "...", "evidence": ["证据1", "证据2"], "impact": "...", "recommended_actions": ["动作1"], "missing_data": []}],
  "watch": [{"title": "...", "reason": "...", "evidence": [], "next_check": "..."}],
  "noise": [{"title": "...", "reason": "...", "confidence": 0.0, "suggested_policy": "ignore_for_now|watch_trend|suppress_candidate"}],
  "recovered": [{"title": "...", "reason": "...", "evidence": []}],
  "insufficient": [{"title": "...", "reason": "...", "needed_data": []}],
  "correlations": [{"title": "...", "correlation_type": "same_device|same_interface|same_server|same_peer|same_time_window|topology", "devices": [], "object_key": "...", "evidence": [], "conclusion": "..."}],
  "next_actions": [{"priority": "P1|P2|P3", "action": "...", "owner_hint": "网管/传输/接入/系统/待定", "reason": "..."}],
  "user_rule_hits": [{"rule_id": 0, "raw_text": "...", "matched_target": "...", "action_result": "boosted|suppressed|downgrade_blocked_by_safety_exception", "safety_exception": []}],
  "data_quality": {"issues": [], "notes": []}
}
""".strip()


def build_initial_messages(summary: dict, model_name: str) -> List[dict]:
    user_payload = {
        "task": "基于 current_window_summary 进行 AIOps 轻量分析",
        "instructions": [
            "先判断是否需要调用工具调查候选项",
            "优先使用 investigate_candidates 批量调查 critical_alarm_candidates 和 Top 候选",
            "如果存在 critical_alarm_candidates 或重要 Trap，最终 JSON 必须覆盖，不能忽略",
            "如果存在 user_rule_hits，最终结果必须包含 user_rule_hits，并在对应结论或 data_quality 中说明规则影响",
            "Trap 未翻译时应放入 insufficient 或 watch，不要当成无关噪声",
            "Trap alarm_name/fault_reason/suggestion 只作为语义辅助，必须结合工具证据判断",
            "Trap 分析只能把 managed_device_ip / managed_device_name 作为故障设备身份，不得把 trap_sender_ip / relay IP 当作故障设备",
            "managed_device_ip 缺失时按 managed_object_name、endpoint_device_names、matched_link 或 managed_device_name 描述，身份不确定时放入 insufficient 并在 data_quality 说明",
            "恢复类 Trap 优先归入 recovered 或 watch，除非其他证据显示故障仍未恢复",
            "不要自由查询无关数据",
            "最多只选择 3~5 个最值得调查的候选",
            "最终输出结构化 JSON",
        ],
        "model": model_name,
        "final_json_schema": final_json_schema_text(),
        "current_window_summary": compact_summary(summary),
    }
    return [{"role": "system", "content": build_system_prompt()}, {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}]


def call_chat(messages: List[dict], model: str, api_key: str, base_url: str, timeout: int, temperature: float, tools: Optional[List[dict]]) -> Any:
    result = call_llm(messages, model=model, temperature=temperature, timeout=None, tools=tools)
    setattr(result.response, "_aiops_llm_provider", result.provider)
    setattr(result.response, "_aiops_llm_model", result.model)
    setattr(result.response, "_aiops_llm_duration_ms", result.duration_ms)
    return result.response


def response_usage(response: Any) -> dict:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    prompt_cache_hit = getattr(usage, "prompt_cache_hit_tokens", None)
    prompt_cache_miss = getattr(usage, "prompt_cache_miss_tokens", None)
    details = getattr(usage, "prompt_tokens_details", None)
    if prompt_cache_hit is None and details is not None:
        prompt_cache_hit = getattr(details, "cached_tokens", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "prompt_cache_hit_tokens": prompt_cache_hit,
        "prompt_cache_miss_tokens": prompt_cache_miss,
    }


def finish_reason(response: Any) -> Optional[str]:
    try:
        return getattr(response.choices[0], "finish_reason", None)
    except Exception:
        return None


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    prompt_price = float(os.getenv("LIGHT_AGENT_PROMPT_PRICE_PER_1M", "0") or 0)
    completion_price = float(os.getenv("LIGHT_AGENT_COMPLETION_PRICE_PER_1M", "0") or 0)
    return round((prompt_tokens / 1_000_000) * prompt_price + (completion_tokens / 1_000_000) * completion_price, 6)


def assistant_message(response: Any) -> Any:
    return response.choices[0].message


def tool_calls_from_message(message: Any) -> List[Any]:
    return list(getattr(message, "tool_calls", None) or [])


def safe_json_loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some OpenAI-compatible reasoning models occasionally close the root
        # object one brace too early and then continue with the next top-level
        # field. Repair only that narrowly detectable pattern; all other invalid
        # output still goes through the normal model-based repair flow.
        candidate = text
        for _ in range(4):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                prefix = candidate[: exc.pos].rstrip()
                suffix = candidate[exc.pos :].lstrip()
                if not (prefix.endswith("}") and suffix.startswith(",")):
                    return None
                candidate = prefix[:-1] + suffix
        return None
    except (TypeError, ValueError):
        return None


def parse_tool_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    parsed = safe_json_loads(str(raw))
    return parsed if isinstance(parsed, dict) else {}


def parse_pseudo_tool_call(content: str) -> Optional[dict]:
    parsed = safe_json_loads(content.strip())
    if isinstance(parsed, dict) and parsed.get("action") == "tool_call" and parsed.get("tool_name"):
        arguments = parsed.get("arguments") or {}
        if isinstance(arguments, dict):
            return {"tool_name": parsed["tool_name"], "arguments": arguments}
    return None


def truncate_tool_result(result: dict) -> dict:
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return result
    compact = {"ok": result.get("ok"), "tool_name": result.get("tool_name"), "truncated": True, "note": "tool result exceeded size limit and was truncated before sending back to model"}
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    if isinstance(payload, dict):
        compact["result"] = {
            "metadata": compact_value(payload.get("metadata") or {}, depth=1),
            "investigations": [compact_investigation(item) for item in (payload.get("investigations") or [])[:3]],
            "data_quality": compact_value(payload.get("data_quality", {}), depth=1),
        }
    compact_text = json.dumps(compact, ensure_ascii=False)
    if len(compact_text) > MAX_TOOL_RESULT_SUMMARY_CHARS:
        compact["result"] = compact_value(compact.get("result") or {}, depth=2, list_limit=2, text_limit=240)
    return compact


def short_text(value: Any, max_chars: int = 360) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value or "")
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def compact_value(value: Any, *, depth: int = 2, list_limit: int = 3, text_limit: int = 360) -> Any:
    if depth <= 0:
        return short_text(value, text_limit)
    if isinstance(value, dict):
        return {str(key): compact_value(item, depth=depth - 1, list_limit=list_limit, text_limit=text_limit) for key, item in list(value.items())[:12]}
    if isinstance(value, list):
        return [compact_value(item, depth=depth - 1, list_limit=list_limit, text_limit=text_limit) for item in value[:list_limit]]
    if isinstance(value, str):
        return short_text(value, text_limit)
    return value


def compact_event(row: Any) -> Any:
    if not isinstance(row, dict):
        return compact_value(row, depth=1)
    return {
        key: compact_value(row.get(key), depth=1)
        for key in (
            "event_type",
            "device_name",
            "device_ip",
            "object_key",
            "first_seen",
            "last_seen",
            "event_count",
            "event_status",
            "severity_max",
            "event_summary",
            "alarm_name",
            "alarm_lifecycle_status",
            "trap_oid_name",
            "managed_object_name",
        )
        if row.get(key) not in (None, "", [])
    }


def compact_investigation(item: Any) -> Any:
    if not isinstance(item, dict):
        return compact_value(item, depth=2)
    candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
    identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
    baseline = item.get("baseline") if isinstance(item.get("baseline"), dict) else {}
    topology = item.get("topology_context") if isinstance(item.get("topology_context"), dict) else {}
    return {
        "candidate_type": item.get("candidate_type"),
        "candidate": {
            key: compact_value(candidate.get(key), depth=1)
            for key in (
                "event_type",
                "device_name",
                "device_ip",
                "object_key",
                "alarm_name",
                "alarm_lifecycle_status",
                "alarm_severity",
                "managed_object_name",
                "event_count",
                "summary",
                "event_summary",
                "trap_oid_name",
            )
            if candidate.get(key) not in (None, "", [])
        },
        "identity": {
            key: identity.get(key)
            for key in (
                "device_name",
                "device_ip",
                "managed_device_name",
                "managed_device_ip",
                "managed_object_name",
                "device_identity_source",
                "device_identity_confidence",
                "object_key",
            )
            if identity.get(key) not in (None, "", [])
        },
        "baseline": {
            key: baseline.get(key)
            for key in ("current_count", "historical_count", "baseline_avg_for_window", "delta")
            if baseline.get(key) not in (None, "")
        },
        "related_current_events": [compact_event(row) for row in (item.get("related_current_events") or [])[:2]],
        "related_alarm_events": [compact_event(row) for row in (item.get("related_alarm_events") or [])[:2]],
        "related_traps": [compact_event(row) for row in (item.get("related_traps") or [])[:2]],
        "topology_context": {
            "matched_devices": [compact_value(row, depth=1) for row in (topology.get("matched_devices") or [])[:2]],
            "related_links": [compact_value(row, depth=1) for row in (topology.get("related_links") or [])[:2]],
        },
        "ai_memory": compact_value(item.get("ai_memory") or {}, depth=1),
    }


def execute_tool_call(tool_name: str, arguments: dict, summary: dict) -> dict:
    arguments = dict(arguments)
    if tool_name == "investigate_candidates" and ("summary" not in arguments or str(arguments.get("summary_json") or "").startswith("/dev/")):
        arguments = dict(arguments)
        arguments.pop("summary_json", None)
        arguments["summary"] = summary
    scope_ips = (summary.get("metadata") or {}).get("platform_scope_device_ips")
    if scope_ips is not None:
        arguments["allowed_device_ips"] = scope_ips
    arguments["limit"] = min(int(arguments.get("limit") or DEFAULT_AGENT_TOOL_LIMIT), DEFAULT_AGENT_TOOL_LIMIT)
    if tool_name == "investigate_candidates":
        arguments["max_candidates"] = min(int(arguments.get("max_candidates") or DEFAULT_AGENT_TOOL_LIMIT), DEFAULT_AGENT_TOOL_LIMIT)
    LOGGER.info("Agent tool call: name=%s argument_keys=%s", tool_name, sorted(arguments.keys()))
    result = execute_ai_tool(tool_name, arguments)
    LOGGER.info("Agent tool result: name=%s ok=%s error=%s", tool_name, result.get("ok"), (result.get("error") or {}).get("type"))
    return truncate_tool_result(result)


def tool_call_signature(tool_name: str, arguments: dict) -> str:
    normalized = arguments
    try:
        normalized = {key: value for key, value in arguments.items() if key not in {"summary", "summary_json"}}
    except Exception:
        normalized = {}
    return "%s:%s" % (tool_name, json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str))


def duplicate_tool_result(tool_name: str) -> dict:
    return {
        "ok": True,
        "tool_name": tool_name,
        "duplicate": True,
        "note": "same tool call already executed in this agent run; use the previous tool_result and produce final JSON without another tool call",
    }


def result_item_count(result: dict) -> int:
    payload = result.get("result") if isinstance(result, dict) else None
    if isinstance(payload, dict):
        for key in ("investigations", "events", "records", "related_links", "matched_devices"):
            if isinstance(payload.get(key), list):
                return len(payload[key])
    return 0


def append_standard_tool_messages(messages: List[dict], assistant: Any, tool_results: List[Tuple[Any, dict]]) -> None:
    assistant_entry = {"role": "assistant", "content": getattr(assistant, "content", None) or "", "tool_calls": []}
    reasoning_content = assistant_reasoning_content(assistant)
    if reasoning_content:
        assistant_entry["reasoning_content"] = reasoning_content
    for call, _result in tool_results:
        function = getattr(call, "function", None)
        assistant_entry["tool_calls"].append({"id": getattr(call, "id", ""), "type": "function", "function": {"name": getattr(function, "name", ""), "arguments": getattr(function, "arguments", "{}")}})
    messages.append(assistant_entry)
    for call, result in tool_results:
        messages.append({"role": "tool", "tool_call_id": getattr(call, "id", ""), "content": json.dumps(result, ensure_ascii=False)})


def assistant_reasoning_content(message: Any) -> Optional[str]:
    reasoning_content = getattr(message, "reasoning_content", None)
    if reasoning_content:
        return reasoning_content
    model_extra = getattr(message, "model_extra", None)
    if isinstance(model_extra, dict):
        extra_reasoning = model_extra.get("reasoning_content")
        if extra_reasoning:
            return str(extra_reasoning)
    return None


def extract_json_block(content: str) -> Optional[str]:
    match = re.search(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", content, re.DOTALL)
    if match:
        return match.group(1)
    start = content.find("{")
    end = content.rfind("}")
    return content[start : end + 1] if start >= 0 and end > start else None


def parse_agent_json(content: str) -> Optional[dict]:
    parsed = safe_json_loads(content.strip())
    if isinstance(parsed, dict):
        return parsed
    block = extract_json_block(content)
    if block:
        parsed = safe_json_loads(block)
        if isinstance(parsed, dict):
            return parsed
    return None


def save_raw_debug(content: str, output_dir: Optional[str] = None) -> str:
    debug_dir = pathlib.Path(output_dir) if output_dir else RAW_DEBUG_DIR
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / ("light-agent-raw-%s.txt" % utc_now().strftime("%Y%m%d-%H%M%S"))
    path.write_text(content or "", encoding="utf-8")
    return str(path)


def repair_agent_json(content: str, messages: List[dict], model: str, api_key: str, base_url: str, timeout: int, temperature: float) -> Tuple[Optional[dict], str]:
    repair_messages = list(messages)
    repair_messages.append({"role": "assistant", "content": content or ""})
    repair_messages.append({"role": "user", "content": "上一条回复不是合法 JSON。请只返回符合指定 schema 的合法 JSON，不要 Markdown，不要解释。"})
    response = call_chat(repair_messages, model, api_key, base_url, timeout, temperature, tools=None)
    repaired = assistant_message(response).content or ""
    return parse_agent_json(repaired), repaired


def ensure_output_shape(result: dict, summary: dict, model: str, tool_call_count: int) -> dict:
    metadata = result.setdefault("metadata", {})
    metadata.setdefault("analysis_time", iso_z(utc_now()))
    metadata.setdefault("window_start", summary.get("metadata", {}).get("window_start"))
    metadata.setdefault("window_end", summary.get("metadata", {}).get("window_end"))
    metadata.setdefault("model", model)
    metadata["tool_call_count"] = tool_call_count
    metadata.setdefault("data_sources", ["current_window_summary", "ai_tools"])
    result.setdefault("overall_status", {"level": "unknown", "title": "分析结果未知", "summary": "AI 未返回完整总体状态。"})
    for field in REQUIRED_ARRAY_FIELDS:
        if not isinstance(result.get(field), list):
            result[field] = []
    if not isinstance(result.get("user_rule_hits"), list):
        result["user_rule_hits"] = summary.get("user_rule_hits") or []
    data_quality = result.setdefault("data_quality", {})
    data_quality.setdefault("issues", [])
    data_quality.setdefault("notes", [])
    return result


def force_final_messages(messages: List[dict]) -> List[dict]:
    final_messages = list(messages)
    final_messages.append({"role": "user", "content": "工具调用轮次已达到上限。请基于已有 current_window_summary 和 tool_result，立即只输出最终合法 JSON。" + final_json_schema_text()})
    return final_messages


def run_light_agent(summary: dict, *, max_tool_rounds: int = 4, model: Optional[str] = None, temperature: float = 0.1, env_file: Optional[str] = None, debug_dir: Optional[str] = None) -> dict:
    load_env(env_file)
    start_time = utc_now()
    start_ms = monotonic_ms()
    trajectory_dir = create_trajectory_dir(debug_dir)
    runtime = {
        "model": model,
        "start_time": iso_z(start_time),
        "end_time": None,
        "duration_ms": None,
        "tool_call_rounds": 0,
        "tool_calls": [],
        "llm_calls": [],
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "trajectory_dir": str(trajectory_dir),
    }
    seen_tool_signatures: set[str] = set()
    write_json(trajectory_dir / "summary_input.json", summary)
    try:
        api_key, base_url, call_model, selected_model, timeout = api_config(model)
    except Exception as exc:
        runtime["end_time"] = iso_z(utc_now())
        runtime["duration_ms"] = monotonic_ms() - start_ms
        result = {"ok": False, "error": "agent_config_error", "message": str(exc), "agent_runtime": runtime}
        write_json(trajectory_dir / "final_result.json", result)
        write_json(trajectory_dir / "runtime_metrics.json", runtime)
        return result

    messages = build_initial_messages(summary, selected_model)
    tools = get_tool_schemas()
    write_json(trajectory_dir / "tool_schemas.json", tools)
    runtime["model"] = selected_model
    if call_model != selected_model:
        runtime["model_selector"] = call_model
    tool_call_count = 0
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    summary_size = len(json.dumps(compact_summary(summary), ensure_ascii=False).encode("utf-8"))
    LOGGER.info("Light agent start: model=%s max_tool_rounds=%s summary_size_bytes=%s tool_schema_count=%s", selected_model, max_tool_rounds, summary_size, len(tools))

    content = ""
    for round_index in range(max_tool_rounds + 1):
        allow_tools = round_index < max_tool_rounds and tool_call_count < max_tool_rounds
        llm_round = len(runtime["llm_calls"]) + 1
        write_json(trajectory_dir / ("messages_round_%s.json" % llm_round), messages)
        call_start = monotonic_ms()
        try:
            response = call_chat(messages, call_model, api_key, base_url, timeout, temperature, tools if allow_tools else None)
        except Exception as exc:
            LOGGER.exception("Light agent AI call failed")
            runtime["end_time"] = iso_z(utc_now())
            runtime["duration_ms"] = monotonic_ms() - start_ms
            result = {"ok": False, "error": "agent_ai_call_failed", "message": str(exc), "metadata": {"model": selected_model, "tool_call_count": tool_call_count}, "agent_runtime": runtime}
            write_json(trajectory_dir / "final_result.json", result)
            write_json(trajectory_dir / "runtime_metrics.json", runtime)
            return result
        call_duration = monotonic_ms() - call_start
        actual_provider = getattr(response, "_aiops_llm_provider", None)
        actual_model = getattr(response, "_aiops_llm_model", selected_model)
        if actual_model:
            runtime["model"] = actual_model
        usage = response_usage(response)
        runtime["llm_calls"].append(
            {
                "round": llm_round,
                "provider": actual_provider,
                "model": actual_model,
                "duration_ms": call_duration,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
                "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
                "assistant_finish_reason": finish_reason(response),
                "messages_count": len(messages),
                "messages_size_bytes": json_size_bytes(messages),
            }
        )
        for key in usage_totals:
            if usage.get(key):
                usage_totals[key] += int(usage[key] or 0)
        runtime["total_prompt_tokens"] = usage_totals["prompt_tokens"]
        runtime["total_completion_tokens"] = usage_totals["completion_tokens"]
        runtime["total_tokens"] = usage_totals["total_tokens"]
        runtime["estimated_cost_usd"] = estimate_cost_usd(runtime["total_prompt_tokens"], runtime["total_completion_tokens"])
        if usage.get("total_tokens") and usage["total_tokens"] > int(os.getenv("LIGHT_AGENT_TOKEN_WARNING_THRESHOLD", "60000")):
            LOGGER.warning("Light agent high token usage in one call: %s", usage)
        if call_duration > int(os.getenv("LIGHT_AGENT_DURATION_WARNING_MS", "180000")):
            LOGGER.warning("Light agent LLM call was slow: round=%s duration_ms=%s", llm_round, call_duration)
        assistant = assistant_message(response)
        content = assistant.content or ""
        standard_tool_calls = tool_calls_from_message(assistant) if allow_tools else []
        if standard_tool_calls:
            tool_results = []
            for call in standard_tool_calls:
                function = getattr(call, "function", None)
                tool_name = getattr(function, "name", "")
                arguments = parse_tool_arguments(getattr(function, "arguments", "{}"))
                if tool_call_count >= max_tool_rounds:
                    tool_result = {"ok": False, "tool_name": tool_name, "error": {"type": "max_tool_rounds_exceeded", "message": "tool call limit reached"}}
                else:
                    signature = tool_call_signature(tool_name, arguments)
                    if signature in seen_tool_signatures:
                        tool_start = monotonic_ms()
                        tool_result = duplicate_tool_result(tool_name)
                        tool_duration = monotonic_ms() - tool_start
                        tool_call_count += 1
                    else:
                        seen_tool_signatures.add(signature)
                        tool_start = monotonic_ms()
                        tool_result = execute_tool_call(tool_name, arguments, summary)
                        tool_duration = monotonic_ms() - tool_start
                        tool_call_count += 1
                    tool_metric = {
                        "round": tool_call_count,
                        "tool_name": tool_name,
                        "duration_ms": tool_duration,
                        "result_size_bytes": json_size_bytes(tool_result),
                        "result_item_count": result_item_count(tool_result),
                        "ok": tool_result.get("ok"),
                    }
                    runtime["tool_calls"].append(tool_metric)
                    runtime["tool_call_rounds"] = tool_call_count
                    write_json(trajectory_dir / ("tool_result_round_%s.json" % tool_call_count), {"arguments": arguments, "result": tool_result, "metric": tool_metric})
                tool_results.append((call, tool_result))
            append_standard_tool_messages(messages, assistant, tool_results)
            continue

        pseudo = parse_pseudo_tool_call(content) if allow_tools else None
        if pseudo:
            if tool_call_count >= max_tool_rounds:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": json.dumps({"tool_result": {"ok": False, "tool_name": pseudo["tool_name"], "error": {"type": "max_tool_rounds_exceeded", "message": "tool call limit reached"}}}, ensure_ascii=False)})
                continue
            pseudo_arguments = pseudo.get("arguments") or {}
            signature = tool_call_signature(pseudo["tool_name"], pseudo_arguments)
            if signature in seen_tool_signatures:
                tool_start = monotonic_ms()
                result = duplicate_tool_result(pseudo["tool_name"])
                tool_duration = monotonic_ms() - tool_start
                tool_call_count += 1
            else:
                seen_tool_signatures.add(signature)
                tool_start = monotonic_ms()
                result = execute_tool_call(pseudo["tool_name"], pseudo_arguments, summary)
                tool_duration = monotonic_ms() - tool_start
                tool_call_count += 1
            tool_metric = {
                "round": tool_call_count,
                "tool_name": pseudo["tool_name"],
                "duration_ms": tool_duration,
                "result_size_bytes": json_size_bytes(result),
                "result_item_count": result_item_count(result),
                "ok": result.get("ok"),
            }
            runtime["tool_calls"].append(tool_metric)
            runtime["tool_call_rounds"] = tool_call_count
            write_json(trajectory_dir / ("tool_result_round_%s.json" % tool_call_count), {"arguments": pseudo_arguments, "result": result, "metric": tool_metric})
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": json.dumps({"tool_result": result}, ensure_ascii=False)})
            continue

        parsed = parse_agent_json(content)
        if parsed is not None:
            LOGGER.info("Light agent final JSON parsed successfully: tool_call_count=%s", tool_call_count)
            write_text(trajectory_dir / "final_response_raw.txt", content)
            parsed = ensure_output_shape(parsed, summary, selected_model, tool_call_count)
            parsed.setdefault("metadata", {})["llm_provider"] = actual_provider
            parsed.setdefault("metadata", {})["model"] = actual_model or selected_model
            parsed.setdefault("metadata", {})["usage"] = usage_totals
            runtime["end_time"] = iso_z(utc_now())
            runtime["duration_ms"] = monotonic_ms() - start_ms
            parsed["agent_runtime"] = runtime
            parsed.setdefault("metadata", {})["trajectory_dir"] = str(trajectory_dir)
            write_json(trajectory_dir / "final_result.json", parsed)
            write_json(trajectory_dir / "runtime_metrics.json", runtime)
            LOGGER.info("Light agent end: duration_ms=%s total_tokens=%s tool_calls=%s", runtime["duration_ms"], runtime["total_tokens"], runtime["tool_call_rounds"])
            return parsed

        if round_index >= max_tool_rounds:
            break
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "请不要继续解释。请只输出最终合法 JSON。" + final_json_schema_text()})

    forced_messages = force_final_messages(messages)
    llm_round = len(runtime["llm_calls"]) + 1
    write_json(trajectory_dir / ("messages_round_%s.json" % llm_round), forced_messages)
    call_start = monotonic_ms()
    try:
        response = call_chat(forced_messages, call_model, api_key, base_url, timeout, temperature, tools=None)
    except Exception as exc:
        LOGGER.exception("Light agent final AI call failed")
        runtime["end_time"] = iso_z(utc_now())
        runtime["duration_ms"] = monotonic_ms() - start_ms
        result = {"ok": False, "error": "agent_ai_call_failed", "message": str(exc), "metadata": {"model": selected_model, "tool_call_count": tool_call_count}, "agent_runtime": runtime}
        write_json(trajectory_dir / "final_result.json", result)
        write_json(trajectory_dir / "runtime_metrics.json", runtime)
        return result
    call_duration = monotonic_ms() - call_start
    actual_provider = getattr(response, "_aiops_llm_provider", None)
    actual_model = getattr(response, "_aiops_llm_model", selected_model)
    if actual_model:
        runtime["model"] = actual_model
    usage = response_usage(response)
    for key in usage_totals:
        if usage.get(key):
            usage_totals[key] += int(usage[key] or 0)
    runtime["total_prompt_tokens"] = usage_totals["prompt_tokens"]
    runtime["total_completion_tokens"] = usage_totals["completion_tokens"]
    runtime["total_tokens"] = usage_totals["total_tokens"]
    runtime["estimated_cost_usd"] = estimate_cost_usd(runtime["total_prompt_tokens"], runtime["total_completion_tokens"])
    runtime["llm_calls"].append(
        {
            "round": llm_round,
            "provider": actual_provider,
            "model": actual_model,
            "duration_ms": call_duration,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
            "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
            "assistant_finish_reason": finish_reason(response),
            "messages_count": len(forced_messages),
            "messages_size_bytes": json_size_bytes(forced_messages),
        }
    )
    content = assistant_message(response).content or ""
    parsed = parse_agent_json(content)
    if parsed is None:
        parsed, content = repair_agent_json(content, forced_messages, call_model, api_key, base_url, timeout, temperature)
    if parsed is not None:
        LOGGER.info("Light agent final JSON parsed after force/repair: tool_call_count=%s", tool_call_count)
        write_text(trajectory_dir / "final_response_raw.txt", content)
        parsed = ensure_output_shape(parsed, summary, selected_model, tool_call_count)
        parsed.setdefault("metadata", {})["llm_provider"] = actual_provider
        parsed.setdefault("metadata", {})["model"] = actual_model or selected_model
        parsed.setdefault("metadata", {})["usage"] = usage_totals
        runtime["end_time"] = iso_z(utc_now())
        runtime["duration_ms"] = monotonic_ms() - start_ms
        parsed["agent_runtime"] = runtime
        parsed.setdefault("metadata", {})["trajectory_dir"] = str(trajectory_dir)
        write_json(trajectory_dir / "final_result.json", parsed)
        write_json(trajectory_dir / "runtime_metrics.json", runtime)
        return parsed

    raw_path = save_raw_debug(content, debug_dir)
    LOGGER.error("Light agent final JSON parse failed; raw saved to %s", raw_path)
    runtime["end_time"] = iso_z(utc_now())
    runtime["duration_ms"] = monotonic_ms() - start_ms
    result = {"ok": False, "error": "invalid_agent_json", "raw_content_path": raw_path, "agent_runtime": runtime}
    write_json(trajectory_dir / "final_result.json", result)
    write_json(trajectory_dir / "runtime_metrics.json", runtime)
    return result
