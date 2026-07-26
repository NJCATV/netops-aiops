# Current production cutover runbook (2026-07-17)

This runbook reflects the live topology discovered through the configured SSH aliases.
It supersedes the earlier full app-plane move for this deployment.

## Live topology

- `JSCN-233`: unified `/2026` frontend and NetOps BFF on TCP 7001.
- `JSCN-20`: platform-aware AIOps API on TCP 18080, AIOps MySQL on 13306,
  ELK, event worker, legacy scheduler and QQ adapter containers.
- `JSCN-236`: existing NetOps MySQL (`go_collector`); AIOps is not mixed into
  this schema.

Backups:

- 233: `/home/yvesyuan/deploy-backups/aiops-integration/20260717-161200`
- 20: `/opt/jscn-aiops/backups/20260717-161200`

## Privileged steps still required

### 1. Correct the 233 clock

```bash
ssh JSCN-233
sudo timedatectl set-ntp true
timedatectl status
```

Expected: `System clock synchronized: yes` and `NTP service: active`. The BFF
already uses the hardware RTC only when the system clock differs by more than five
minutes, so no application configuration change is needed after NTP becomes healthy.

### 2. Reload the scoped scheduler and signed QQ adapter on 20

The current source and environment are already staged in `/opt/jscn-aiops`. Compose
bind-mounts this directory, so image rebuilding is unnecessary.

```bash
ssh JSCN-20
cd /opt/jscn-aiops/deploy
sudo docker compose restart aiops-scheduler aiops-qq-adapter
sudo docker compose ps aiops-scheduler aiops-qq-adapter
```

Verify the protected QQ bridge without printing its token:

```bash
set -a
. /opt/jscn-aiops/deploy/.env
set +a
curl -fsS -H "Authorization: Bearer $QQ_ADAPTER_ADMIN_TOKEN" \
  http://127.0.0.1:18088/internal/status
```

After confirming the scheduler has restarted from the scoped source, enable task writes
in `/home/yvesyuan/.netops2026.json` on 233 and restart the user-owned 7001 process.
Until then, report-task GET is enabled and mutations intentionally return 503.

## Current user-owned services

- 233 startup script: `/home/yvesyuan/PycharmProjects/anbo_wx/backend/start-netops7001.sh`
- 20 API startup script: `/home/yvesyuan/jscn-aiops-releases/20260717-161200/runtime/start-api.sh`
- 20 scope sync: `/home/yvesyuan/jscn-aiops-releases/20260717-161200/runtime/sync-scope.sh`

Both API processes have `@reboot` cron entries; scope sync runs every five minutes
under `flock`.

## Rollback

1. Keep ELK and UDP ingestion running.
2. Restore 233 `netops2026.py`, `.netops2026.json` and the saved frontend tarball.
3. Restart the 7001 user process with its startup script.
4. Stop only the user-owned 18080 gunicorn process if the BFF is pointed back to the
   legacy 8080 API.
5. Restore `jscn_aiops.sql.gz` only when schema rollback is required. The migration is
   additive, so normal application rollback does not require dropping new columns.
