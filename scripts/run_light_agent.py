#!/usr/bin/env python3
"""Run the lightweight AIOps Agent and save structured JSON output."""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.agent.light_agent import run_light_agent  # noqa: E402
from aiops.agent.persistence import save_agent_result  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-tool-rounds", type=int, default=int(os.getenv("LIGHT_AGENT_MAX_TOOL_ROUNDS", "4")))
    parser.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_MODEL"))
    parser.add_argument("--temperature", type=float, default=float(os.getenv("LIGHT_AGENT_TEMPERATURE", "0.1")))
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE"))
    parser.add_argument("--debug-dir", default=os.getenv("LIGHT_AGENT_DEBUG_DIR", "outputs/debug"))
    parser.add_argument("--save-to-db", action="store_true")
    parser.add_argument("--summary-path", default=None)
    parser.add_argument("--result-path", default=None)
    parser.add_argument("--log-level", default=os.getenv("LIGHT_AGENT_LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    summary_path = pathlib.Path(args.summary_json)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    result = run_light_agent(
        summary,
        max_tool_rounds=args.max_tool_rounds,
        model=args.model,
        temperature=args.temperature,
        env_file=args.env_file,
        debug_dir=args.debug_dir,
    )
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.save_to_db:
        runtime = result.get("agent_runtime", {}) if isinstance(result, dict) else {}
        save_result = save_agent_result(
            result,
            summary_path=args.summary_path or str(summary_path),
            result_path=args.result_path or str(output),
            trajectory_dir=runtime.get("trajectory_dir"),
            env_file=args.env_file,
        )
        if not save_result.get("ok"):
            result.setdefault("metadata", {})["saved_to_db"] = False
            result.setdefault("metadata", {})["db_save_error"] = save_result.get("error")
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": False, "error": "save_to_db_failed", "detail": save_result}, ensure_ascii=False, indent=2))
            return 1
        metadata = result.setdefault("metadata", {})
        metadata.update(
            {
                "saved_to_db": True,
                "ai_run_id": save_result.get("run_id"),
                "ai_run_uid": save_result.get("run_uid"),
                "saved_finding_count": save_result.get("finding_count"),
            }
        )
        if isinstance(runtime, dict):
            runtime.update(
                {
                    "saved_to_db": True,
                    "ai_run_id": save_result.get("run_id"),
                    "ai_run_uid": save_result.get("run_uid"),
                    "saved_finding_count": save_result.get("finding_count"),
                }
            )
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runtime = result.get("agent_runtime", {}) if isinstance(result, dict) else {}
    if runtime:
        metrics_path = output.parent / "runtime_metrics.json"
        metrics_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    stats = {
        "summary_window": {
            "start": summary.get("metadata", {}).get("window_start"),
            "end": summary.get("metadata", {}).get("window_end"),
        },
        "model": metadata.get("model") or args.model,
        "tool_call_count": metadata.get("tool_call_count", 0),
        "final_finding_count": len(result.get("must_handle", [])) if isinstance(result, dict) else 0,
        "duration_ms": runtime.get("duration_ms"),
        "total_tokens": runtime.get("total_tokens"),
        "trajectory_dir": runtime.get("trajectory_dir"),
        "output": str(output),
        "runtime_metrics": str(output.parent / "runtime_metrics.json") if runtime else None,
        "saved_to_db": result.get("metadata", {}).get("saved_to_db"),
        "ai_run_id": result.get("metadata", {}).get("ai_run_id"),
        "ai_run_uid": result.get("metadata", {}).get("ai_run_uid"),
        "saved_finding_count": result.get("metadata", {}).get("saved_finding_count"),
        "ok": result.get("ok", True) if isinstance(result, dict) else False,
        "error": result.get("error") if isinstance(result, dict) else "invalid_result",
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["ok"] is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
