# Task 16 Lightweight Agent Flow

Task 16 replaces the old one-shot Markdown report style with a lightweight AIOps Agent flow:

```text
current_window_summary -> controlled AI tools -> max 4 tool calls -> structured JSON result
```

The old Task 13 Markdown report script is kept unchanged for debugging and historical compatibility.

## Relationship With Task 14 and Task 15

- Task 14 builds compact `current_window_summary` from Elasticsearch.
- Task 15 exposes controlled investigation tools through `aiops/tools/ai_tools.py`.
- Task 16 lets the model analyze only the summary and tool results. The model cannot query Elasticsearch or MySQL directly.

## Runtime Modules

- `aiops/agent/light_agent.py`
- `scripts/run_light_agent.py`

Core function:

```python
run_light_agent(summary, max_tool_rounds=4, model=None, temperature=0.1)
```

## Command

```bash
cd /opt/jscn-aiops
python3 scripts/run_light_agent.py \
  --summary-json /data/jscn-aiops/reports/task16/current_window_summary.json \
  --output /data/jscn-aiops/reports/task16/ai_agent_result.json \
  --max-tool-rounds 4 \
  --env-file deploy/.env
```

## AI Configuration

The Agent uses OpenAI-compatible DeepSeek configuration from runtime environment only:

- `DEEPSEEK_API_KEY` or `AI_API_KEY`
- `DEEPSEEK_BASE_URL` or `AI_API_BASE_URL`
- `DEEPSEEK_MODEL` or `AI_MODEL`
- `AI_REQUEST_TIMEOUT_SECONDS`

Secrets must stay in runtime `.env` and must not be committed.

## Tool Flow

1. Send system/user messages with compact `current_window_summary`.
2. Provide `get_tool_schemas()` from Task 15.
3. If the model returns standard `tool_calls`, execute them through `execute_ai_tool()`.
4. If the model emits pseudo tool JSON, parse and execute it as fallback.
5. Append tool results and continue until no more tool request or the configured tool-call limit is reached.
6. Force final JSON if the limit is reached.

Task 16 prefers `investigate_candidates` as the primary investigation tool. Smaller tools are bounded follow-ups for known devices, objects, topology, or baseline checks.

After Task 16.1, the prompt and compact summary explicitly include `critical_alarm_candidates`. If this section or important Trap candidates are present, the final JSON must cover them in `must_handle`, `watch`, or `insufficient`. Untranslated Trap data must not be silently dropped; if meaning is unclear it should be reported as insufficient evidence.

After Task 16.2, Trap candidates may include MIB translation fields from Logstash ingestion or backend MySQL lookup. The Agent should use readable `trap_oid_name` and `trap_oid_module` when present, while still preserving raw OIDs for traceability.

## Output

The output is JSON for page rendering. Top-level fields include:

- `metadata`
- `overall_status`
- `summary_cards`
- `must_handle`
- `watch`
- `noise`
- `recovered`
- `insufficient`
- `correlations`
- `next_actions`
- `data_quality`

All array fields are present even when empty. The Agent does not output Markdown.

## JSON Parsing Protection

The backend:

- Tries direct `json.loads()`.
- Falls back to extracting a JSON code block or first JSON object.
- Runs one repair prompt if parsing still fails.
- Saves raw invalid content under debug output and returns `invalid_agent_json` if repair fails.

## Validation

Validation was run on JSCN-20 as `aiops` in `/opt/jscn-aiops`.

Checks passed:

```bash
python3 -m py_compile aiops/agent/light_agent.py scripts/run_light_agent.py aiops/tools/ai_tools.py
python3 scripts/run_light_agent.py --help
```

DeepSeek runtime validation:

- Input: `/data/jscn-aiops/reports/task16/current_window_summary.json`
- Output: `/data/jscn-aiops/reports/task16/ai_agent_result.json`
- Model: `deepseek-v4-pro`
- Tool call count: `1`
- Final `must_handle` count: `2`
- Final JSON parsed successfully.
- Required arrays were present.
- Output was not Markdown.

Tool limit validation:

- With `--max-tool-rounds 1`, the Agent executed only 1 tool call and still produced valid JSON.

## Current Limits

- No frontend page.
- No scheduler.
- No email.
- No login or permissions.
- No database writes for AI findings.
- No Dify, LangGraph, CrewAI, AutoGen, MCP, or multi-agent framework.
- No automatic ticket dispatch.
