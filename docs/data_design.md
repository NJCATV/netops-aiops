# Data Design

## Index Naming

初期计划使用以下 Elasticsearch 索引命名：

```text
jscn-aiops-syslog-raw-YYYY.MM.DD
jscn-aiops-trap-raw-YYYY.MM.DD
jscn-aiops-syslog-parsed-YYYY.MM.DD
```

设计原则：

1. raw 索引用于完整留存原始消息。
2. parsed 索引用于查询、聚合、AI 报告统计。
3. 日期后缀便于生命周期管理、归档和迁移。
4. 索引前缀通过环境变量配置，避免写死。

## Syslog Raw Fields

| Field | Type | Description |
| --- | --- | --- |
| `@timestamp` | date | Elasticsearch 写入时间或接收时间 |
| `ingest_time` | date | 接收组件处理时间 |
| `source_ip` | keyword | Syslog 来源 IP |
| `source_port` | integer | Syslog 来源端口 |
| `raw_message` | text | 完整原始 Syslog |
| `receiver` | keyword | 接收组件标识 |
| `parse_status` | keyword | raw 阶段可为 `raw_only` |

## Syslog Parsed Fields

| Field | Type | Description |
| --- | --- | --- |
| `log_time` | date | 日志自身时间 |
| `source_ip` | keyword | 网络层来源 IP |
| `device_name` | keyword | 设备名 |
| `device_ip` | keyword | 设备管理 IP 或日志识别出的设备 IP |
| `module` | keyword | 日志模块 |
| `severity` | keyword | 告警级别 |
| `event_code` | keyword | 事件码 |
| `interface` | keyword | 接口名 |
| `slot` | keyword | 槽位 |
| `raw_message` | text | 完整原始 Syslog |
| `parse_status` | keyword | `parsed`、`partial`、`failed` |
| `event_family` | keyword | 事件族，如 interface、optical、ppp、routing |
| `key_signals` | keyword | 用于聚合和 AI 分析的关键信号 |

## SNMP Trap Raw Fields

Trap ????????????????????? MIB ???Task 16.2 ????? Trap ??? Logstash ????? OID ????? Trap ??? lookup ???

| Field | Type | Description |
| --- | --- | --- |
| `@timestamp` | date | Elasticsearch ????????? |
| `ingest_time` | date | ???????? |
| `source_ip` | keyword | Trap ?? IP |
| `source_port` | integer | Trap ???? |
| `raw_message` | text | ???? Trap ?? |
| `trap_oid` | keyword | ????? Trap OID |
| `enterprise_oid` | keyword | ?? OID |
| `trap_oid_name` | keyword | MIB OID translated object/notification name when available |
| `trap_oid_module` | keyword | MIB module name when available |
| `trap_oid_type` | keyword | MIB object type, such as `NOTIFICATION-TYPE` |
| `mib_translated` | boolean | Whether the Trap OID was translated by Logstash or backend lookup |
| `mib_lookup_source` | keyword | Translation source, such as `logstash_dictionary` or `mysql` |
| `trap_sender_ip` | keyword | UDP Trap sender observed by Logstash. This may be a relay or NMS, not the managed device. |
| `collector_source_ip` | keyword | Alias for the collector-observed Trap sender/source. |
| `snmp_agent_addr` | keyword | Valid SNMPv1 PDU agent address when available. `0.0.0.0` and `255.255.255.255` are ignored as device identity. |
| `managed_device_name` | keyword | Managed device name parsed from H3C Trap varbinds or existing parsed fields. |
| `managed_device_ip` | keyword | Resolved managed device IP from agent address, explicit Trap varbind, or MySQL `networkDevice.ip_address`. |
| `device_identity_source` | keyword | Identity resolution source: `snmp_agent_addr`, `varbind_device_ip`, `device_name_lookup`, `sender_fallback`, or `unknown`. |
| `device_identity_confidence` | float | Identity confidence from 0 to 1. |
| `device_ip` | keyword | Compatibility alias for `managed_device_ip`; must not be populated from relay/source IP unless `device_identity_source=sender_fallback`. |
| `device_name` | keyword | Compatibility alias for `managed_device_name`. |
| `parse_status` | keyword | `raw_only`?`partial`?`failed` |

