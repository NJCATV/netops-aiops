# Demo Guide

This guide walks through the current end-to-end demo path.

## Start

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d
docker-compose ps
```

Open:

```text
http://<server>:5772/
```

## Demo Flow

1. Log in to the Web console.
2. Open System Overview and confirm 1h, 3h, and 24h counts for Syslog, Trap, and alarm_events.
3. Open realtime Syslog and confirm recent parsed events are visible.
4. Open Trap and confirm `trap_sender_ip` is shown separately from managed device and managed object fields.
5. Open alarm_events and confirm aggregated events show event type, device/object, status, count, first seen, and last seen.
6. Open AI Analysis and trigger a manual analysis for 4h, 12h, 24h, or a custom window.
7. Watch the run move from `running` to `success` or `failed`.
8. Open AI History, view the run detail, and inspect must_handle, watch, noise, recovered, insufficient, correlations, next_actions, and data_quality.
9. Add feedback to a finding as an admin user.
10. Open Scheduled Tasks, create an interval or daily task, disable/enable it, and run it immediately.

## Evidence Chain

Syslog / Trap ingestion
-> MIB translation
-> Trap topology enrichment
-> alarm_events aggregation
-> Web realtime tables
-> manual AI analysis
-> AI findings and feedback
-> scheduled AI task execution

## Notes

Viewer users can only read. Admin users can trigger AI analysis, configure scheduled tasks, and add feedback.
