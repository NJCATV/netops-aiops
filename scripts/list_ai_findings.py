#!/usr/bin/env python3
"""List persisted AI findings for validation and debugging."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.agent.persistence import load_env_file  # noqa: E402
from app.db import create_db_engine  # noqa: E402
from app.models import AiAnalysisRun, AiFinding, AiFindingFeedback  # noqa: E402
from sqlalchemy import desc, select  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest", type=int, default=20)
    parser.add_argument("--run-uid", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--device-ip", default=None)
    parser.add_argument("--object-key", default=None)
    parser.add_argument("--with-feedback", action="store_true")
    parser.add_argument("--env-file", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    engine = create_db_engine()
    stmt = (
        select(
            AiFinding.id,
            AiFinding.finding_uid,
            AiAnalysisRun.run_uid,
            AiFinding.category,
            AiFinding.title,
            AiFinding.severity,
            AiFinding.confidence,
            AiFinding.device_ip,
            AiFinding.device_name,
            AiFinding.object_key,
            AiFinding.finding_fingerprint,
            AiFinding.lifecycle_status,
            AiFinding.created_at,
            AiFindingFeedback.feedback_type,
            AiFindingFeedback.actual_root_cause,
            AiFindingFeedback.action_taken,
            AiFindingFeedback.operator,
        )
        .join(AiAnalysisRun, AiFinding.run_id == AiAnalysisRun.id)
        .outerjoin(AiFindingFeedback, AiFindingFeedback.finding_id == AiFinding.id)
        .order_by(desc(AiFinding.created_at), desc(AiFindingFeedback.created_at))
        .limit(max(1, min(args.latest, 200)))
    )
    if args.run_uid:
        stmt = stmt.where(AiAnalysisRun.run_uid == args.run_uid)
    if args.category:
        stmt = stmt.where(AiFinding.category == args.category)
    if args.device_ip:
        stmt = stmt.where(AiFinding.device_ip == args.device_ip)
    if args.object_key:
        stmt = stmt.where(AiFinding.object_key == args.object_key)
    if args.with_feedback:
        stmt = stmt.where(AiFindingFeedback.id.is_not(None))
    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(stmt).mappings().all()]
    for row in rows:
        row["created_at"] = str(row.get("created_at") or "")
    print(json.dumps({"count": len(rows), "findings": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
