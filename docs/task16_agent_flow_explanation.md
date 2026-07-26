# Task 16 轻量 Agent 实际执行流程说明

## 1. 当前整体流程

当前 Task 16 的真实执行链路是：

```text
current_window_summary.json
  -> run_light_agent()
  -> 第一次调用 DeepSeek
  -> DeepSeek 返回 tool_calls
  -> 后端执行 Task 15 受控工具
  -> 将 tool_result 追加回 messages
  -> 再次调用 DeepSeek
  -> DeepSeek 输出最终结构化 JSON
  -> ai_agent_result.json
```

注意：AI 不直接访问 Elasticsearch 或 MySQL。AI 只能请求工具名和参数，真正查询由后端受控工具执行。

## 2. 对应代码文件

| 环节 | 文件 | 作用 |
| --- | --- | --- |
| 生成当前窗口摘要 | `aiops/context/current_window_summary.py` | 从 ES 聚合生成 `current_window_summary` |
| 生成摘要脚本 | `scripts/build_current_window_summary.py` | 命令行生成 summary JSON |
| Agent 主流程 | `aiops/agent/light_agent.py` | 构造 prompt、调用 DeepSeek、执行工具循环、解析最终 JSON |
| Agent 运行脚本 | `scripts/run_light_agent.py` | 读取 summary，调用 `run_light_agent()`，保存结果 |
| AI 工具注册表 | `aiops/tools/ai_tools.py` | 提供 `get_tool_schemas()` 和 `execute_ai_tool()` |
| 候选调查工具实现 | `aiops/tools/investigation.py` | 实现 `investigate_candidates()` 等具体调查逻辑 |
| 旧 Markdown 报告 | `scripts/generate_ai_report.py` | Task 13 旧逻辑，保留，不参与 Task 16 主流程 |

## 3. 第一次调用 DeepSeek 时发了什么 prompt

第一次调用 DeepSeek 的 messages 由 `aiops/agent/light_agent.py` 构造。

相关函数：

- `build_system_prompt()`
- `final_json_schema_text()`
- `build_initial_messages(summary, model_name)`
- `compact_summary(summary)`

第一次 messages 主要有两条：

### 3.1 system message

system message 说明 AI 的身份和约束：

```text
你是城域网 AIOps 轻量分析 Agent。
你不是 Markdown 报告生成器。
你只能基于 current_window_summary 和工具返回结果分析。
你不能编造设备、链路、接口、业务影响。
你不能直接生成 ES DSL 或 SQL。
你只能通过可用工具查询更多证据。
```

还明确要求 AI 判断：

- 哪些必须处置；
- 哪些持续观察；
- 哪些可能是长期噪声；
- 哪些已经恢复；
- 哪些数据不足；
- 哪些存在多设备关联或公共服务异常。

并规定优先调查顺序：

1. `open_incidents`
2. `critical_traps / important_trap_candidates`
3. `multi_device_correlations`
4. `flapping_objects`
5. `new_anomalies`
6. `baseline_deviations`
7. `noise_candidates`

### 3.2 user message

user message 是一个 JSON，结构大致是：

```json
{
  "task": "基于 current_window_summary 进行 AIOps 轻量分析",
  "instructions": [
    "先判断是否需要调用工具调查候选项",
    "优先使用 investigate_candidates 批量调查 Top 候选",
    "不要自由查询无关数据",
    "最多只选择 3~5 个最值得调查的候选",
    "最终输出结构化 JSON"
  ],
  "model": "deepseek-v4-pro",
  "final_json_schema": "...",
  "current_window_summary": {
    "...": "压缩后的当前窗口摘要"
  }
}
```

其中 `current_window_summary` 不是旧的完整 AI context，而是 Task 14 的压缩摘要，包含：

- `overview`
- `open_incidents`
- `important_trap_candidates / important_traps`
- `baseline_deviations`
- `new_anomalies`
- `flapping_objects`
- `multi_device_correlations`
- `noise_candidates`
- `data_quality`

### 3.3 同时发送 tools schema

第一次调用 DeepSeek 时，还会把 Task 15 的工具 schema 一起发给模型。

代码位置：

- `aiops/tools/ai_tools.py`
- `get_tool_schemas()`

注册的工具有：

- `investigate_candidates`
- `get_related_events`
- `get_device_history`
- `get_object_history`
- `get_topology_context`
- `get_baseline`

## 4. 第一次 AI 返回了什么

