# Task 16 Runtime Analysis

This document records the real runtime pressure test for the lightweight AIOps Agent after Task 16. The goal was behavior analysis, not new product functionality.

## Test Inputs

Both tests used the same 48-hour `current_window_summary`:

- Summary path: `/data/jscn-aiops/reports/task16/runtime_test_round2/current_window_summary.json`
- Window start: `2026-05-16T03:17:27.883928Z`
- Window end: `2026-05-18T03:17:27.883928Z`
- Summary size sent to Agent after compaction: about `74427` bytes

## Test Outputs

Round 2 output directory:

- `/data/jscn-aiops/reports/task16/runtime_test_round2/`

Round 4 output directory:

- `/data/jscn-aiops/reports/task16/runtime_test_round4/`

Each directory contains current summary, Agent result, runtime metrics, and full trajectory files under `debug/agent_runs/<run_id>/`.

## Runtime Metrics Summary

| Metric | max-tool-rounds=2 | max-tool-rounds=4 |
| --- | ---: | ---: |
| Duration ms | `475979` | `251561` |
| LLM calls | `4` | `2` |
| Tool calls executed | `2` | `1` |
| Total prompt tokens | `179711` | `81597` |
| Total completion tokens | `13461` | `7610` |
| Total tokens | `193172` | `89207` |
| Prompt cache hit tokens | `116992` | `67456` |
| Prompt cache miss tokens | `62719` | `14141` |
| Overall status | `major` | `major` |
| must_handle count | `2` | `3` |
| watch count | `5` | `3` |
| noise count | `2` | `2` |
| recovered count | `2` | `2` |
| insufficient count | `2` | `2` |
| correlations count | `5` | `3` |
| next_actions count | `5` | `4` |

## Tool Call Details

Round 2 executed:

1. `investigate_candidates`: `575 ms`, `34767 bytes`, `3` items, OK.
2. `get_topology_context`: `86 ms`, `194 bytes`, `0` items, OK.

Round 4 executed:

1. `investigate_candidates`: `597 ms`, `34767 bytes`, `3` items, OK.

## Round 2 vs Round 4 Analysis

The `max-tool-rounds=4` run did not use additional tool capacity. It called only `investigate_candidates` once and then produced final JSON. The `max-tool-rounds=2` run made an extra `get_topology_context` call, but that call returned only a small result and did not materially improve the final conclusion.

Token usage was much higher in the round 2 run:

- Round 2 total tokens: `193172`
- Round 4 total tokens: `89207`
- Increase: `103965` tokens, about `116.5%` higher than round 4

Runtime was also higher in round 2:

- Round 2 duration: `475979 ms`
- Round 4 duration: `251561 ms`
- Increase: `224418 ms`, about `89.2%` higher than round 4

The quality difference was not clearly better for round 2. Both runs found `major` status and identified physical optical/interface problems as must-handle. Round 4 produced one more must-handle item with fewer tokens and fewer LLM calls. This suggests that extra allowed rounds do not guarantee more investigation value; the model's actual behavior matters more than the configured maximum.

## Agent Behavior Observations

The Agent correctly prioritized `investigate_candidates` in both tests. This is the desired behavior for the MVP because it avoids free exploration and keeps investigation backend-controlled.

The Agent did not attempt free ES DSL or SQL. All investigation used the Task 15 tool layer.

The most valuable tool was `investigate_candidates`. It already returned enough evidence for the main must-handle conclusions. The extra `get_topology_context` in round 2 had little value because the needed topology-like context was already represented or the lookup result was too small.

The candidates most likely to trigger investigation were open incidents around `INTERFACE_LINK`, `OPTICAL_FAULT`, and BFD-related events. Multi-device Radius and QoS correlations were useful for watch/correlation sections, but did not require additional tool calls in the observed runs.

## Token Growth Sources

The main token drivers are:

1. `current_window_summary`: about `74427` bytes before model tokenization.
2. `investigate_candidates` tool result: about `34767` bytes.
3. Message history: after tool results are appended, each additional LLM call resends summary, schemas, assistant messages, and tool outputs.
4. Final JSON generation: completion tokens were `7610` to `13461`, which is significant but smaller than prompt growth.

The round 2 run shows that retry/follow-up turns can multiply prompt tokens even when the additional tool result is small. Message history is therefore a larger scaling risk than individual small follow-up tools.

## Current Recommendations

1. Default MVP setting should be `max-tool-rounds=2` or lower, with strong prompting to call `investigate_candidates` once and then finalize.
2. For production demo, `max-tool-rounds=2` is enough; `max-tool-rounds=4` should remain available for debugging or unusually complex windows.
3. `investigate_candidates` should be compressed further before Task 17/18 production use. The current `34767 bytes` result is usable but contributes heavily to follow-up prompt size.
4. The initial `current_window_summary` should be further pruned for Agent runtime. It is already much smaller than the old full context, but still large enough to drive high prompt token counts.
5. Store and inspect trajectory files during development. They are essential for understanding why the Agent continued, why token usage grew, and which evidence influenced final findings.
6. The current flow is sufficient for MVP demonstration: it produces structured JSON, uses controlled tools, records metrics, and avoids direct ES/MySQL access by AI.

## Not Done

No frontend page, scheduler, email, login, database findings persistence, multi-Agent framework, Dify, LangGraph, MCP, or automatic dispatch was added in this follow-up.
