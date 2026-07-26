# Task 7 Syslog Parsing Rules

## Scope

Task 7 adds a configurable Syslog parsing rule framework. It does not implement
event aggregation, AI calls, dashboards, or Trap MIB translation.

## Rule Files

- `config/event_family_rules.yml`: maps `event_code`, `module`, and keywords to
  `event_family`.
- `config/field_extract_rules.yml`: defines per-family core fields and regular
  expressions for `extracted_fields`.

Unknown events remain `unknown` and are reported for later rule expansion.

## Historical CSV Import

JSCN-20 did not initially contain the full 7-day export window in Elasticsearch.
For Task 7 validation, the uploaded historical exports were copied to:

```text
/data/jscn-aiops/imports/task7/Syslog-20260517142508.csv
/data/jscn-aiops/imports/task7/TrapList-20260517_142833.csv
```

Import command:

```bash
cd /opt/jscn-aiops
python3 scripts/import_exported_alarm_csv.py \
  --es-url http://127.0.0.1:9200 \
  --syslog-csv /data/jscn-aiops/imports/task7/Syslog-20260517142508.csv \
  --trap-csv /data/jscn-aiops/imports/task7/TrapList-20260517_142833.csv
```

Import result:

- Syslog: `50000` imported or updated
- Trap: `5690` imported or updated
- Failed: `0`

The importer uses stable document IDs derived from CSV fields, so re-running the
same import updates the same documents instead of creating duplicates.

## Replay Command

The replay script is read-only for Elasticsearch. It recomputes
`event_family`, `extracted_fields`, and `parse_status`, but does not write the
results back to Elasticsearch.

```bash
cd /opt/jscn-aiops
python3 scripts/replay_syslog_rules.py \
  --es-url http://127.0.0.1:9200 \
  --out-dir /data/jscn-aiops/reports/task7 \
  --batch-size 2000 \
  --top-n 15
```

## Outputs

Server outputs:

```text
/data/jscn-aiops/reports/task7/task7_parse_report.json
/data/jscn-aiops/reports/task7/task7_parse_report.md
/data/jscn-aiops/reports/task7/unknown_event_report.md
```

Repository copies:

```text
reports/task7/task7_parse_report.json
reports/task7/task7_parse_report.md
reports/task7/unknown_event_report.md
```

## Validation Result

Latest replay result:

- Total Syslog documents: `50887`
- Parsed: `49991`
- Partial: `890`
- Failed: `6`
- Unknown ratio: `0.01%`

Event family distribution:

| event_family | Count |
| --- | ---: |
| `ppp_auth` | 25335 |
| `ptp_clock` | 20152 |
| `radius` | 1823 |
| `bfd_flap` | 1316 |
| `qos_congestion` | 1314 |
| `optical_fault` | 490 |
| `shell_security` | 277 |
| `interface_link` | 152 |
| `device_fault` | 22 |
| `unknown` | 6 |

Unknown event codes:

| event_code | Count |
| --- | ---: |
| `LLDP_NEIGHBOR_AGE_OUT` | 5 |
| `CLK_REF_LOST` | 1 |

## Notes

- `PTP_SYNC_SUPPRESSION` does not always include `SuppressionCounts`; this is
  treated as an optional field, not a parse failure.
- QOS CPU queue congestion usually has `slot`, `queue_id`, and `reason`, but no
  interface. `slot` is the core field for current QOS samples.
- Interface link logs usually include `interface` and the new state only. The
  previous state is kept as an optional field for formats that provide it.
- Trap remains raw/basic only for Task 7. No MIB translation was added.
