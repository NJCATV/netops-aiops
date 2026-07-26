# JSCN AIOps

> 当前模块架构、数据库、端口限制和 Fail2ban/防火墙基线见
> [`docs/module-contract.md`](docs/module-contract.md)。用户统一从 `233:5772` 网管入口访问，20 不作为独立用户入口。

JSCN AIOps ingests Syslog and SNMP Trap data, enriches H3C Trap events with MIB and topology context, aggregates operational signals into `alarm_events`, and exposes a Web management console for realtime review and AI-assisted triage.

## Services

Run the stack from the deployment directory:

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d
```

Core services:

- `elasticsearch`: stores Syslog, Trap, and alarm event time-series indexes.
- `logstash`: receives Syslog and SNMP Trap data and writes parsed documents.
- `kibana`: Elasticsearch inspection UI.
- `mysql`: stores users, task configuration, AI runs, findings, feedback, and MIB mappings.
- `aiops-event-worker`: continuously aggregates parsed Syslog into `alarm_events`.
- `aiops-api`: Flask API for authentication, realtime data, AI analysis, findings, feedback, and scheduled task configuration.
- `aiops-scheduler`: independent worker that executes due AI analysis tasks.
- `aiops-qq-adapter`: optional NapCat/OneBot adapter for using the fault KB assistant in allowlisted QQ groups.
- `aiops-web`: Nginx-hosted Vue UI with `/api` reverse proxy to `aiops-api`.

## Web Console

Default Web port:

```text
生产用户从南京安播智维平台的“系统管理 → AIOps 系统管理 → 旧版入口”进入：

```text
https://172.31.1.233:5772/2026/legacy-aiops/
```

该页面使用网管 JWT，经 `/wx/api/netops2026/aiops/*` BFF 访问 AIOps。AIOps 本地注册、密码登录和 Session 兜底已移除；20 服务器的 5772 只绑定 `127.0.0.1`，不得作为用户入口。
```

The Web console supports login/register, realtime Syslog, Trap, alarm event review, manual AI analysis, AI history and findings, operator feedback, and scheduled AI task configuration.

## Common Checks

```bash
cd /opt/jscn-aiops/deploy
docker-compose ps
docker-compose logs --tail=100 aiops-api
docker-compose logs --tail=100 aiops-event-worker
docker-compose logs --tail=100 aiops-scheduler
curl -s http://127.0.0.1:8080/api/health
curl -s http://127.0.0.1:5772/api/health
curl -s http://127.0.0.1:18088/health
git status
```

QQ group access through NapCat/OneBot is documented in `docs/qq_adapter_napcat.md`.

## Data Boundary

Elasticsearch stores high-volume operational events. MySQL stores application metadata and AI workflow state. The AI Agent receives compact summaries and tool results through controlled Python code; it does not directly access Elasticsearch or MySQL.

Do not commit `.env` or any secret values.
