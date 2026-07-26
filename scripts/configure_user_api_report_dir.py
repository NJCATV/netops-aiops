"""Atomically configure a writable report directory for the user-owned API."""

from __future__ import annotations

import os
import pathlib
import sys


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: configure_user_api_report_dir.py APP_ENV REPORT_DIR")
    env_path = pathlib.Path(sys.argv[1]).resolve()
    report_dir = pathlib.Path(sys.argv[2]).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(report_dir, os.W_OK):
        raise PermissionError(f"report directory is not writable: {report_dir}")

    original = env_path.read_text(encoding="utf-8").splitlines()
    assignment = f"AI_RUN_REPORT_DIR={report_dir}"
    output = []
    replaced = False
    for line in original:
        if line.startswith("AI_RUN_REPORT_DIR="):
            output.append(assignment)
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(assignment)

    temporary = env_path.with_suffix(env_path.suffix + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temporary, env_path.stat().st_mode & 0o777)
    temporary.replace(env_path)
    print(f"AI_RUN_REPORT_DIR={report_dir}")


if __name__ == "__main__":
    main()
