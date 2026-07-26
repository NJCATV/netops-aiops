# Task 16 关键告警覆盖缺口分析

## 1. 当前链路简述

当前轻量 Agent 链路是：

```text
Elasticsearch raw syslog / raw trap / alarm_events
  -> current_window_summary
  -> investigate_candidates 受控工具
  -> DeepSeek light_agent
  -> ai_agent_result.json
```

AI 不直接查询 ES/MySQL，只能看到 `current_window_summary` 和工具返回结果。

Task 16 压测使用的 48 小时窗口为：

- `2026-05-16T03:17:27.883928Z` 到 `2026-05-18T03:17:27.883928Z`
- summary 路径：`/data/jscn-aiops/reports/task16/runtime_test_round2/current_window_summary.json`
- round=2 trajectory：`/data/jscn-aiops/reports/task16/runtime_test_round2/debug/agent_runs/20260518-061716-97e56fa8/`
- round=4 trajectory：`/data/jscn-aiops/reports/task16/runtime_test_round4/debug/agent_runs/20260518-062611-3e0a303d/`

## 2. 漏报告警在各阶段是否存在

以 `CN-16K-M-B`、`GigabitEthernet2/0/9`、`Vlan-interface4038` 为重点核对。

### ES 原始数据

结论：存在。

- `jscn-aiops-syslog-parsed-*` 中存在 `CN-16K-M-B` 的接口、PPP、板卡类日志。
- `jscn-aiops-trap-raw-*` 中存在包含 `CN-16K-M-B` 的 Trap。
- `jscn-aiops-alarm-events-*` 中存在未恢复接口和光路事件。

关键样例：

- `INTERFACE_LINK`：`CN-16K-M-B / GigabitEthernet2/0/9`，`event_status=open`，`event_count=2`
- `INTERFACE_LINK`：`CN-16K-M-B / Vlan-interface4038`，`event_status=open`，`event_count=2`
- `OPTICAL_FAULT`：`CN-16K-M-B / GE2/0/9`，`event_status=open`，`event_count=2`
- `DEV_FAULT_TOOLONG`：`Card in slot 19 is still in Fault state...` 存在于 syslog，但 `event_family=unknown`，未稳定进入 `alarm_events`

### current_window_summary

结论：接口 Down / 光路告警进入了 `open_incidents`，但没有独立关键候选池。

在 48 小时 summary 中：

- `open_incidents[5]`：`INTERFACE_LINK / CN-16K-M-B / Vlan-interface4038`
- `open_incidents[6]`：`INTERFACE_LINK / CN-16K-M-B / GigabitEthernet2/0/9`
- `open_incidents[7]`：`OPTICAL_FAULT / CN-16K-M-B / GE2/0/9`

但旧 summary 没有 `critical_alarm_candidates`，Trap 也只进入 `important_traps`，并且仍按“severity 不可靠”处理。

### investigate_candidates 候选选择

结论：目标告警未进入工具调查结果。

旧 `select_candidates(summary, 5)` 的结果为：

1. `BFD_FLAP / GZL-16K-M-A`
2. `BFD_FLAP / CN16K-F-HeXinA`
3. `INTERFACE_LINK / ZL-16K-M-B / GigabitEthernet2/0/1`
4. `INTERFACE_LINK / ZL-16K-M-B / Vlan-interface4085`
5. `OPTICAL_FAULT / ZL-16K-M-B / GE2/0/1`

`CN-16K-M-B` 排在 `open_incidents[5-7]`，没有进入默认 Top 5 工具调查。

### tool_result

结论：round=2 和 round=4 的 `tool_result_round_1.json` 都不包含 `CN-16K-M-B`、`GigabitEthernet2/0/9`、`Vlan-interface4038`。

也就是说，AI 首轮虽然在 summary 中看到了目标告警，但补充证据包没有覆盖这些告警。

### DeepSeek 最终 JSON

结论：覆盖不稳定。

- Task 16 普通运行结果包含 `CN-16K-M-B`。
- round=2 结果包含 `CN-16K-M-B`。
- round=4 结果完全不包含 `CN-16K-M-B`、`GigabitEthernet2/0/9`、`Vlan-interface4038`。

这说明问题不是“数据不存在”，而是候选优先级和 prompt 约束不足导致的稳定性问题。

## 3. 漏报根因判断

根因分为三类：

1. `current_window_summary` 筛选/排序漏掉关键语义
   旧 summary 只有通用 `open_incidents`，没有把未恢复接口 Down、光路、板卡/硬件、重要 Trap 抽成必须关注的关键候选池。

2. `investigate_candidates` TopN 选择漏掉
   旧工具优先级是 `open_incidents -> multi_device_correlations -> flapping_objects...`，在 `open_incidents` 内主要按 `event_count` 排序。BFD、其它接口告警和光路告警会挤占 Top 5，导致 `CN-16K-M-B` 没有进入工具证据包。

3. light_agent prompt 没有“必须覆盖”约束
   旧 prompt 只说优先调查 `open_incidents` 和 Trap，没有要求 `critical_alarm_candidates` 或重要 Trap 最终必须落到 `must_handle/watch/insufficient`。因此模型即使在 summary 中看到，也可能在生成最终 JSON 时省略。

补充问题：

- `DEV_FAULT_TOOLONG` 板卡类告警已进入 raw syslog，但 `event_family=unknown`，当前聚合规则没有稳定转成 `alarm_events`。本轮不做完整 syslog 规则扩展，但需要在 data_quality 中暴露 unknown 比例，后续单独补规则。
- 当前 Trap 已由上游过滤为紧急/重要，但旧代码仍按“缺 severity，无法判断重要性”处理。这个假设已经过期。