Task 16.3 separates Trap sender identity from managed-device identity. `source_ip` is preserved for compatibility, but AI summary and investigation should use `managed_device_ip` / `managed_device_name` for device attribution. If a Trap only has sender IP and no managed identity, the backend should mark it as `unknown` or low-confidence `sender_fallback` instead of treating the sender as the failed device.

## MIB OID Mapping Table

Task 16.2 adds MySQL table `mib_oid_mappings` as the master data source for H3C MIB OID translation.

| Field | Description |
| --- | --- |
| `oid` | Numeric OID without leading dot |
| `name` | MIB object or notification name |
| `module` | MIB module name |
| `object_type` | MIB type, for example `OBJECT-TYPE` or `NOTIFICATION-TYPE` |
| `syntax` | Compact syntax string when present |
| `max_access` | Access mode when present |
| `status` | MIB status when present |
| `description_short` | Truncated description for operator context |
| `source_file` | Imported MIB text source file |
| `source_line` | Line number in source file |
| `is_notification` | Whether this row is a Trap notification |

Logstash dictionaries are generated from this table and used for new Trap ingestion. Backend lookup uses the same table to enrich historical Trap data and AI investigation output.

## Trap Alarm Definition Tables

Task 16.6 adds private NMS/vendor alarm definition enrichment. The source file is not a standard MIB; it is an exported alarm definition library with alarm names, severity, lifecycle type, reason, and suggestion.

Tables:

- `trap_alarm_definitions`
- `trap_alarm_oid_aliases`

`trap_alarm_definitions` stores one row per exported alarm definition:

| Field | Description |
| --- | --- |
| `vendor` | Auto-detected vendor label, such as `huawei`, `h3c`, or `unknown` |
| `enterprise_id` | Vendor enterprise OID from the export |
| `enterprise_name` | Enterprise display name from `trapEnterprise.enterpriseName` |
| `fault_oid` | Main alarm OID |
| `fault_oid_v1` | SNMPv1-compatible alarm OID when exported |
| `fault_oid_v2` | SNMPv2-compatible alarm OID when exported |
| `fault_name` | Human-readable alarm name |
| `severity` / `custom_severity` | Exported severity fields |
| `fault_type` | Exported occur/recover type |
| `lifecycle_status` | Normalized `active`, `recovered`, or `unknown` |
| `desc_info` / `fault_reason` / `suggestion` | Long text kept in MySQL and truncated before AI context |
| `source_file` | Import source filename |

`trap_alarm_oid_aliases` stores every matchable OID alias:

| Field | Description |
| --- | --- |
| `definition_id` | Parent alarm definition |
| `oid` | Matchable OID; unique |
| `oid_type` | `faultOid`, `faultOidV1`, `faultOidV2`, `recoverOid`, or `alias` |
| `vendor` | Copied vendor for filtering/export |
| `enterprise_id` | Copied enterprise OID |

Logstash alarm dictionaries are generated from these tables and write:

- `alarm_name`
- `alarm_severity`
- `alarm_lifecycle_status`
- `alarm_vendor`
- `alarm_enterprise_name`
- `alarm_definition_matched`
- `alarm_lookup_source`

Backend enrichment uses the same tables for historical Trap and AI investigation fallback, and may add truncated:

- `alarm_fault_reason`
- `alarm_suggestion`

Trap identity semantics after Task 16.6:

- `trap_sender_ip` and `collector_source_ip` are relay/source fields only.
- `snmp_agent_addr` is written only when it is a valid IP.
- `managed_device_ip` is the real managed device IP when it can be resolved.
- `device_ip` is only a compatibility alias for `managed_device_ip`; it must not be populated from Trap sender/relay IP.

## Future MySQL Tables

MySQL 初期不实现，后续用于保存报告、规则、设备清单和事件状态。

候选表：

1. `devices`：设备清单。
2. `ai_reports`：AI 报告元数据和报告路径。
3. `event_rules`：事件族、聚合规则和降噪规则。
4. `active_events`：活跃事件状态。
5. `event_history`：事件生命周期历史。

## AI Report Statistics JSON

第二阶段 Python Worker 应生成结构化 JSON，再调用 AI。

计划字段：

