# Task 16.4 Alarm Event Worker Runtime

## Problem

`syslog-parsed` and `trap-raw` can keep receiving fresh data while `alarm_events` stops advancing if `event_aggregation_worker.py` is only started manually. In that state the AI context sees fresh Trap data but stale or empty alarm events, which can lead to Trap-only analysis.

This task moves the alarm event aggregation worker into Docker Compose so `docker-compose up -d` starts it with Elasticsearch and Logstash.

## Existing Worker Check

- Current entry: `workers/event_aggregation_worker.py`.
- It supports `--once`, `--interval-seconds`, `--lookback-minutes`, and `--dry-run`.
- The original worker can run continuously, but it advances from a checkpoint by default.
- It writes generated events through `scripts/write_alarm_events_to_es.py`.
- Elasticsearch writes are idempotent because `bulk_upsert()` uses `_id = event_id` and `doc_as_upsert: true`.
- `event_id` and `fingerprint` are now stable hashes of `event_type + aggregation_key`. The aggregation key already includes the event bucket start, event type, device/object grouping fields, and configured window. Re-running the same window updates the same ES document instead of inserting another copy.

## Runtime Design

The Compose service runs `scripts/run_event_aggregation_worker.py`, which wraps the existing aggregation worker in fixed-lookback micro-batches:

- default interval: `300` seconds;
- default lookback: `30` minutes;
- each round queries `now - lookback` to `now`;
- each round reuses the existing family, field extraction, and aggregation rules;
- each round logs window start/end, scanned count, generated count, written count, elapsed time, and errors;
- exceptions are logged and the loop continues unless `--once` was used.

This is a periodic micro-batch rather than per-log realtime processing because the current rules aggregate by short windows and lifecycle pairs. A small lookback tolerates late-arriving syslog documents and Logstash/ES indexing delay while keeping implementation simple and rerunnable.

## Current Window Summary

`current_window_summary` is not scheduled here. It should be generated immediately before AI analysis so the AI sees the same fresh window used for that run. Scheduling it separately can create stale summaries even when source data is current.

## Docker Compose

After deploying the updated code and runtime `.env`:

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d
```

Start only the worker:

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d aiops-event-worker
docker-compose ps
docker-compose logs --tail=100 aiops-event-worker
```

Configurable environment variables:

```bash
ALARM_EVENT_WORKER_INTERVAL_SECONDS=300
ALARM_EVENT_WORKER_LOOKBACK_MINUTES=30
ALARM_EVENT_WORKER_ES_URL=http://elasticsearch:9200
```

On JSCN-20, Docker Hub was not directly reachable during verification, so runtime `deploy/.env` was set to an already reachable mirror image:

```bash
AIOPS_PYTHON_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.11-slim
```

## Dry Run

```bash
cd /opt/jscn-aiops
python3 scripts/run_event_aggregation_worker.py \
  --once \
  --dry-run \
  --lookback-minutes 180 \
  --env-file deploy/.env
```

## One-Time Backfill

Recent 6 hours:

```bash
cd /opt/jscn-aiops
python3 scripts/run_event_aggregation_worker.py \
  --once \
  --lookback-minutes 360 \
  --env-file deploy/.env
```

Recent 24 hours:

```bash
cd /opt/jscn-aiops
python3 scripts/run_event_aggregation_worker.py \
  --once \
  --lookback-minutes 1440 \
  --env-file deploy/.env
```

## Freshness Check

```bash
cd /opt/jscn-aiops
python3 scripts/check_alarm_event_freshness.py --max-lag-minutes 30 --env-file deploy/.env
python3 scripts/check_alarm_event_freshness.py --max-lag-minutes 30 --json --env-file deploy/.env
```

The script reports:

- latest parsed syslog timestamp;
- latest alarm event `last_seen`;
- lag in minutes;
- 1h, 3h, and 24h counts for syslog, trap, and alarm events;
- warning when alarm events lag beyond the threshold.

## AI Verification Flow

Regenerate the summary only when AI analysis is about to run:

```bash
cd /opt/jscn-aiops
python3 scripts/build_current_window_summary.py --hours 24 --env-file deploy/.env
```

Then run the light agent against that fresh summary:

```bash
python3 scripts/run_light_agent.py \
  --summary-json outputs/current_window_summary.json \
  --output outputs/light_agent_result.json \
  --env-file deploy/.env
```

Expected result after backfill and worker startup: `alarm_event_total > 0`, and the light agent analysis should include alarm event evidence instead of pure Trap-only conclusions.

## Local Verification

- `python -m py_compile workers/event_aggregation_worker.py scripts/run_event_aggregation_worker.py scripts/check_alarm_event_freshness.py` passed.
- On JSCN-20, dry-run over the latest 3 hours scanned `1534` Syslog documents, prepared `1528` aggregatable logs, and generated `529` candidate alarm events.
- A one-time 24-hour backfill scanned `11790` Syslog documents, prepared `11695` aggregatable logs, generated `4173` alarm events, and upserted `4173` documents with zero errors.
- Freshness after worker startup: latest Syslog `2026-05-19T03:04:17.762000Z`, latest alarm event `2026-05-19T03:04:07.077000Z`, lag `0.18` minutes, warning `false`.
- Recent counts after recovery: 1h `syslog=460`, `trap=13`, `alarm_events=180`; 3h `syslog=1528`, `trap=43`, `alarm_events=524`; 24h `syslog=11788`, `trap=290`, `alarm_events=4171`.
- `docker-compose up -d aiops-event-worker` started `jscn-aiops-event-worker`. First Compose-managed round scanned `234`, prepared `234`, generated `97`, wrote `97`, and reported zero errors.
- Rebuilt 24-hour `outputs/current_window_summary.json`: `syslog_total=11788`, `trap_total=290`, `alarm_event_total=4171`.
- Re-ran light Agent with `max-tool-rounds=2`: output `outputs/task16_4/light_agent_result.json`, `ok=true`, `tool_call_count=2`, `must_handle_count=2`, and the result referenced both alarm event and Trap evidence.
