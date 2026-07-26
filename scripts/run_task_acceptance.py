"""Execute one configured report task for production acceptance."""

from __future__ import annotations

import argparse

from aiops.scheduler.ai_scheduler import execute_task_once


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", type=int)
    args = parser.parse_args()
    result = execute_task_once(args.task_id, trigger="acceptance")
    print({"ok": result.ok, "run_uid": result.run_uid, "status": result.status, "error": result.error})
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
