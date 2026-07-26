# JSCN AIOps（`netops-aiops`）

本仓库承载 20 上的 AIOps 数据面：Syslog/SNMP Trap 接入、事件聚合、MIB 与拓扑富化、AI 分析、知识库、调度和 ELK。用户不直接访问 20，而是统一从 233 的网管入口访问；模块架构、数据库、端口边界和端口守卫见 [`docs/module-contract.md`](docs/module-contract.md)。

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

## 用户入口与安全边界

- 用户入口：浏览器仅通过 `https://anbo.njcatv.net:5772/` 的平台菜单和 `/api/netops2026/aiops/*` BFF 调用访问 AIOps。
- 20 的 `5772` 仅绑定 `127.0.0.1`，只用于本机健康检查与回滚；不能作为用户入口。
- `18080`（BFF API）和 `18190`（基础设施探针）仅允许 233 与本机；`13306`（MySQL）和 `5601`（Kibana）仅允许本机及 `172.31.0.0/16`；`9200`（Elasticsearch）仅允许本机与 Docker bridge。
- 端口收敛由 `netops-aiops-port-guard.service` 的 `INPUT` 与 Docker `DOCKER-USER` 规则共同执行，UFW 未启用不表示服务裸露。

Web 控制台支持实时 Syslog、Trap、告警事件、人工 AI 分析、历史报告、操作反馈和计划任务；本地注册、密码登录和 Session 兜底不作为生产入口。

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
