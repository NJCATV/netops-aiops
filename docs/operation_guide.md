# Operation Guide

## One Command Startup

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d
```

## Service Checks

```bash
docker-compose ps
docker-compose logs --tail=100 logstash
docker-compose logs --tail=100 aiops-event-worker
docker-compose logs --tail=100 aiops-api
docker-compose logs --tail=100 aiops-scheduler
docker-compose logs --tail=100 aiops-web
```

## Health Checks

```bash
curl -s http://127.0.0.1:8080/api/health
curl -s http://127.0.0.1:5772/api/health
```

## Freshness

After login, use:

```text
GET /api/runtime/freshness
GET /api/runtime/overview?hours=24
```

The Web System Overview also shows freshness and latest AI status.

## Manual AI Analysis

Use the Web AI Analysis page or:

```text
POST /api/ai-runs
```

Recommended default:

```json
{
  "hours": 24,
  "max_tool_rounds": 2,
  "save_to_db": true
}
```

## Scheduled AI Tasks

Scheduled tasks are configured through `/api/report-tasks` or the Web Scheduled Tasks page. The independent `aiops-scheduler` container polls enabled tasks and writes results to `ai_analysis_runs` and `ai_findings`.

## Git Hygiene

Before deployment handoff:

```bash
git status
git log --oneline -5
```

Keep runtime files, `.env`, generated reports, debug output, and Python caches out of commits.