## 4. 推荐修复路线

本轮建议立即做 Task 16.1 小修复：

1. 在 `current_window_summary` 中新增 `critical_alarm_candidates`。
2. 将当前窗口 Trap 视为上游已过滤的紧急/重要候选，继续保留紧凑字段，不做 MIB 翻译。
3. 调整 `open_incidents` 排序，让接口 Down、物理 Down、Line protocol Down、光路、板卡/硬件、风扇、电源、温度类告警优先。
4. 调整 `investigate_candidates`，优先调查 `critical_alarm_candidates`。
5. 调整 light_agent prompt，要求关键候选和重要 Trap 最终 JSON 必须覆盖。
6. 在 `data_quality` 中补充 Trap 上游过滤、MIB 翻译、severity 缺失、unknown event_family 比例。

不建议本轮做：

- 完整 MIB 解析。
- 大规模重构 syslog/trap 采集。
- 新增前端。
- 新增 Agent 框架。
- 让 AI 直接访问 ES/MySQL。

## 5. 是否需要立即做 Task 16.1

需要。

原因是目标告警已经进入 ES 和 summary，但没有稳定进入工具调查和最终 JSON。这会影响 MVP 演示中“紧急/重要未恢复告警必须被值班 Agent 看到”的核心可信度。

Task 16.1 的范围可以保持很小：只增加关键候选池、调整候选优先级和 prompt 约束，不改变采集链路，不做复杂 Agent 编排。

## 6. Task 16.1 修复与验证结果

已实施小修复：

- `current_window_summary` 新增 `critical_alarm_candidates`。
- Trap 聚合键调整为 `trap_oid + source_ip + enterprise_oid + specific_trap`。
- 当前窗口 Trap 作为上游已过滤紧急/重要数据进入 `important_traps` 和 `important_trap_candidates`。
- `open_incidents` 排序优先未恢复接口 Down、光路、板卡/硬件、风扇、电源、温度类告警。
- `investigate_candidates` 优先选择 `critical_alarm_candidates`，并且同类关键候选内先选 `alarm_event`，再选 Trap。
- light_agent prompt 要求关键候选和重要 Trap 必须在最终 JSON 中覆盖。
- `data_quality` 增加 Trap 上游过滤、MIB 翻译状态、severity 可用性、unknown event_family 比例。

服务器验证命令：

```bash
cd /opt/jscn-aiops
python3 -m py_compile \
  aiops/context/current_window_summary.py \
  scripts/build_current_window_summary.py \
  aiops/tools/investigation.py \
  aiops/tools/ai_tools.py \
  aiops/agent/light_agent.py \
  scripts/run_light_agent.py

python3 scripts/build_current_window_summary.py \
  --hours 48 \
  --output /data/jscn-aiops/reports/task16_1/current_window_summary.json

python3 scripts/investigate_candidates.py \
  --summary-json /data/jscn-aiops/reports/task16_1/current_window_summary.json \
  --output /data/jscn-aiops/reports/task16_1/investigation_context.json \
  --max-candidates 5 \
  --env-file deploy/.env

python3 scripts/run_light_agent.py \
  --summary-json /data/jscn-aiops/reports/task16_1/current_window_summary.json \
  --output /data/jscn-aiops/reports/task16_1/ai_agent_result.json \
  --max-tool-rounds 2 \
  --env-file deploy/.env
```

验证结果：

- 48 小时 summary 生成成功。
- `critical_alarm_candidates=21`。
- `critical_alarm_candidates[0]`：`INTERFACE_LINK / CN-16K-M-B / Vlan-interface4038`。
- `critical_alarm_candidates[1]`：`INTERFACE_LINK / CN-16K-M-B / GigabitEthernet2/0/9`。
- `critical_alarm_candidates[2]`：`OPTICAL_FAULT / CN-16K-M-B / GE2/0/9`。
- `important_traps=18`，包含 `specific_trap`。
- `investigate_candidates` Top 5 已覆盖上述 3 条 CN-16K-M-B 关键告警和 2 条高频重要 Trap。
- light agent 输出合法 JSON。
- 最终 `ai_agent_result.json` 已覆盖 `CN-16K-M-B`、`GigabitEthernet2/0/9`、`Vlan-interface4038`、`GE2/0/9`。
- 未翻译 Trap 被放入 `insufficient`，没有被忽略。

本次真实 Agent 运行指标：

- model：`deepseek-v4-pro`
- duration：`334915 ms`
- tool_call_count：`2`
- total_tokens：`156150`
- prompt_tokens：`146622`
- completion_tokens：`9528`
- 第一次工具调用：`investigate_candidates`，`29141 bytes`
- 第二次工具调用：`get_device_history`，`4242 bytes`

与修复前压测相比：

- 修复前 round=2：`193172 tokens`，`475979 ms`，2 次工具调用。
- 修复前 round=4：`89207 tokens`，`251561 ms`，1 次工具调用。
- 修复后本次：`156150 tokens`，`334915 ms`，2 次工具调用。

本次 token 高于修复前 round=4，低于修复前 round=2。主要原因是 summary 增加了关键候选池，且模型额外调用了一次 `get_object_history`。关键告警覆盖稳定性明显提升，仍在 Task 16 MVP 可接受范围内。
