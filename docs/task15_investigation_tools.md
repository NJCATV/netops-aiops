# Task 15 AI Investigation Tools MVP

Task 15 adds a bounded backend investigation tool for the lightweight AIOps Agent MVP. It expands selected candidates from `current_window_summary` into a structured JSON package. It does not call AI, does not let AI query Elasticsearch directly, and does not introduce Agent frameworks.

## Scope

Implemented:

- Added `aiops/tools/investigation.py`.
- Added `investigate_candidates()`.
- Added `scripts/investigate_candidates.py`.
- Reads Task 14 `current_window_summary` JSON.
- Selects bounded candidates from open incidents, multi-device correlations, flapping objects, new anomalies, baseline deviations, important Trap candidates, and noise candidates.
- After Task 16.1, `critical_alarm_candidates` is selected first so urgent/important Trap and unresolved physical/interface/optical alarms are investigated before general open incidents.
- For each candidate, returns:
  - related current events
  - historical events
  - related Trap evidence
  - baseline snapshot
  - optional topology context from MySQL `networkDevice` and `networkLinks`
  - optional historical AI memory from MySQL `report_records`

Not implemented:

- No DeepSeek call.
- No free-form `search_events` tool exposed to AI.
- No unlimited query loop.
- No frontend changes.
- No database writes.
- No Trap normalization; raw related Trap evidence is compact only.

## Command

Build a summary first:

```bash
cd /opt/jscn-aiops
python3 scripts/build_current_window_summary.py \
  --hours 48 \
  --output /data/jscn-aiops/reports/task15/current_window_summary_48h.json
```

Build investigation context:

```bash
python3 scripts/investigate_candidates.py \
  --summary-json /data/jscn-aiops/reports/task15/current_window_summary_48h.json \
  --output /data/jscn-aiops/reports/task15/investigation_context_48h.json \
  --max-candidates 5 \
  --env-file deploy/.env
```

## Output Shape

Top-level sections:

- `metadata`
- `investigations`
- `data_quality`

Each `investigations[]` item contains:

- `candidate_type`
- `candidate`
- `identity`
- `baseline`
- `related_current_events`
- `historical_events`
- `related_traps`
- `topology_context`
- `ai_memory`

The output is intended as the input package for Task 16 lightweight Agent calls.

## AI Callable Tool Layer

Task 15 follow-up exposes a controlled tool layer for Task 16:

- `aiops/tools/ai_tools.py`
- `AI_TOOLS` registry
- `get_tool_schemas()`
- `execute_ai_tool(tool_name, arguments)`

Registered tools:

- `investigate_candidates`
- `get_related_events`
- `get_device_history`
- `get_object_history`
- `get_topology_context`
- `get_baseline`

`get_tool_schemas()` returns OpenAI/DeepSeek function-calling compatible schema objects. If the runtime model client does not support standard `tool_calls`, Task 16 can still ask the model to emit pseudo tool JSON and pass the parsed name/arguments into `execute_ai_tool()`.

`investigate_candidates` has two roles:

1. Offline evidence-package generation through `scripts/investigate_candidates.py`.
2. Primary Task 16 Agent investigation tool through `execute_ai_tool("investigate_candidates", args)`.

Task 16 should prefer `investigate_candidates` as the main investigation step instead of letting AI freely query Elasticsearch. The smaller tools are bounded follow-ups for a known device, object, event type, topology lookup, or baseline comparison.

Candidate priority after Task 16.1:

1. `critical_alarm_candidates`
2. `open_incidents`
3. `multi_device_correlations`
4. `flapping_objects`
5. `new_anomalies`
6. `baseline_deviations`
7. `important_trap_candidates`
8. `noise_candidates`

Tool safety rules:

- No tool accepts raw ES DSL.
- No tool accepts raw SQL.
- Every tool enforces a limit.
- Tool outputs use compact event/trap summaries and do not emit full `raw_log_samples`.
- Related Trap evidence includes compact MIB translation fields (`trap_oid_name`, `trap_oid_module`, `mib_translated`) when available from ES or backend lookup.
- Tool calls are logged by tool name.
- Argument errors and execution failures return structured `{ok: false, error: ...}` results.
- No tool calls DeepSeek.

## Validation

Server validation was run as `aiops` in `/opt/jscn-aiops`.

Syntax and CLI checks:

```bash
python3 -m py_compile aiops/context/current_window_summary.py scripts/build_current_window_summary.py aiops/tools/investigation.py aiops/tools/ai_tools.py scripts/investigate_candidates.py
python3 scripts/investigate_candidates.py --help
```

Runtime validation with a 48-hour window and 5 candidates:

- Summary alarm events: `4277`
- Summary open incidents: `50`
- Summary baseline deviations: `22`
- Summary flapping objects: `30`
- Summary multi-device correlations: `6`
- Summary noise candidates: `1`
- Investigation candidates: `5`
- Related current events per candidate: up to configured limit `20`
- Historical events were returned for matching candidates.
- Topology and AI memory were enabled through MySQL runtime configuration.
- `get_tool_schemas()` returned 6 tool schemas.
- `execute_ai_tool("investigate_candidates", args)` returned `ok=true` with 2 bounded investigations in validation.
- `execute_ai_tool("unknown_tool", {})` returned structured `unknown_tool` error.
- Validation confirmed tool output did not contain `raw_log_samples`.

Current environment notes:

- Related Trap evidence can be empty when no Trap matches candidate device/OID in the candidate time range.
- Topology and AI memory are optional. They return explicit notes if MySQL dependencies or runtime credentials are unavailable.
