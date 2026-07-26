#!/usr/bin/env python3
"""Add operator feedback to an AI finding."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.agent.persistence import VALID_FEEDBACK_TYPES, save_ai_finding_feedback  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--finding-id", type=int, required=True)
    parser.add_argument("--feedback-type", required=True, choices=sorted(VALID_FEEDBACK_TYPES))
    parser.add_argument("--actual-root-cause", default=None)
    parser.add_argument("--action-taken", default=None)
    parser.add_argument("--operator", default=None)
    parser.add_argument("--comment", default=None)
    parser.add_argument("--env-file", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = save_ai_finding_feedback(
        args.finding_id,
        {
            "feedback_type": args.feedback_type,
            "actual_root_cause": args.actual_root_cause,
            "action_taken": args.action_taken,
            "operator": args.operator,
            "comment": args.comment,
        },
        env_file=args.env_file,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
