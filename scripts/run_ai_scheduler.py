#!/usr/bin/env python3
"""Run the scheduled AI analysis worker."""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.scheduler.ai_scheduler import run_due_tasks_once, scheduler_loop  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("AI_SCHEDULER_POLL_SECONDS", "60")))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-level", default=os.getenv("AI_SCHEDULER_LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.once:
        results = run_due_tasks_once()
        for result in results:
            print({"ok": result.ok, "run_uid": result.run_uid, "status": result.status, "error": result.error})
        return 0 if all(result.ok for result in results) else 1
    scheduler_loop(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
