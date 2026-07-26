#!/usr/bin/env python3
"""Build current_window_summary JSON for the lightweight AIOps agent."""

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

from aiops.context.current_window_summary import SummaryConfig, SummaryLimits, build_current_window_summary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--hours", type=int, default=int(os.getenv("CURRENT_WINDOW_HOURS", "7")))
    parser.add_argument("--baseline-days", type=int, default=int(os.getenv("CURRENT_WINDOW_BASELINE_DAYS", "7")))
    parser.add_argument("--syslog-index", default=os.getenv("SYSLOG_PARSED_INDEX", "jscn-aiops-syslog-parsed-*"))
    parser.add_argument("--trap-index", default=os.getenv("TRAP_RAW_INDEX", "jscn-aiops-trap-raw-*"))
    parser.add_argument("--event-index", default=os.getenv("ALARM_EVENTS_INDEX", "jscn-aiops-alarm-events-*"))
    parser.add_argument("--output", default=os.getenv("CURRENT_WINDOW_SUMMARY_OUTPUT", "outputs/current_window_summary.json"))
    parser.add_argument("--env-file", default=os.getenv("AIOPS_ENV_FILE"))
    parser.add_argument("--critical-alarm-candidates-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_CRITICAL_ALARM_CANDIDATES_LIMIT", "50")))
    parser.add_argument("--critical-traps-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_CRITICAL_TRAPS_LIMIT", "20")))
    parser.add_argument("--important-traps-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_IMPORTANT_TRAPS_LIMIT", "20")))
    parser.add_argument("--open-incidents-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_OPEN_INCIDENTS_LIMIT", "50")))
    parser.add_argument("--baseline-deviations-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_BASELINE_DEVIATIONS_LIMIT", "30")))
    parser.add_argument("--new-anomalies-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_NEW_ANOMALIES_LIMIT", "30")))
    parser.add_argument("--flapping-objects-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_FLAPPING_OBJECTS_LIMIT", "30")))
    parser.add_argument("--multi-device-correlations-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_MULTI_DEVICE_CORRELATIONS_LIMIT", "30")))
    parser.add_argument("--noise-candidates-limit", type=int, default=int(os.getenv("CURRENT_SUMMARY_NOISE_CANDIDATES_LIMIT", "20")))
    parser.add_argument("--event-scan-size", type=int, default=int(os.getenv("CURRENT_SUMMARY_EVENT_SCAN_SIZE", "5000")))
    parser.add_argument("--trap-scan-size", type=int, default=int(os.getenv("CURRENT_SUMMARY_TRAP_SCAN_SIZE", "500")))
    parser.add_argument("--log-level", default=os.getenv("CURRENT_SUMMARY_LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    limits = SummaryLimits(
        critical_alarm_candidates=args.critical_alarm_candidates_limit,
        critical_traps=args.critical_traps_limit,
        important_traps=args.important_traps_limit,
        open_incidents=args.open_incidents_limit,
        baseline_deviations=args.baseline_deviations_limit,
        new_anomalies=args.new_anomalies_limit,
        flapping_objects=args.flapping_objects_limit,
        multi_device_correlations=args.multi_device_correlations_limit,
        noise_candidates=args.noise_candidates_limit,
        event_scan_size=args.event_scan_size,
        trap_scan_size=args.trap_scan_size,
    )
    config = SummaryConfig(
        es_url=args.es_url,
        hours=args.hours,
        baseline_days=args.baseline_days,
        syslog_index=args.syslog_index,
        trap_index=args.trap_index,
        event_index=args.event_index,
        env_file=args.env_file,
        limits=limits,
    )
    summary = build_current_window_summary(config)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "syslog_total": summary["overview"]["syslog_total"],
                "trap_total": summary["overview"]["trap_total"],
                "alarm_event_total": summary["overview"]["alarm_event_total"],
                "critical_alarm_candidates": len(summary["critical_alarm_candidates"]),
                "open_incidents": len(summary["open_incidents"]),
                "baseline_deviations": len(summary["baseline_deviations"]),
                "flapping_objects": len(summary["flapping_objects"]),
                "multi_device_correlations": len(summary["multi_device_correlations"]),
                "noise_candidates": len(summary["noise_candidates"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
