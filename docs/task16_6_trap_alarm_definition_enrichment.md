# Task 16.6 Trap Alarm Definition Enrichment

## Goal

接入综合网管/厂商网管导出的私有告警定义库，用它补足 SNMP Trap 的告警名称、级别、发生/恢复状态、原因和建议。该文件不是标准 MIB；它是网管告警定义库，字段包括 `faultOid`、`faultOidV1`、`faultOidV2`、`faultName`、`severity`、`faultType`、`descInfo`、`faultReason`、`suggestion` 等。

告警定义库和 MIB OID 字典并行使用：

- 告警定义库负责告警语义、级别、生命周期和处置上下文。
- MIB OID 字典负责对象/通知名、模块名和 MIB 类型。
- 新 Trap 入库优先由 Logstash alarm dictionary 匹配；历史 Trap 由 backend MySQL lookup 兜底。

## Data Model

新增 MySQL 表：

- `trap_alarm_definitions`
- `trap_alarm_oid_aliases`

`faultOid`、`faultOidV1`、`faultOidV2` 都写入 alias 表，支持 SNMPv1/SNMPv2 Trap OID 形态。`trap_alarm_oid_aliases.oid` 唯一，避免同一 OID 多义写入 Logstash 字典。

## Import And Dictionary Export

源文件：

```text
/data/jscn-aiops/mib/OID_export.txt
```

导入命令：

```bash
python3 scripts/import_trap_alarm_definitions.py \
  --source /data/jscn-aiops/mib/OID_export.txt \
  --vendor auto \
  --env-file deploy/.env \
  --replace
```

验证结果：

- source total: `8928`
- imported definitions: `8928`
- unique aliases: `26689`
- vendor distribution: `unknown=5476`, `h3c=2285`, `huawei=1167`
- alias types: `faultOid=8895`, `faultOidV1=8880`, `faultOidV2=8914`

Logstash dictionary export:

```bash
python3 scripts/export_logstash_trap_alarm_dictionary.py \
  --env-file deploy/.env \
  --output-dir /data/jscn-aiops/logstash/mib
```

Generated files:

- `trap_alarm_name.json`
- `trap_alarm_severity.json`
- `trap_alarm_lifecycle.json`
- `trap_alarm_vendor.json`
- `trap_alarm_enterprise_name.json`
- `trap_alarm_suggestion.json`

Exported dictionary entries: `26689`.

## Logstash And Backend Enrichment

`deploy/logstash/pipeline/trap.conf` now adds:

- `alarm_name`
- `alarm_severity`
- `alarm_lifecycle_status`
- `alarm_vendor`
- `alarm_enterprise_name`
- `alarm_definition_matched`
- `alarm_lookup_source=logstash_alarm_dictionary`

Existing MIB fields are preserved:

- `trap_oid_name`
- `trap_oid_module`
- `trap_oid_type`
- `mib_translated`
- `mib_lookup_source`

Backend lookup module:

- `aiops/trap/alarm_definition_lookup.py`

Backend enrichment writes compact AI-safe fields:

- `alarm_fault_reason`
- `alarm_suggestion`
- `alarm_definition_matched`
- `alarm_lookup_source=mysql`

Long `descInfo` / `faultReason` / `suggestion` are truncated before they enter summary or tool output.

## Trap Identity Semantics

Trap identity rules after this task:

- `trap_sender_ip` / `collector_source_ip` are UDP sender or NMS relay addresses.
- `172.25.131.3` is not used as `device_ip`.
- invalid SNMPv1 agent addresses such as `0.0.0.0`, `255.255.255.255`, and `\xFF\xFF\xFF\xFF` are ignored.
- `managed_device_ip` is resolved only from valid `snmp_agent_addr`, explicit varbind device IP, or `networkDevice.device_name -> ip_address`.
- `device_ip` is only a compatibility alias for `managed_device_ip`.
- link Trap analysis should prefer `managed_object_name`, `endpoint_device_names`, `endpoint_interfaces`, and `matched_link`.

## Historical Backfill

Dry-runs:

- 24h dry-run scanned `339`, alarm definition matched `321`.
- 7d dry-run scanned `7055`, alarm definition matched `6921`.

Formal backfill:

```bash
python3 scripts/backfill_trap_enrichment.py \
  --days 7 \
  --batch-size 500 \
  --env-file deploy/.env
```

Result:

- scanned: `7055`
- updated: `7055`
- bulk error items after raising recent Trap index field limit to `2000`: `0`
- alarm definition matched: `6921`
- MIB translated: `4862`
- object extracted: `4637`
- topology link matched: `1870`

Post-backfill 7d ES checks:

- `alarm_definition_matched=true`: `6921`
- `alarm_definition_matched=false`: `134`
- `device_ip=172.25.131.3`: `0`
- invalid `snmp_agent_addr`: `0`

## Summary And Investigation Validation

24h summary:

- `important_traps`: `30`
- `critical_alarm_candidates`: `36`
- `trap_alarm_definition_matched_count`: `316`
- `trap_alarm_definition_unmatched_count`: `18`
- `trap_mib_translated_count`: `143`
- `trap_mib_untranslated_count`: `191`
- `trap_object_extracted_count`: `334`
- `trap_topology_link_matched_count`: `161`
- `trap_topology_link_unmatched_count`: `173`
- `trap_sender_as_device_ip_count`: `0`

Example enriched Trap candidate:

- alarm name: `计费服务器DOWN`
- alarm severity: `2`
- vendor: `h3c`
- sender: `172.25.131.3`
- managed device IP: IPv6 management address, not the sender

`investigate_candidates` validation:

- Top40 investigation included `30` Trap candidates.
- Trap candidates returned related `alarm_events`, related Trap evidence, and AI memory where available.
- Link Trap candidates matched `networkLinks`; example `YGM-16K-M-A To CN16K-F-HeXinA Link3 IPv6` matched `link_id=634`.

## Light Agent Validation

Command:

```bash
python3 scripts/run_light_agent.py \
  --summary-json outputs/task16_6/current_window_summary_24h.json \
  --output outputs/task16_6/light_agent_24h.json \
  --max-tool-rounds 2 \
  --env-file deploy/.env
```

Result:

- output JSON: valid
- tool calls: `2`
- final findings in `must_handle`: `3`
- recovered section included recovered items
- `172.25.131.3` appeared only in data-quality notes as Trap relay/source, not as a faulty device
- total tokens: `308725`

The token cost is still too high for routine frontend/API workflows. A compact frontend summary profile is still recommended before broad Vue page development.

## Remaining Gaps

- `134` Trap documents in the 7d window still do not match the alarm definition library.
- `191` recent 24h Trap records remain MIB-untranslated, although most now have alarm definitions.
- Summary size remains large for interactive AI use.

## Frontend Readiness

Backend Trap semantics are now much safer for API/UI consumption than before this task. It is reasonable to start a small Flask/Vue read-only workflow that consumes backend-enriched summary/investigation DTOs, but broad operational frontend work should still wait for a compact summary profile to reduce token and latency cost.
