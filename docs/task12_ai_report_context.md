# Task 12 AI Report Context Builder

Task 12 builds structured context for the later AI report generator. It queries Elasticsearch, summarizes current alarms and historical baselines, and saves JSON for the AI step. It does not call AI.

## Command

```bash
cd /opt/jscn-aiops
python3 scripts/build_ai_report_context.py --hours 24 --baseline-days 7 --sample-md reports/task12/sample_ai_context.md
```

## Outputs

- Context JSON: `/data/jscn-aiops/reports/context/YYYYMMDD-HH-ai-context.json`
- Validation Markdown: `reports/task12/sample_ai_context.md`

The repository archives the latest validation samples under:

- `reports/task12/sample_ai_context.json`
- `reports/task12/sample_ai_context.md`

## Context Contents

The JSON includes:

- Current window Syslog count, hourly trend, TOP devices, TOP event codes, TOP event families, and severity distribution.
- Current window Trap count, TOP trap OID, TOP source IP, TOP enterprise OID, and same-device correlation hints.
- Current window alarm event count, TOP event types, TOP devices, status distribution, open events, recovered/flapping events, and representative event samples.
- Seven-day baseline daily counts and averages by event type/device.
- Current window compared with the previous window and the seven-day average.
- Focused PPP, PTP, BFD, Optical, Radius, and QoS analysis.
- Optional topology enrichment from MySQL `networkDevice` and `networkLinks`.

## JSCN-20 Validation

Latest validation:

- Syslog total: `10506`
- Trap total: `1085`
- Alarm events total: `3376`
- Compressed raw-log count in events: `9972`
- Topology inventory devices: `62`
- Topology inventory links: `1086`
- Matched current event devices: `10`
- Related links for matched devices: `228`

TOP event types:

| event_type | Count |
| --- | ---: |
| `PPP_AUTH_FAILURE` | 2852 |
| `PTP_CLOCK_JITTER` | 287 |
| `QOS_CONGESTION` | 144 |
| `RADIUS_SERVER_ABNORMAL` | 59 |
| `BFD_FLAP` | 52 |
| `OPTICAL_FAULT` | 52 |
| `INTERFACE_LINK` | 10 |

## Scope Boundary

This task does not call AI, write MySQL records, generate final AI Markdown reports, or send email.

MySQL is read-only in this task and is used only to enrich AI context with device and link metadata.
