#!/usr/bin/env python3
"""Build bounded investigation context for current-window candidates."""

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

from aiops.tools.investigation import InvestigationConfig, InvestigationLimits, investigate_candidates  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-json", default=os.getenv("CURRENT_WINDOW_SUMMARY_JSON", "outputs/current_window_summary.json"))
    parser.add_argument("--output", default=os.getenv("INVESTIGATION_CONTEXT_OUTPUT", "outputs/investigation_context.json"))
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--syslog-index", default=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"))
    parser.add_argument("--trap-index", default=os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"))
    parser.add_argument("--event-index", default=os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*"))
    parser.add_argument("--baseline-days", type=int, default=int(os.getenv("INVESTIGATION_BASELINE_DAYS", "7")))
    parser.add_argument("--before-minutes", type=int, default=int(os.getenv("INVESTIGATION_BEFORE_MINUTES", "30")))
    parser.add_argument("--after-minutes", type=int, default=int(os.getenv("INVESTIGATION_AFTER_MINUTES", "30")))
    parser.add_argument("--max-candidates", type=int, default=int(os.getenv("INVESTIGATION_MAX_CANDIDATES", "20")))
    parser.add_argument("--related-events-limit", type=int, default=int(os.getenv("INVESTIGATION_RELATED_EVENTS_LIMIT", "20")))
    parser.add_argument("--historical-events-limit", type=int, default=int(os.getenv("INVESTIGATION_HISTORICAL_EVENTS_LIMIT", "20")))
    parser.add_argument("--related-traps-limit", type=int, default=int(os.getenv("INVESTIGATION_RELATED_TRAPS_LIMIT", "20")))
    parser.add_argument("--topology-links-limit", type=int, default=int(os.getenv("INVESTIGATION_TOPOLOGY_LINKS_LIMIT", "30")))
    parser.add_argument("--ai-memory-limit", type=int, default=int(os.getenv("INVESTIGATION_AI_MEMORY_LIMIT", "5")))
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE"))
    parser.add_argument("--log-level", default=os.getenv("INVESTIGATION_LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    summary_path = pathlib.Path(args.summary_json)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    limits = InvestigationLimits(
        candidates=args.max_candidates,
        related_current_events=args.related_events_limit,
        historical_events=args.historical_events_limit,
        related_traps=args.related_traps_limit,
        topology_links=args.topology_links_limit,
        ai_memory=args.ai_memory_limit,
    )
    config = InvestigationConfig(
        es_url=args.es_url,
        syslog_index=args.syslog_index,
        trap_index=args.trap_index,
        event_index=args.event_index,
        baseline_days=args.baseline_days,
        before_minutes=args.before_minutes,
        after_minutes=args.after_minutes,
        env_file=args.env_file,
        limits=limits,
    )
    context = investigate_candidates(summary, config)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "candidate_count": context["metadata"]["candidate_count"],
                "investigations": len(context["investigations"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