在真实运行中，第一次 DeepSeek 没有直接输出最终 JSON，而是返回：

```text
finish_reason = tool_calls
```

意思是：AI 认为当前 summary 还不够，需要调用工具补充证据。

它选择的主要工具是：

```text
investigate_candidates
```

这符合我们的设计：Task 16 应优先让 AI 调用 `investigate_candidates`，而不是自由查 ES。

## 5. 后端收到 tool_calls 后做了什么

后端不会把 AI 生成的查询语句拿去执行，因为 AI 不允许写 ES DSL 或 SQL。

后端只做这几件事：

1. 解析 tool name；
2. 解析 arguments；
3. 调用 `execute_ai_tool(tool_name, arguments)`；
4. `execute_ai_tool()` 到注册表 `AI_TOOLS` 中查找受控工具；
5. 执行后端固定逻辑；
6. 得到压缩后的 tool result；
7. 把 tool result 追加回 messages。

相关代码：

- `aiops/agent/light_agent.py`
  - `execute_tool_call()`
  - `append_standard_tool_messages()`
- `aiops/tools/ai_tools.py`
  - `AI_TOOLS`
  - `execute_ai_tool()`
- `aiops/tools/investigation.py`
  - `investigate_candidates()`

## 6. investigate_candidates 具体查了什么

`investigate_candidates()` 是 Task 15 的主调查工具。

它做的是一次性批量调查，不让 AI 无限查询。

它主要查：

1. 当前相关事件；
2. 历史同类事件；
3. 相关 Trap；
4. 拓扑上下文；
5. 历史 AI 报告记忆；
6. 基线对比。

这些查询都在后端代码里写死边界和 limit，不接受自由 ES DSL 或自由 SQL。

真实压测中，`investigate_candidates` 返回：

```text
result_size_bytes = 34767
result_item_count = 3
ok = true
```

意思是：工具返回了 3 个主要候选调查包，大小约 34KB。

## 7. 补充查询后第二次怎么调 DeepSeek

工具执行完成后，后端会把工具结果追加到 messages。

第二次调用 DeepSeek 时，messages 变成：

```text
system message
user message，包含 current_window_summary
assistant message，包含第一次 tool_calls
tool message，包含 investigate_candidates 的返回结果
```

也就是说，第二次 prompt 不是重新开始，而是在第一次对话基础上追加了工具结果。

DeepSeek 第二次看到的是：

1. 原始分析任务；
2. 当前窗口摘要；
3. 它自己刚才请求的工具调用；
4. 后端真实返回的工具结果。

然后 DeepSeek 根据这些信息决定：

- 是否继续调用工具；
- 或者直接输出最终 JSON。

## 8. round=2 具体发生了什么

round=2 表示最多允许 2 次工具调用。

真实运行中，它确实执行了 2 次工具调用。

### 8.1 第一次 LLM 调用

输入：

- system prompt；
- user prompt；
- current_window_summary；
- tool schemas。

AI 返回：

- `finish_reason = tool_calls`
- 请求调用 `investigate_candidates`

消耗：

- `prompt_tokens = 33413`
- `completion_tokens = 1756`
- `total_tokens = 35169`

### 8.2 第一次工具调用

工具：

```text
investigate_candidates
```

后端查询：

- Top 候选；
- 相关当前事件；
- 历史事件；
- Trap；
- 拓扑；
- 历史 AI 记忆；
- 基线。

返回：

- `result_size_bytes = 34767`
- `result_item_count = 3`
- `ok = true`

### 8.3 第二次 LLM 调用

输入：

- 原始 system/user prompt；
- 第一次 tool_call；
- `investigate_candidates` 的 tool_result。

AI 返回：

- 再次 `finish_reason = tool_calls`
- 请求调用 `get_topology_context`

消耗：

- `prompt_tokens = 49182`
- `completion_tokens = 340`
- `total_tokens = 49522`

### 8.4 第二次工具调用

工具：

```text
get_topology_context
```

返回：

- `result_size_bytes = 194`
- `result_item_count = 0`
- `ok = true`

这个工具返回非常小，说明补查价值有限。

### 8.5 后续 LLM 调用与最终输出

round=2 后面又发生了两次 LLM 调用，主要用于生成和修正最终 JSON。

最终输出：

- `overall_status.level = major`
- `must_handle = 2`
- `watch = 5`
- `noise = 2`
- `recovered = 2`
- `insufficient = 2`
- `correlations = 5`
- `next_actions = 5`

主要 must_handle：

