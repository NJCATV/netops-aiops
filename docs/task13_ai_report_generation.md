# Task 13 AI Report Generation MVP

Task 13 generates a Markdown AIOps report from the Task 12 `ai_context.json`.

## Scope

Implemented:

- Read Task 12 AI context JSON.
- Call an OpenAI-compatible AI endpoint.
- Default model: `deepseek-v4-pro`.
- Save Markdown report under `/data/jscn-aiops/reports/`.
- Write report metadata to MySQL `report_records`.
- Write report body to Elasticsearch `jscn-aiops-ai-reports-*`.
- Mark MySQL report status as `failed` when AI or persistence fails.

Not implemented:

- Scheduler.
- Email sending.
- Web UI.
- User-triggered API endpoint.

## Runtime Configuration

Set real secrets in runtime `.env` only:

```bash
AI_API_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-pro
AI_REQUEST_TIMEOUT_SECONDS=120
AI_REASONING_EFFORT=high
DEEPSEEK_API_KEY=<runtime-api-key>
```

`AI_API_KEY` can also be used as a fallback, but `DEEPSEEK_API_KEY` is preferred for this deployment.

## Install Dependency

```bash
cd /opt/jscn-aiops
python3 -m pip install --user -r requirements.txt
```

## Generate Report

```bash
cd /opt/jscn-aiops
python3 scripts/generate_ai_report.py \
  --env-file deploy/.env \
  --context-json /data/jscn-aiops/reports/context/YYYYMMDD-HH-ai-context.json
```

Output example:

```bash
/data/jscn-aiops/reports/YYYY-MM-DD-HH-aiops-report.md
```

If `DEEPSEEK_API_KEY` or `AI_API_KEY` is missing, the script exits with failure and writes a failed `report_records` entry when a valid context JSON is provided.

Current JSCN-20 validation confirmed this behavior:

- Context: `/data/jscn-aiops/reports/context/20260517-09-ai-context.json`
- MySQL record: `report_records.id=1`
- Status: `failed`
- Error: `DEEPSEEK_API_KEY or AI_API_KEY is required`

After configuring `DEEPSEEK_API_KEY`, JSCN-20 success validation completed:

- Context: `/data/jscn-aiops/reports/context/20260517-09-ai-context.json`
- Report file: `/data/jscn-aiops/reports/2026-05-17-09-aiops-report.md`
- Archived sample: `reports/task13/2026-05-17-09-aiops-report.md`
- MySQL record: `report_records.id=2`
- MySQL status: `success`
- Elasticsearch index: `jscn-aiops-ai-reports-2026.05.17`
- Elasticsearch document: `report-2`
- Report size: `12220` bytes

## Persistence

MySQL:

- Table: `report_records`
- Records status, report path, ES index/document id, error message, and summary.

Elasticsearch:

- Index pattern: `jscn-aiops-ai-reports-*`
- Template: `deploy/elasticsearch/templates/ai_reports_template.json`

## Prompt Contract

The report prompt requires Chinese Markdown output with:

- Overall operating status.
- Current window vs historical baseline.
- High-frequency abnormal devices.
- Device/link impact using `topology_context` when available.
- PPP, PTP, BFD, Optical, Radius, QoS, and Trap analysis.
- Possible causes.
- Recommended actions.
- Follow-up items.
