# Task 11 MySQL Application Metadata Initialization

Task 11 introduces MySQL for small application management data only. Elasticsearch remains responsible for Syslog, Trap, alarm events, AI contexts, and AI report documents.

## Runtime Settings

The runtime `.env` on JSCN-20 should contain real secrets and must not be committed:

```bash
MYSQL_PORT=13306
MYSQL_IMAGE=mysql:8.0
MYSQL_DATABASE=jscn_aiops
MYSQL_USER=aiops
MYSQL_PASSWORD=<runtime-password>
MYSQL_ROOT_PASSWORD=<runtime-root-password>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<runtime-admin-password>
```

The MySQL container listens on `3306` internally and is mapped to host port `13306`.

If Docker Hub is unreachable from JSCN-20, set `MYSQL_IMAGE` to an accessible registry mirror in the runtime `.env`.

## Start MySQL

```bash
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d mysql
docker-compose ps mysql
```

## Initialize Tables

Install Python dependencies if needed:

```bash
cd /opt/jscn-aiops
python3 -m pip install -r requirements.txt
```

Initialize schema and the default admin user:

```bash
cd /opt/jscn-aiops
python3 scripts/init_mysql.py --env-file deploy/.env
```

## Tables

- `users`
- `report_tasks`
- `report_records`
- `email_send_logs`
- `app_settings`
- `audit_logs`

## Scope Boundary

MySQL stores only app metadata. Do not copy raw Syslog, Trap, or high-volume alarm event documents into MySQL.