1. `time_window`：统计时间范围。
2. `total_logs`：总日志数。
3. `top_devices`：设备排行 TOP10。
4. `top_event_codes`：event_code 排行 TOP10。
5. `event_family_counts`：事件族统计。
6. `hourly_trend`：按小时趋势。
7. `parse_failed_count`：解析失败数量。
8. `sample_raw_messages`：典型原始日志样例。
9. `suspected_repeated_alerts`：疑似高频重复告警。

## Task 7 Configurable Syslog Parsing

Syslog parsing rules are now externalized:

- `config/event_family_rules.yml` classifies events from `event_code`, `module`, and keywords.
- `config/field_extract_rules.yml` extracts family-specific fields with regular expressions.

Replay output adds a derived `extracted_fields` object for validation. The current expected shape is:

| event_family | extracted_fields |
| --- | --- |
| `ppp_auth` | `username`, `domain` |
| `ptp_clock` | `slot`, `time_offset`, `threshold`, `suppression_count` |
| `bfd_flap` | `old_state`, `new_state`, `diag`, `linktype` |
| `optical_fault` | `interface`, `error_code`, `reason` |
| `radius` | `radius_server`, `server_ip`, `port` |
| `qos_congestion` | `slot`, `queue_id`, `interface`, `reason` |
| `interface_link` | `interface`, `old_state`, `new_state` |
| `device_fault` | `slot`, `reason` |
| `shell_security` | `username`, `command` |

Task 7 replay `parse_status` semantics:

- `parsed`: `event_family` is recognized and all configured core fields are extracted.
- `partial`: `event_family` is recognized, but one or more core fields are missing.
- `failed`: `event_family` is `unknown`.

The replay script does not write these derived values back to Elasticsearch. Task 8 should use this contract when designing `alarm_events`.

## Task 8 Alarm Events

Task 8 generates offline `alarm_events` from Syslog documents. The script does not write events back to Elasticsearch yet; it writes JSON and Markdown files for validation.

Output files:

- `reports/task8/task8_alarm_events.json`
- `reports/task8/task8_alarm_events.md`
- `docs/outputs/task8/task8_alarm_events.json`
- `docs/outputs/task8/task8_alarm_events.md`

Common `alarm_events` fields:

| Field | Description |
| --- | --- |
| `event_id` | Stable hash built from event type, aggregation key, first/last time, and count. |
| `event_type` | Aggregated event type, such as `PTP_CLOCK_JITTER`. |
| `event_family` | Source family from Task 7 rules. |
| `device_ip` | Device IP. |
| `device_name` | Device name. |
| `object_key` | Main affected object, such as username, slot, link type, interface, or queue. |
| `first_seen` | First log time in the event. |
| `last_seen` | Last log time in the event. |
| `duration_seconds` | Event duration in seconds. |
| `event_count` | Number of raw logs compressed into the event. |
| `event_status` | `open`, `recovered`, `recovered_or_flapping`, `recover_without_open`, or `clear_without_open`. |
| `severity_max` | Highest severity in the grouped logs. |
| `raw_log_samples` | Up to 5 raw logs for traceability. |
| `event_summary` | Deterministic summary generated by the aggregation script. |
| `aggregation_key` | The full grouping key, including time window. |

Initial event types:

| event_type | Source family | Window | Main grouping |
| --- | --- | ---: | --- |
| `PPP_AUTH_FAILURE` | `ppp_auth` | 5 min | `device_ip + username + domain` |
| `PTP_CLOCK_JITTER` | `ptp_clock` | 5 min | `device_ip + slot` |
| `BFD_FLAP` | `bfd_flap` | 5 min | `device_ip + session_id` when available, otherwise `device_ip + linktype + diag` |
| `OPTICAL_FAULT` | `optical_fault` | 10 min | `device_ip + interface`, fallback `device_ip + error_code` |
| `RADIUS_SERVER_ABNORMAL` | `radius` | 5 min | `device_ip + radius_server + server_ip` |
| `QOS_CONGESTION` | `qos_congestion` | 5 min | `device_ip + slot + queue_id` |

Task 8 is still offline. A later task should decide whether `alarm_events` are written to Elasticsearch, MySQL, or both.