1. `ZL-16K-M-B GE2/0/1` 光口 Down 且收光过低；
2. `CN-16K-M-B GE2/0/9` 光口 Down 且收光过低。

## 9. round=4 具体发生了什么

round=4 表示最多允许 4 次工具调用。

但真实运行中，AI 只调用了 1 次工具。

### 9.1 第一次 LLM 调用

输入和 round=2 第一次相同：

- system prompt；
- user prompt；
- current_window_summary；
- tool schemas。

AI 返回：

- `finish_reason = tool_calls`
- 请求调用 `investigate_candidates`

消耗：

- `prompt_tokens = 33413`
- `completion_tokens = 758`
- `total_tokens = 34171`

### 9.2 第一次工具调用

工具：

```text
investigate_candidates
```

返回：

- `result_size_bytes = 34767`
- `result_item_count = 3`
- `ok = true`

### 9.3 第二次 LLM 调用

输入：

- 原始 system/user prompt；
- 第一次 tool_call；
- `investigate_candidates` 的 tool_result。

AI 这次没有继续请求工具，而是直接输出最终 JSON。

消耗：

- `prompt_tokens = 48184`
- `completion_tokens = 6852`
- `total_tokens = 55036`

最终输出：

- `overall_status.level = major`
- `must_handle = 3`
- `watch = 3`
- `noise = 2`
- `recovered = 2`
- `insufficient = 2`
- `correlations = 3`
- `next_actions = 4`

主要 must_handle：

1. 多设备 SRv6 POLICY BFD 会话 Administratively Down 且未恢复；
2. `ZL-16K-M-B GE2/0/1` 光口收光功率严重偏低导致端口 Down；
3. RADIUS 服务器 `111.208.114.150` 多台 BRAS 持续异常。

## 10. 为什么 round=2 反而更慢、token 更多

这不是因为 round=2 本身更重，而是因为 AI 实际行为不同。

round=2：

- LLM 调用 4 次；
- 工具调用 2 次；
- total tokens = 193172；
- 总耗时约 476 秒。

round=4：

- LLM 调用 2 次；
- 工具调用 1 次；
- total tokens = 89207；
- 总耗时约 252 秒。

每多一次 LLM 调用，都会把历史 messages、summary、tool_result 再发一遍，所以 token 会快速膨胀。

round=2 中第二次工具 `get_topology_context` 返回只有 194 bytes，价值不高，但它导致后续 prompt 历史更长。

## 11. 最终生成的内容是什么

最终生成的不是 Markdown，而是页面可渲染的 JSON。

输出文件：

- round=2：`/data/jscn-aiops/reports/task16/runtime_test_round2/ai_agent_result.json`
- round=4：`/data/jscn-aiops/reports/task16/runtime_test_round4/ai_agent_result.json`

JSON 里面有：

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
- `agent_runtime`

其中 `agent_runtime` 是本次 follow-up 新增的运行指标，记录 LLM 调用、工具调用、token、耗时和 trajectory 目录。

## 12. 完整轨迹保存在哪里

round=2：

```text
/data/jscn-aiops/reports/task16/runtime_test_round2/debug/agent_runs/20260518-061716-97e56fa8
```

round=4：

```text
/data/jscn-aiops/reports/task16/runtime_test_round4/debug/agent_runs/20260518-062611-3e0a303d
```

每个目录里有：

- `summary_input.json`
- `tool_schemas.json`
- `messages_round_1.json`
- `messages_round_2.json`
- `tool_result_round_1.json`
- `final_response_raw.txt`
- `final_result.json`
- `runtime_metrics.json`

round=2 因为多走了一次工具和更多 LLM 轮次，所以还有：

- `messages_round_3.json`
- `messages_round_4.json`
- `tool_result_round_2.json`

## 13. 当前结论

当前 Agent 的实际执行过程已经跑通：

1. 先用压缩 summary 让 AI 判断；
2. AI 优先请求 `investigate_candidates`；
3. 后端执行受控查询；
4. 工具结果回填给 AI；
5. AI 输出结构化 JSON；
6. 全过程保存 runtime metrics 和 trajectory。

从这次压测看，`investigate_candidates` 已经是最有价值的主工具。

后续优化重点不是盲目增加轮次，而是：

1. 压缩 `current_window_summary`；
2. 压缩 `investigate_candidates` 返回内容；
3. 限制无意义补查；
4. 默认用较小 `max-tool-rounds` 做 MVP 演示。
