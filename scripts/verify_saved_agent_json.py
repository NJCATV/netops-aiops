"""Verify that a saved model response is recoverable by the production parser."""

from __future__ import annotations

import pathlib
import sys

from aiops.agent.light_agent import parse_agent_json


path = pathlib.Path(sys.argv[1])
parsed = parse_agent_json(path.read_text(encoding="utf-8"))
if not isinstance(parsed, dict):
    raise SystemExit("unparseable")
print(f"parsed keys={','.join(sorted(parsed))} must_handle={len(parsed.get('must_handle') or [])}")
