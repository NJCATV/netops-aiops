# Task 6: Elasticsearch 查询验证与 24 小时摘要

## Scope

本任务验证从 Elasticsearch 查询最近 24 小时 Syslog 和 Trap 数据，并输出 JSON 与 Markdown 摘要。

本任务不做 AI 分析，不做定时任务，不做 MIB 翻译。

执行时间：2026-05-17

执行用户：`aiops`

## Output Files

服务器输出：

```text
/data/jscn-aiops/reports/task6/task6-24h-summary.json
/data/jscn-aiops/reports/task6/task6-24h-summary.md
```

仓库归档：

```text
docs/outputs/task6-24h-summary.json
docs/outputs/task6-24h-summary.md
```

查询脚本：

```text
scripts/task6_es_24h_summary.py
```

## Query Window

```text
window_start: 2026-05-16T06:13:28.768028Z
window_end:   2026-05-17T06:13:28.768028Z
lookback:     24 hours
```

## Syslog Aggregations

索引：

```text
jscn-aiops-syslog-parsed-*
```

聚合字段：

1. `device_ip.keyword`
2. `device_name.keyword`
3. `event_code.keyword`
4. `event_family.keyword`
5. `severity.keyword`

结果摘要：

```text
total: 341
top device_ip: 172.25.2.35 / 160
top device_name: JS-16K-M-A / 160
top event_code: PPP_CHASTEN / 155
top event_family: unknown / 171
top severity: 4 / 341
```

## Trap Aggregations

索引：

```text
jscn-aiops-trap-raw-*
```

聚合字段：

1. `trap_oid.keyword`
2. `source_ip.keyword`
3. `enterprise_oid.keyword`

结果摘要：

```text
total: 55
top trap_oid: __missing__ / 51
top source_ip: 172.25.131.3 / 55
top enterprise_oid: __missing__ / 51
```

说明：Trap 不做 MIB 翻译。`__missing__` 表示字段在文档中不存在。Task 5 中字段增强前入库的 Trap 只有 raw 和 varbinds，因此部分历史 Trap 没有 `trap_oid`、`enterprise_oid`。

## Findings

1. 最近 24 小时 Syslog 已可按设备、事件码、事件族、级别聚合统计。
2. 最近 24 小时 Trap 已可按来源 IP 聚合统计。
3. Trap OID 聚合中 `__missing__` 占比较高，这是字段增强前入库数据导致，不是接收失败。
4. Syslog `device_name` 中存在 `2026 / 10`，这是 Task 4 早期解析规则把年份误识别为设备名的历史残留；Task 4 已修复，后续新日志不应继续出现该问题。
5. Syslog `event_family=unknown` 数量较高，后续需要补充 PTP、QoS、RADIUS 等事件族映射。

## Commands

部署并执行脚本：

```bash
mkdir -p /opt/jscn-aiops/scripts /data/jscn-aiops/reports/task6
python3 /opt/jscn-aiops/scripts/task6_es_24h_summary.py \
  --es-url http://127.0.0.1:9200 \
  --out-dir /data/jscn-aiops/reports/task6 \
  --top-n 10
```

核心查询逻辑：

```json
{
  "size": 0,
  "track_total_hits": true,
  "query": {
    "range": {
      "@timestamp": {
        "gte": "now-24h",
        "lte": "now"
      }
    }
  },
  "aggs": {
    "top_field": {
      "terms": {
        "field": "field.keyword",
        "size": 10,
        "missing": "__missing__"
      }
    }
  }
}
```

## Acceptance Result

Task 6 验收项已完成：

1. 已从 Elasticsearch 查询最近 24 小时 Syslog 数据。
2. 已按 `device_ip`、`device_name`、`event_code`、`event_family`、`severity` 输出聚合统计。
3. 已从 Elasticsearch 查询最近 24 小时 Trap 数据。
4. 已按 `trap_oid`、`source_ip`、`enterprise_oid` 输出 TOP 排行。
5. 已输出 JSON 和 Markdown 摘要。
6. 已明确 Trap 未做 MIB 翻译。