## Task 8.1 Event Modes

Task 8.1 refines `alarm_events` into two event modes:

| event_mode | Meaning | Event types |
| --- | --- | --- |
| `lifecycle` | Tracks occur/recover, up/down, or suppression/resume status within a time window. | `PTP_CLOCK_JITTER`, `BFD_FLAP`, `OPTICAL_FAULT`, `INTERFACE_LINK`, `RADIUS_SERVER_ABNORMAL` |
| `statistical` | Summarizes high-volume repeated logs into metric-oriented event buckets. | `PPP_AUTH_FAILURE`, `QOS_CONGESTION` |

`PPP_AUTH_FAILURE` is now grouped by `device_ip + domain + 5-minute window` and includes these metrics:

- `username_count`
- `top_usernames`
- `total_failures`
- `user_focus_items`

`QOS_CONGESTION` is now grouped by `slot + queue_id + 5-minute window` and includes:

- `event_count`
- `top_devices`
- `top_queues`

`BFD_FLAP` now uses `session_id` when the raw message contains one. The current `session_id` is the endpoint pair inside `Sess[...]` before the first comma; this avoids over-splitting by LD/RD values.

Task 8.1 remains offline and read-only for Elasticsearch. It does not persist `alarm_events` to ES or MySQL.

## Task 9 Alarm Events Elasticsearch Index

Task 9 persists refined Task 8.1 `alarm_events` to Elasticsearch for Kibana queries, AI context building, and the future web API.

Index pattern:

- `jscn-aiops-alarm-events-YYYY.MM.DD`

Template:

- `deploy/elasticsearch/templates/alarm_events_template.json`

Primary fields:

| Field | Type | Description |
| --- | --- | --- |
| `event_id` | keyword | Stable document id used for idempotent upsert. |
| `event_type` | keyword | Aggregated event type, such as `PPP_AUTH_FAILURE` or `PTP_CLOCK_JITTER`. |
| `event_mode` | keyword | `lifecycle` or `statistical`. |
| `event_family` | keyword | Source family from Syslog parsing rules. |
| `device_ip` | keyword | Device IP. |
| `device_name` | keyword | Device name. |
| `object_key` | keyword | Main affected object for the event. |
| `first_seen` | date | First raw log timestamp in the event. |
| `last_seen` | date | Last raw log timestamp in the event. |
| `duration_seconds` | long | Event duration. |
| `event_count` | long | Raw log count compressed into the event. |
| `event_status` | keyword | `open`, `recovered`, `flapping_or_recovered`, `statistical`, or related lifecycle state. |
| `severity_max` | keyword | Highest severity observed in grouped logs. |
| `aggregation_key` | keyword | Full aggregation key, including time bucket. |
| `event_summary` | text | Deterministic event summary. |
| `raw_log_samples` | flattened | Up to 5 source log samples for traceability. |
| `extracted_metrics` | flattened | Event-specific metrics, such as top usernames, time offsets, or queue data. |
| `created_at` | date | Import creation time. |
| `updated_at` | date | Last import/update time. |

Duplicate handling:

- Elasticsearch `_id` is set to `event_id`.
- Re-running the import upserts the same document instead of creating duplicates.
- The script also keeps `aggregation_key + first_seen` available for future duplicate checks and troubleshooting.

This index stores operational event time-series data. It does not replace MySQL application metadata planned in later tasks.

## Task 10 Event Aggregator Checkpoint

The incremental event aggregation Worker keeps runtime progress outside Git:

- `/data/jscn-aiops/runtime/checkpoints/event_aggregator.json`

Checkpoint fields:

| Field | Description |
| --- | --- |
| `last_success_at` | End timestamp of the latest successful non-dry-run window. |
| `last_query_start` | Query start timestamp used in the latest successful run. |
| `last_query_end` | Query end timestamp used in the latest successful run. |
| `last_raw_syslog_count` | Number of raw Syslog documents read from Elasticsearch. |
| `last_prepared_log_count` | Number of logs kept after parsing and supported-family filtering. |
| `last_event_count` | Number of alarm events generated by the run. |
| `last_upserted_count` | Number of alarm event documents upserted to Elasticsearch. |
| `updated_at` | Checkpoint update timestamp. |

