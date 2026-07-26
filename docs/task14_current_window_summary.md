# Task 14 Current Window Summary

Task 14 adds a compact `current_window_summary` builder for the lightweight AIOps Agent MVP. It does not call AI, does not modify the frontend, and keeps the old Task 12 full AI report context builder for debugging and offline analysis.

## Scope

Implemented:

- Added `aiops/context/current_window_summary.py`.
- Added `build_current_window_summary()`.
- Added `scripts/build_current_window_summary.py`.
- Generates JSON only.
- Keeps raw log evidence compact: `open_incidents.evidence_samples` is limited to 1-2 items and no full `raw_log_samples` field is emitted.
- Supports configurable limits for all candidate sections.

Not implemented:

- No DeepSeek or other AI call.
- No Agent framework.
- No frontend changes.
- No database writes.
- No changes to Syslog or Trap ingestion.

## Command

```bash
cd /opt/jscn-aiops
python3 scripts/build_current_window_summary.py \
  --hours 7 \
  --output outputs/current_window_summary.json
```

Useful runtime options:

```bash
python3 scripts/build_current_window_summary.py \
  --hours 7 \
  --baseline-days 7 \
  --open-incidents-limit 50 \
  --baseline-deviations-limit 30 \
  --new-anomalies-limit 30 \
  --flapping-objects-limit 30 \
  --multi-device-correlations-limit 30 \
  --noise-candidates-limit 20
```

## Output Sections

The JSON contains:

- `metadata`
- `overview`
- `critical_alarm_candidates`
- `critical_traps`
- `important_traps`
- `important_trap_candidates`
- `open_incidents`
- `baseline_deviations`
- `new_anomalies`
- `flapping_objects`
- `multi_device_correlations`
- `noise_candidates`
- `data_quality`

`current_window_summary` is intended as the first input to the later lightweight Agent flow. It is smaller and more selective than the Task 12 full report context.

`critical_alarm_candidates` was added after Task 16 gap analysis to make urgent/important physical alarms stable for Agent consumption. It includes compact open interface/optical/hardware-style candidates and important Trap candidates. This section is intentionally bounded and does not include full raw logs.

## Candidate Logic

`open_incidents` reads `alarm_events` and keeps only `event_status=open`, prioritizing:

- `OPTICAL_FAULT`
- `INTERFACE_LINK`
- `BFD_FLAP`
- `RADIUS_SERVER_ABNORMAL`
- `PTP_CLOCK_JITTER`
- `QOS_CONGESTION`

After Task 16.1, open incident sorting gives higher priority to unresolved interface Down, physical Down, Line protocol Down, optical, board/card, fan, power, and temperature style alarms so that long-running PPP/PTP-style noise does not push out key physical faults.

`critical_alarm_candidates` is built from:

- compact `open_incidents` that match critical physical/interface/optical/hardware keywords;
- compact Trap groups from the current window.

Current Trap data is treated as upstream-filtered critical/important input. After Task 16.2, the summary prefers translated Trap fields already stored in Elasticsearch and falls back to MySQL MIB lookup for historical Trap documents. It still does not perform full Trap normalization or severity inference.

`baseline_deviations` compares current-window counts with the previous 7-day baseline normalized to the current window length.

`new_anomalies` checks repeated current patterns with very low 7-day lookback counts.

`flapping_objects` focuses on BFD, interface, optical, and PTP repeated state-change signals.

`multi_device_correlations` groups common objects across devices, including Radius server, BFD peer/session, PTP slot, QoS queue, optical object, interface object, and Trap OID.

`noise_candidates` marks stable non-open high-frequency event types as low-attention candidates. AI still makes the final judgment in later tasks.

## Validation

Local syntax and CLI checks passed:

```bash
python -m py_compile aiops/context/current_window_summary.py scripts/build_current_window_summary.py
python scripts/build_current_window_summary.py --help
```

JSCN-20 read-only validation with the requested 7-hour window:

```bash
python scripts/build_current_window_summary.py \
  --es-url http://172.25.60.20:9200 \
  --hours 7 \
  --output outputs/current_window_summary.json
```

Result:

- Syslog total: `2983`
- Trap total: `800`
- Alarm event total: `0`
- Output size: `10565` bytes

The 7-hour window had Syslog and Trap data, but no matching `alarm_events` documents. This indicates the event aggregation worker had not produced current-window event documents for that exact window.

Extended 48-hour validation confirmed candidate extraction:

- Alarm event total: `4338`
- Open incidents: `50`
- Baseline deviations: `22`
- Flapping objects: `30`
- Multi-device correlations: `6`
- Noise candidates: `1`

Observed examples:

- Open incidents include `BFD_FLAP`, `INTERFACE_LINK`, and `OPTICAL_FAULT`.
- Multi-device correlations include Radius server `111.208.114.150` across `3` devices.
- Flapping objects include `PTP_CLOCK_JITTER`, `BFD_FLAP`, `INTERFACE_LINK`, and `OPTICAL_FAULT`.
- Noise candidates include stable high-frequency `PPP_AUTH_FAILURE`.

## Data Quality Notes

Current known limitations:

- Trap severity is not reliably available, so `critical_traps` may be empty and `important_traps` is frequency-ranked.
- Current Trap input has already been filtered upstream as critical/important, so `important_traps` and `important_trap_candidates` should be treated as AI attention candidates even when MIB translation is incomplete.
- Trap MIB translation is partial. H3C MIB OID names are available when the OID exists in `mib_oid_mappings`; missing OIDs remain raw and are counted in `data_quality`.
- Topology context is not included in Task 14 summary.
- If the event aggregation worker is not current, `alarm_events`-based sections can be empty even when raw Syslog and Trap data exist.
