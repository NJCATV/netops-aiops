# Task 17 AI Findings, Memory, And Feedback

## Goal

Task 17 persists each lightweight Agent run and its structured findings into MySQL, then lets operator feedback become compact memory for later investigations.

Flow:

```text
current_window_summary
  -> controlled investigation tools
  -> light_agent JSON
  -> ai_analysis_runs / ai_findings
  -> ai_finding_feedback
  -> investigate_candidates ai_memory
```

AI still does not query MySQL or Elasticsearch directly. The backend reads memory and passes only compact records to the Agent tools.

## Tables

### ai_analysis_runs

Stores one row per Agent run.

Key fields:

- `run_uid`
- `window_start`
- `window_end`
- `hours`
- `model_name`
- `status`
- `overall_level`
- `overall_title`
- `summary_text`
- `summary_path`
- `result_path`
- `trajectory_dir`
- `tool_call_count`
- `llm_call_count`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `duration_ms`
- `error_message`
- `created_at`

### ai_findings

Stores one row per Agent finding. Findings are split from:

- `must_handle`
- `watch`
- `noise`
- `recovered`
- `insufficient`
- `correlations`
- `next_actions`

Categories stored as:

- `must_handle`
- `watch`
- `noise`
- `recovered`
- `insufficient`
- `correlation`
- `next_action`

The original compact finding is retained in `raw_finding`, but `raw_finding` is not returned to the Agent memory context.

### ai_finding_feedback

Stores operator feedback for a finding.

Supported `feedback_type` values:

- `confirmed`
- `false_positive`
- `ignored`
- `resolved`
- `suppressed`
- `escalated`
- `needs_more_data`

Feedback updates `ai_findings.lifecycle_status`:

- `confirmed` -> `active`
- `false_positive` -> `false_positive`
- `ignored` -> `ignored`
- `resolved` -> `resolved`
- `suppressed` -> `suppressed`
- `escalated` -> `active`
- `needs_more_data` -> `unknown`

## Save Agent Result

Default `run_light_agent.py` behavior is unchanged: it writes JSON only.

To persist to MySQL:

```bash
cd /opt/jscn-aiops
python3 scripts/run_light_agent.py \
  --summary-json /data/jscn-aiops/reports/task16_2/current_window_summary.json \
  --output /data/jscn-aiops/reports/task17/ai_agent_result.json \
  --max-tool-rounds 2 \
  --save-to-db \
  --env-file deploy/.env
```

When saving succeeds, the output JSON metadata includes:

- `saved_to_db`
- `ai_run_id`
- `ai_run_uid`
- `saved_finding_count`

The same values are also added to `agent_runtime` when runtime metrics are present.

## Finding Fingerprint

`finding_fingerprint` is a stable SHA-256 based hash truncated to 32 hex characters.

Inputs:

- category
- event types
- device IP
- device name
- object key
- normalized title/action/reason

This makes repeated findings on the same device/interface/object easier to match in later windows while keeping matching simple and deterministic.

## Feedback CLI

Example:

```bash
python3 scripts/add_ai_finding_feedback.py \
  --finding-id 1 \
  --feedback-type confirmed \
  --actual-root-cause "test confirmed root cause" \
  --action-taken "test action taken" \
  --operator "admin" \
  --comment "test feedback comment" \
  --env-file deploy/.env
```

The command validates `finding_id`, validates `feedback_type`, inserts feedback, and updates the finding lifecycle status.

## Query CLI

Examples:

```bash
python3 scripts/list_ai_findings.py --latest 20 --env-file deploy/.env
python3 scripts/list_ai_findings.py --run-uid <run_uid> --env-file deploy/.env
python3 scripts/list_ai_findings.py --category must_handle --device-ip 172.25.2.18 --env-file deploy/.env
python3 scripts/list_ai_findings.py --with-feedback --env-file deploy/.env
```

## AI Memory In Investigation

`investigate_candidates` now uses `ai_findings` and `ai_finding_feedback` before returning tool output to the Agent.

Each `ai_memory.records[]` item is compact:

- `finding_id`
- `title`
- `category`
- `severity`
- `confidence`
- `lifecycle_status`
- `actual_root_cause`
- `action_taken`
- `feedback_type`
- `created_at`
- `window_start`
- `window_end`

It does not return full `raw_finding` or raw log samples.

If no history exists:

```json
{
  "enabled": true,
  "records": [],
  "notes": ["no historical ai findings"]
}
```

## Validation

Server validation ran in `/opt/jscn-aiops` as `aiops`.

Syntax:

```bash
python3 -m py_compile \
  app/models.py \
  aiops/agent/persistence.py \
  scripts/run_light_agent.py \
  scripts/add_ai_finding_feedback.py \
  scripts/list_ai_findings.py \
  aiops/tools/investigation.py
```

Table creation:

- `ai_analysis_runs`
- `ai_findings`
- `ai_finding_feedback`

Persisted Agent run:

- `ai_run_id=1`
- `saved_finding_count=26`
- `saved_to_db=true`

Feedback validation:

- Added `confirmed` feedback to finding `1`.
- `ai_findings.lifecycle_status` changed to `active`.

Memory validation:

- Re-ran `investigate_candidates`.
- CN-16K-M-B candidates returned `ai_memory` with the confirmed finding and feedback:
  - `actual_root_cause=test_confirmed_root_cause`
  - `action_taken=test_action_taken`
  - `feedback_type=confirmed`

## Current Limits

Not implemented:

- Frontend feedback page.
- Login or permissions.
- Email.
- Scheduler.
- Automatic dispatch.
- Dify, MCP, LangGraph, CrewAI, or multi-agent framework.
- AI direct MySQL/ES access.
- Full raw finding or raw log replay in Agent memory.

Next frontend task can call the persistence functions or thin Flask endpoints around the same tables.
