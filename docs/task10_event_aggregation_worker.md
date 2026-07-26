# Task 10 Incremental Event Aggregation Worker

Task 10 turns the offline Task 8.1 aggregation into a repeatable worker. The worker reads parsed Syslog from Elasticsearch, generates alarm events with the existing configurable rules, writes events to `jscn-aiops-alarm-events-*`, and updates a checkpoint after a successful run.

## Scope

Implemented:

- Incremental query from `jscn-aiops-syslog-parsed-*`.
- Checkpoint file: `/data/jscn-aiops/runtime/checkpoints/event_aggregator.json`.
- Reuse of Task 7 parsing rules and Task 8.1 aggregation rules.
- Idempotent event upsert through `event_id`.
- `--once`, `--lookback-minutes`, and `--dry-run`.

Not implemented:

- Redis active event state.
- AI calls.
- Web UI.
- MySQL metadata.

## Manual Run

Run once without writing:

```bash
cd /opt/jscn-aiops
python3 workers/event_aggregation_worker.py --once --lookback-minutes 10 --dry-run
```

Run once and write alarm events:

```bash
cd /opt/jscn-aiops
python3 workers/event_aggregation_worker.py --once --lookback-minutes 10
```

Run continuously every 5 minutes:

```bash
cd /opt/jscn-aiops
python3 workers/event_aggregation_worker.py --interval-seconds 300
```

## Cron Example

```cron
*/5 * * * * cd /opt/jscn-aiops && /usr/bin/python3 workers/event_aggregation_worker.py --once --lookback-minutes 10 >> /data/jscn-aiops/logs/event_aggregation_worker.log 2>&1
```

## systemd Timer Example

Service:

```ini
[Unit]
Description=JSCN AIOps event aggregation worker

[Service]
Type=oneshot
WorkingDirectory=/opt/jscn-aiops
ExecStart=/usr/bin/python3 workers/event_aggregation_worker.py --once --lookback-minutes 10
User=aiops
Group=aiops
```

Timer:

```ini
[Unit]
Description=Run JSCN AIOps event aggregation worker every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

## Runtime Outputs

- Worker report: `/data/jscn-aiops/reports/task10/task10_worker_run_report.md`
- Per-run event JSON: `/data/jscn-aiops/reports/task10/YYYYMMDD-HHMMSS-worker-events.json`
- Checkpoint: `/data/jscn-aiops/runtime/checkpoints/event_aggregator.json`

The worker advances the checkpoint only when the run is not a dry run and all Elasticsearch upserts succeed.
