# Task 16.2 H3C MIB OID Translation

## Goal

Task 16.2 adds H3C MIB OID translation for Trap handling without introducing a full MIB compiler or changing Syslog collection.

The design has two paths:

1. Logstash translates new Trap documents at ingestion time using generated OID dictionaries.
2. Backend lookup enriches historical Trap documents and AI investigation output when ES documents do not already contain translated fields.

Trap severity is still determined by upstream filtering. This task does not infer severity from MIB names.

## Data Model

MySQL table:

- `mib_oid_mappings`

Important columns:

- `oid`
- `name`
- `module`
- `object_type`
- `syntax`
- `max_access`
- `status`
- `description_short`
- `source_file`
- `source_line`
- `is_notification`

The table stores compact metadata only. Long MIB descriptions are truncated by the import script and are not sent wholesale to AI.

## Import

Source file used in validation:

```text
/data/jscn-aiops/mib/h3c_mib_objects.txt
```

Import command:

```bash
cd /opt/jscn-aiops
python3 scripts/import_mib_oid_map.py \
  --input /data/jscn-aiops/mib/h3c_mib_objects.txt \
  --env-file deploy/.env \
  --batch-size 2000
```

Validation result:

- Imported or updated OID mappings: `43515`
- `NOTIFICATION-TYPE` mappings: `2338`

Example lookup results:

- `1.3.6.1.4.1.25506.2.4.4.0.5` -> `hh3cCfgFileChange`, `HH3C-CONFIG-MAN-MIB`
- `1.3.6.1.4.1.25506.2.6.4.0.54` -> `hh3cEntityExtOpticalWarningClear`, `HH3C-ENTITY-EXT-MIB`

## Logstash Dictionary Export

Export command:

```bash
python3 scripts/export_logstash_mib_dictionary.py \
  --env-file deploy/.env \
  --output-dir /data/jscn-aiops/logstash/mib \
  --notifications-only
```

Generated files:

- `/data/jscn-aiops/logstash/mib/h3c_oid_name.json`
- `/data/jscn-aiops/logstash/mib/h3c_oid_module.json`
- `/data/jscn-aiops/logstash/mib/h3c_oid_type.json`

Validation result:

- Exported dictionary entries: `2338`
- Dictionary directory size: about `400 KB`

## Logstash Ingestion Translation

`deploy/logstash/pipeline/trap.conf` now uses three `translate` filters after `trap_oid` extraction:

- `trap_oid_name`
- `trap_oid_module`
- `trap_oid_type`

It also writes:

- `mib_translated`
- `mib_lookup_source=logstash_dictionary`

`deploy/docker-compose.yml` mounts:

```text
/data/jscn-aiops/logstash/mib -> /usr/share/logstash/mib
```

Important deployment note:

When adding this mount to an existing container, `docker-compose restart logstash` is not enough. The container must be recreated once:

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d logstash
```

Server validation:

- Logstash pipeline restarted and is running.
- New Trap documents after restart include translated fields.
- Example new Trap:

```json
{
  "trap_oid": "1.3.6.1.4.1.25506.2.13.3.0.2",
  "trap_oid_name": "hh3cRadiusAccServerUpTrap",
  "trap_oid_module": "HH3C-RADIUS-MIB",
  "mib_translated": true,
  "mib_lookup_source": "logstash_dictionary"
}
```

## Backend Lookup And Enrichment

New modules:

- `aiops/mib/lookup.py`
- `aiops/mib/trap_enrichment.py`

Backend behavior:

- Prefer translated fields already present in ES.
- If missing, lookup `trap_oid` from MySQL.
- If still missing, keep the raw OID and mark `mib_translated=false`.

This is used by:

- `current_window_summary`
- `investigate_candidates` related Trap evidence

## Summary And Agent Validation

Summary command:

```bash
python3 scripts/build_current_window_summary.py \
  --hours 48 \
  --env-file deploy/.env \
  --output /data/jscn-aiops/reports/task16_2/current_window_summary.json
```

Validation result:

- `important_traps` now includes readable names where mappings exist.
- `data_quality` includes MIB lookup metrics:
  - `mib_lookup_available=true`
  - `mib_lookup_hits=283`
  - `mib_lookup_misses=213`
  - `mib_es_translated_hits=4`
  - `trap_mib_translated_count=287`
  - `trap_mib_untranslated_count=213`

Agent validation:

```bash
python3 scripts/run_light_agent.py \
  --summary-json /data/jscn-aiops/reports/task16_2/current_window_summary.json \
  --output /data/jscn-aiops/reports/task16_2/ai_agent_result.json \
  --max-tool-rounds 2 \
  --env-file deploy/.env
```

Result:

- Output JSON is valid.
- Translated Trap names appear in AI output, including:
  - `hh3cCfgFileChange`
  - `hh3cRadiusAccServerUpTrap`
  - `hh3cEntityExtSFPPhony`
  - `hh3cEntityExtOpticalWarningClear`
- The AI no longer has to describe these translated candidates only as bare OIDs.

Runtime:

- Duration: `358514 ms`
- Tool calls: `2`
- Total tokens: `149134`
- `investigate_candidates` result size: `30168 bytes`

## Current Limits

Not implemented in this task:

- Full MIB compiler.
- Full Trap normalization into standard alarm events.
- Severity inference from MIB names.
- AI direct MySQL or ES access.
- Dify, LangGraph, MCP, or multi-agent orchestration.

Some H3C private OIDs from `1.3.6.1.4.1.25506.4.2.59.2` are not present in the provided expanded MIB text and remain untranslated. They are preserved as raw OIDs and surfaced in `insufficient` when relevant.