The checkpoint is runtime state and must not be committed to Git. Repeated runs remain idempotent because event documents are upserted by `event_id`.

## Task 11 MySQL Application Metadata

MySQL is introduced only for application management data. It must not store large Syslog, Trap, or alarm event time-series data; those remain in Elasticsearch.

Default connection settings:

| Item | Value |
| --- | --- |
| Host | `localhost` |
| Host port | `13306` |
| Database | `jscn_aiops` |
| User | `aiops` |

Tables:

| Table | Purpose |
| --- | --- |
| `users` | Login users, roles, password hashes, and account status. |
| `report_tasks` | Scheduled report definitions, time windows, recipients, and run timing. |
| `report_records` | Report generation metadata, status, file path, ES document reference, errors, and metrics. |
| `email_send_logs` | Email delivery records linked to report records. |
| `app_settings` | Small application settings, such as default report hours and mail enable flag. |
| `audit_logs` | Application operation audit records. |

Runtime initialization:

- `scripts/init_mysql.py` creates all tables through SQLAlchemy.
- The default admin user is created from `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
- Passwords are stored as Werkzeug password hashes.
- Real MySQL and admin passwords must be set in the runtime `.env`, not committed.

## Task 12 AI Report Context

Task 12 builds AI-ready context from Elasticsearch only. It does not call AI and does not write to MySQL.

Output path:

- `/data/jscn-aiops/reports/context/YYYYMMDD-HH-ai-context.json`

Local validation samples:

- `reports/task12/sample_ai_context.json`
- `reports/task12/sample_ai_context.md`

Context sections:

| Section | Description |
| --- | --- |
| `metadata` | Generation time, ES URL, and task purpose. |
| `window` | Current window, previous window, and baseline range. |
| `current_window.syslog` | Syslog total, hourly trend, TOP devices, TOP event codes, TOP families, and severity distribution. |
| `current_window.trap` | Trap total, TOP trap OID/source/enterprise, and same-device correlation hints with alarm events. |
| `current_window.alarm_events` | Event total, compressed raw-log count, TOP event types/devices/statuses, open events, recovered/flapping events, and key samples. |
| `baseline` | Seven-day daily counts, daily averages by event type/device, current-vs-previous comparison, and current-vs-baseline comparison. |
| `special_analysis` | PPP, PTP, BFD, Optical, Radius, and QoS focused metrics plus representative event details. |
| `topology_context` | Optional MySQL enrichment from `networkDevice` and `networkLinks`, including matched event devices, device role/status/model/version, related links, and link state counts. |

This JSON is the required input for the later AI report generator. AI prompts should use the structured metrics and event samples instead of re-querying raw logs directly.

When `topology_context.enabled` is `true`, AI report generation should use it to identify affected device roles, neighboring links, and possible service impact. If MySQL is unavailable, the context builder keeps this section disabled and still emits the rest of the report context.

## Task 16.5 Trap Topology Correlation

Trap identity is split into four layers:

| Layer | Field examples | Meaning |
| --- | --- | --- |
| Trap sender | `trap_sender_ip`, `collector_source_ip`, `source_ip` | UDP sender or relay. It must not be treated as the failed device. |
| Managed device | `managed_device_ip`, `managed_device_name` | Actual device identity when a valid agent address, explicit varbind, or `networkDevice` lookup exists. |
| Managed object | `managed_object_name`, `managed_object_address`, `topology_object_key` | Link/object carried by H3C Trap varbinds or raw text. This may exist even when `managed_device_ip` is null. |
| Topology link | `matched_link`, `endpoint_device_names`, `endpoint_interfaces` | Compact `networkLinks` match used to analyze both endpoints and interfaces. |

Invalid SNMP agent addresses such as `255.255.255.255`, `0.0.0.0`, and `\xFF\xFF\xFF\xFF` are ignored. Backend enrichment may leave `managed_device_ip=null`; it must not copy `trap_sender_ip` into device identity for relayed Traps.

`aiops/topology/lookup.py` reads MySQL metadata:

- `networkDevice` provides endpoint role, hierarchy, status, model, and management IP.
- `networkLinks` provides link name, state, source/target device, source/target interface, and endpoint IPs.

Trap candidates in `current_window_summary` include topology fields when available:

- `managed_object_name`
- `managed_object_address`
- `endpoint_device_names`
- `endpoint_interfaces`
- `topology_object_key`
- `topology_match`
- `matched_link`
- `related_device_roles`
- `topology_correlation_status`

`investigate_candidates` uses matched links or parsed endpoints to fetch compact related `alarm_events` for both sides of the link, focusing on interface, optical, BFD, RADIUS, and PTP event types. It returns compact event summaries instead of large raw log blocks.

Current limitations:

- The system does not rewrite historical ES documents.
- Matching is conservative; normalized names remove case and separators but do not perform broad fuzzy matching.
- If only `managed_object_name` is known, AI must not invent a device IP.
- If topology matching fails, AI should classify the Trap as `insufficient` or `watch`.

## Task 13 AI Reports

Task 13 generates Markdown reports from Task 12 context.

File output:

- `/data/jscn-aiops/reports/YYYY-MM-DD-HH-aiops-report.md`

MySQL metadata:

- Table: `report_records`
- Stores report title, window, status, file path, Elasticsearch reference, error message, summary, and compact metrics.

Elasticsearch index:

- `jscn-aiops-ai-reports-YYYY.MM.DD`
- Template: `deploy/elasticsearch/templates/ai_reports_template.json`

Primary ES fields:

| Field | Description |
| --- | --- |
| `report_id` | MySQL `report_records.id`. |
| `title` | Report title. |
| `status` | `success` or `failed`. |
| `model` | AI model name, default `deepseek-v4-pro`. |
| `context_path` | Source Task 12 context JSON path. |
| `report_path` | Markdown file path. |
| `window_start` / `window_end` | Report time window. |
| `markdown` | Generated Markdown body. |
| `context_summary` | Compact metrics copied from AI context. |

Real AI API keys must remain in runtime `.env` and must not be committed.

## Task 14 Current Window Summary

Task 14 adds a compact JSON input for the lightweight AIOps Agent MVP.

Output path example:

- `outputs/current_window_summary.json`

Builder:

- `aiops/context/current_window_summary.py`
- `scripts/build_current_window_summary.py`

Top-level sections:

| Section | Description |
| --- | --- |
| `metadata` | Generation time, current window start/end, and window hours. |
| `overview` | Syslog, Trap, alarm event, open/recovered/flapping, and compressed raw-log counts. |
| `critical_traps` | Trap candidates with reliable critical severity when available. |
| `important_traps` | Frequency-ranked Trap candidates when severity is unavailable or non-critical. |
| `open_incidents` | Compact `event_status=open` alarm events, with only 1-2 evidence samples. |
| `baseline_deviations` | Current-window count deviations from the normalized 7-day baseline. |
| `new_anomalies` | Patterns that are repeated now but rare in the lookback window. |
| `flapping_objects` | BFD, interface, optical, and PTP objects with repeated state changes. |
| `multi_device_correlations` | Common abnormal objects across multiple devices, such as Radius server or Trap OID. |
| `noise_candidates` | Stable, non-open, high-frequency event types that may be long-term noise. |
| `data_quality` | Unknown event-family, Trap MIB, topology, baseline, and field-missing notes. |

This summary does not replace the Task 12 full AI report context. The full context remains available for debugging and offline report analysis, while Task 14 is the initial input for the later lightweight Agent investigation flow.


## Task 15 Investigation Context

Task 15 adds bounded backend investigation for candidates selected from `current_window_summary`.

Builder:

- `aiops/tools/investigation.py`
- `scripts/investigate_candidates.py`

Input:

- Task 14 `current_window_summary` JSON.

Output path example:

- `/data/jscn-aiops/reports/task15/investigation_context_48h.json`

Top-level sections:

| Section | Description |
| --- | --- |
| `metadata` | Generation time, source summary window, candidate count, and purpose. |
| `investigations` | Bounded per-candidate investigation packages. |
| `data_quality` | Tool scope, limits, optional source notes, and no direct AI DB access flag. |

Each investigation contains related current events, historical events, related Trap evidence, a baseline snapshot, optional topology context, and optional historical AI memory. This tool intentionally avoids exposing arbitrary `search_events` to AI.

## Task 15 AI Tool Registry

Task 15 follow-up adds an AI-callable controlled tool layer:

- `aiops/tools/ai_tools.py`
- `AI_TOOLS`
- `get_tool_schemas()`
- `execute_ai_tool(tool_name, arguments)`

Registered tool names:

| Tool | Purpose |
| --- | --- |
| `investigate_candidates` | Primary bounded investigation from `current_window_summary`. |
| `get_related_events` | Compact related alarm events for known event/device/object constraints. |
| `get_device_history` | Compact bounded history for one device. |
| `get_object_history` | Compact bounded history for one object/event/device combination. |
| `get_topology_context` | Controlled topology lookup from MySQL metadata. |
| `get_baseline` | Current count versus historical baseline comparison. |

The registry is designed for Task 16. AI receives schemas or emits pseudo tool JSON, while backend code executes only these registered tools. Raw ES DSL and raw SQL are not accepted.

## Task 16 AI Agent Result JSON

Task 16 produces page-renderable structured JSON instead of Markdown.

Output path example:

- `/data/jscn-aiops/reports/task16/ai_agent_result.json`

Top-level sections:

| Section | Description |
| --- | --- |
| `metadata` | Analysis time, source window, model, tool call count, token usage, and data sources. |
| `overall_status` | Overall level, title, and short summary. |
| `summary_cards` | Compact dashboard counters. |
| `must_handle` | Findings that need active handling and have at least two evidence items. |
| `watch` | Items that need continued observation. |
| `noise` | Long-term stable or low-attention candidates. |
| `recovered` | Items considered recovered. |
| `insufficient` | Items where evidence is not enough for a conclusion. |
| `correlations` | Multi-device, same-object, same-time, or topology correlations. |
| `next_actions` | Prioritized operational actions. |
| `data_quality` | Known data issues and analysis notes. |

## Task 17 AI Findings, Memory, And Feedback

Task 17 persists lightweight Agent output into MySQL and uses operator feedback as compact memory for later investigations.

New MySQL tables:

| Table | Purpose |
| --- | --- |
| `ai_analysis_runs` | One row per `light_agent` run, including window, model, status, paths, tool/LLM counters, tokens, and runtime. |
| `ai_findings` | One row per Agent finding split from `must_handle`, `watch`, `noise`, `recovered`, `insufficient`, `correlations`, and `next_actions`. |
| `ai_finding_feedback` | Operator feedback for a finding, such as confirmed root cause, false positive, ignored, resolved, suppressed, escalated, or needs more data. |

`ai_analysis_runs` key fields:

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

`ai_findings` key fields:

- `finding_uid`
- `run_id`
- `category`
- `title`
- `severity`
- `confidence`
- `device_ip`
- `device_name`
- `object_key`
- `event_types`
- `root_cause_hypothesis`
- `impact`
- `reason`
- `evidence`
- `recommended_actions`
- `missing_data`
- `raw_finding`
- `finding_fingerprint`
- `lifecycle_status`
- `created_at`
- `updated_at`

`finding_fingerprint` is a stable SHA-256 based hash generated from category, event types, device identity, object key, and normalized title/action/reason text. It is used to match recurring findings across later windows.

`ai_finding_feedback.feedback_type` values:

- `confirmed`
- `false_positive`
- `ignored`
- `resolved`
- `suppressed`
- `escalated`
- `needs_more_data`

Feedback updates `ai_findings.lifecycle_status` so later analysis can distinguish active, resolved, ignored, false-positive, and suppressed findings.

AI memory retrieval:

1. `investigate_candidates` keeps using controlled backend tools only.
2. It now reads compact memory from `ai_findings` and `ai_finding_feedback`.
3. Matching prioritizes same `finding_fingerprint`, `device_ip`, `device_name`, `object_key`, and event type.
4. Records with operator feedback are preferred.
5. Tool output returns only compact memory fields: title, category, severity, confidence, lifecycle status, feedback type, actual root cause, action taken, created time, and run window.
6. Full `raw_finding`, raw logs, raw ES DSL, and raw SQL are not exposed to the Agent.

This closes the MVP memory loop without adding frontend pages, scheduler, email, login, automatic dispatch, or a multi-agent framework.
