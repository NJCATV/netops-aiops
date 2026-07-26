# AIOps split deployment runbook (JSCN-233 + JSCN-20)

## Final placement

- `233`: unified web, NetOps API/BFF, AIOps API, AIOps scheduler, one MySQL 8 instance with separate `anbo_wx` and `jscn_aiops` schemas.
- `20`: Elasticsearch, Kibana, Logstash, alarm-event worker, NapCat and QQ adapter.
- Do not move Elasticsearch data to `233`; its heap, disk I/O and retention workload must remain isolated from the user-facing control plane.

## Preflight and backup

1. Fix NTP on `233`; HMAC identity envelopes allow only 90 seconds of clock skew.
2. Freeze AIOps metadata writes for the short MySQL dump window. ELK ingestion may continue.
3. Back up both databases and the active configuration:

```bash
mysqldump --single-transaction --routines --triggers jscn_aiops | gzip > /data/jscn-aiops/backups/jscn_aiops-pre-merge.sql.gz
mysqldump --single-transaction --routines --triggers anbo_wx | gzip > /data/backups/anbo_wx-pre-aiops.sql.gz
cp /home/yvesyuan/.netops2026.json /home/yvesyuan/.netops2026.json.pre-aiops
```

4. Generate one 64-byte shared secret and install the same value on both hosts; never commit it:

```bash
openssl rand -hex 64
```

## MySQL move to 233

1. Create `jscn_aiops` and a least-privilege `aiops` account on the existing MySQL instance.
2. Restore the dump into `jscn_aiops`.
3. Run `python scripts/migrate_platform_integration.py --dry-run`, review the plan, then run it without `--dry-run`. The raw SQL file remains available for DBA review, while the runner is idempotent and records its migration ID.
4. Create a read-only `netops_scope_reader` account limited to the OLT, CMTS and organization mapping tables required by `scripts/sync_platform_device_scope.py`.
5. Run the scope projection and verify row counts before enabling the BFF.

## Application plane on 233

```bash
sudo install -d -o yvesyuan -g yvesyuan /opt/jscn-aiops /data/jscn-aiops/reports
rsync -a --delete --exclude '.git' --exclude 'deploy/.env*' ./ /opt/jscn-aiops/
python3 -m venv /opt/jscn-aiops/.venv
/opt/jscn-aiops/.venv/bin/pip install -r /opt/jscn-aiops/requirements.txt
sudo install -d -m 0750 /etc/jscn-aiops
sudo install -m 0640 deploy/app-plane.env /etc/jscn-aiops/app.env
sudo install -m 0644 deploy/systemd/jscn-aiops-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jscn-aiops-api jscn-aiops-scheduler jscn-aiops-scope-sync.timer
```

Only `172.25.60.20` and localhost may reach TCP `18080`. Only `172.25.60.233` may reach the QQ adapter internal TCP `18088`; its status/audit endpoints require `QQ_ADAPTER_ADMIN_TOKEN`. The NetOps configuration at `/home/yvesyuan/.netops2026.json` must contain:

```json
{
  "aiops": {
    "base_url": "http://172.25.60.233:18080",
    "shared_secret": "REPLACE_WITH_SHARED_SECRET",
    "timeout": 150
  }
}
```

Back up and deploy the unified frontend and route module, then restart only the NetOps API service:

```bash
sudo cp -a /var/www/NetAlert/frontend/dist/2026 /var/www/NetAlert/frontend/dist/2026.pre-aiops
sudo rsync -a --delete web/ops-platform/dist/ /var/www/NetAlert/frontend/dist/2026/
cp /home/yvesyuan/PycharmProjects/anbo_wx/backend/app/routes/netops2026.py /home/yvesyuan/PycharmProjects/anbo_wx/backend/app/routes/netops2026.py.pre-aiops
cp backend/ops-platform-api/ops_platform_api.py /home/yvesyuan/PycharmProjects/anbo_wx/backend/app/routes/netops2026.py
# Use `systemctl list-units | grep -E 'anbo|netops|gunicorn'` to identify and restart the existing API unit.
```

## Data plane on 20

Copy `.env.data-plane.example` to `.env.data-plane`, fill secrets, then:

```bash
cd /opt/jscn-aiops/deploy
docker-compose -f docker-compose.20-data-plane.yml config
docker-compose -f docker-compose.20-data-plane.yml up -d --build
```

After health checks pass, stop and remove only the old `aiops-api`, `aiops-scheduler`, `aiops-web` and `aiops-mysql` containers. Keep their MySQL volume untouched for the rollback window.

## Validation and cutover

Run the automated checks first:

```bash
python scripts/preflight_split_deployment.py app --env-file /etc/jscn-aiops/app.env
python scripts/preflight_split_deployment.py data --env-file deploy/.env.data-plane
```

1. Verify clocks differ by less than 5 seconds.
2. Verify API, scheduler, ES cluster, Logstash pipelines, event-worker freshness and QQ service identity.
3. Log in through NetOps as normal user, organization admin and super admin; verify both navigation and BFF denial behavior.
4. Verify an empty organization scope produces zero events and AI evidence, never global data.
5. Create one manual AI run and confirm `scope_org_id`, `scope_regions_json`, identity audit and operation audit records.
6. Keep the old MySQL container stopped but recoverable for seven days. Roll back by restoring the saved NetOps route/config, restarting old AIOps application containers, and leaving ELK untouched.
