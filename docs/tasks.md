# Tasks

## Execution Rules

1. 每次只完成一个明确任务，完成后停止等待下一步指令。
2. 每个任务完成后必须更新本文档。
3. 每个任务完成后必须 git add、git commit、git push。
4. 不提交真实密码、API Key、SSH 私钥或生产 `.env`。
5. 所有部署命令和验证过程必须记录到文档。
6. Task 1 之前不连接 JSCN-20。

## Task List

| ID | Task | Status | Deliverables | Acceptance |
| --- | --- | --- | --- | --- |
| Task 0 | 初始化项目文档和任务计划 | Done | `agent.md`、`README.md`、`docs/*.md`、`.env.example`、`.gitignore`、基础目录 | 文档完整；Git 仓库初始化；提交并 push |
| Task 1 | JSCN-20 服务器环境检查 | Done | `docs/task1_jscn20_environment_check.md` | 已明确 OS、资源、端口、防火墙、Docker、Git、目录权限 |
| Task 2 | Docker Compose 基础环境 | Done | `deploy/docker-compose.yml`、`deploy/README.md`、`docs/task2_docker_compose_base.md` | JSCN-20 已安装 Docker/docker-compose；目录已创建；Compose 骨架已记录 |
| Task 3 | Elasticsearch + Kibana 部署 | Done | `deploy/docker-compose.yml`、`deploy/.env.example`、`docs/task3_elasticsearch_kibana_deploy.md` | ES API 可访问；Kibana 可访问；数据目录已持久化 |
| Task 4 | Syslog 接入 Elasticsearch | Done | `deploy/logstash/pipeline/syslog.conf`、`deploy/logstash/config/logstash.yml`、`docs/task4_syslog_ingest.md` | UDP 10087 真实 Syslog 已进入 ES；raw_message 完整保存 |
| Task 5 | Trap 接入 Elasticsearch | Done | `deploy/logstash/pipeline/trap.conf`、`docs/task5_trap_ingest.md` | UDP 10086 真实 Trap 已进入 ES；原始内容可查询 |
| Task 6 | Kibana 查询验证 | Done | `scripts/task6_es_24h_summary.py`、`docs/outputs/task6-24h-summary.json`、`docs/outputs/task6-24h-summary.md`、`docs/task6_es_query_validation.md` | 已按时间、设备、event_code、event_family、severity 和 Trap OID/source/enterprise 输出统计 |
| Task 7 | Python 聚合统计 | Pending | Worker 查询 ES、生成统计 JSON | 可手动生成过去 24 小时统计 JSON |
| Task 8 | AI 定时分析报告 MVP | Pending | AI 调用、Markdown 报告、定时运行方式 | 可生成基于真实 ES 数据的 Markdown 报告 |

## Task 0 Completion Notes

完成内容：

1. 创建项目长期约束文档 `agent.md`。
2. 创建项目说明文档 `README.md`。
3. 创建项目计划、架构、部署、数据设计和任务清单文档。
4. 创建 `.env.example`，仅包含配置项示例。
5. 创建 `.gitignore`。
6. 创建基础目录结构占位文件。

未执行内容：

1. 未连接 JSCN-20。
2. 未部署 Elasticsearch、Kibana、Logstash、Redis、MySQL。
3. 未安装 Docker。
4. 未开发 Python Worker。
5. 未编写 Logstash pipeline。

## Next Recommended Task

Task 7：Python 聚合统计。

建议先处理：

1. 将 Task 6 的一次性查询脚本演进为正式 Worker 聚合模块。
2. 输出稳定的过去 24 小时统计 JSON。
3. 加入解析失败数量、小时趋势和典型样例。
4. 为 Task 8 的 AI 报告输入做准备。

## Task 1 Completion Notes

完成内容：

1. 通过 `ssh JSCN-20` 完成只读环境检查。
2. 记录 JSCN-20 OS、内核、CPU、内存、磁盘和网络信息。
3. 确认 UDP `10086` 和 UDP `10087` 当前未被监听程序占用。
4. 确认 Docker 和 Docker Compose 未安装。
5. 确认 Git 实际已安装，版本为 `2.25.1`。
6. 确认 `/opt/jscn-aiops` 和 `/data/jscn-aiops` 尚不存在，创建需要 sudo 权限。
7. 新增 `docs/task1_jscn20_environment_check.md` 作为检查记录。

未执行内容：

1. 未安装 Docker。
2. 未安装或修改 Git。
3. 未创建服务器目录。
4. 未部署 Elasticsearch、Kibana、Logstash、Redis、MySQL。
5. 未编写或运行 Python Worker。

## Task 2 Completion Notes

完成内容：

1. 使用 `aiops` 用户完成 JSCN-20 Docker 基础环境安装。
2. 安装 Docker Engine `26.1.3` 和 `docker-compose` `1.25.0`。
3. 将 `aiops` 加入 docker 组，并验证新会话可管理 Docker network 和 volume。
4. 创建 `/opt/jscn-aiops` 和 `/data/jscn-aiops` 规划目录，并授权给 `aiops:aiops`。
5. 新增 `deploy/docker-compose.yml` 作为 Compose 基础骨架。
6. 新增 `deploy/README.md` 记录 Compose 基础命令和当前边界。
7. 新增 `docs/task2_docker_compose_base.md` 记录安装、验证和风险。

未执行内容：

1. 未部署 Elasticsearch、Kibana、Logstash、Redis、MySQL。
2. 未启动业务容器。
3. 未开发 Python Worker。
4. 未编写 Logstash pipeline。
5. 未修改或提交任何真实密码、API Key 或生产 `.env`。

## Task 3 Completion Notes

完成内容：

1. 使用 Elastic Stack `7.17.27` 部署 Elasticsearch 和 Kibana。
2. 从 `docker.elastic.co` 成功拉取 ES/Kibana 镜像。
3. 更新 `deploy/docker-compose.yml`，加入 `elasticsearch` 和 `kibana` 服务。
4. 新增 `deploy/.env.example`，记录部署变量示例。
5. 在 JSCN-20 设置 `vm.max_map_count=262144`。
6. 将 ES 数据目录持久化到 `/data/jscn-aiops/es`。
7. 验证 Elasticsearch API 可访问，cluster health 为 green。
8. 验证 Kibana `/api/status` 返回 HTTP `200` 且 overall status 为 green。
9. 新增 `docs/task3_elasticsearch_kibana_deploy.md` 记录部署和验证过程。

未执行内容：

1. 未部署 Logstash。
2. 未接入 Syslog UDP `10087`。
3. 未接入 SNMP Trap UDP `10086`。
4. 未创建业务索引模板。
5. 未开发 Python Worker。

## Task 4 Completion Notes

完成内容：

1. 拉取 Logstash `7.17.27` 镜像。
2. 在 Compose 中新增 `logstash` 服务。
3. 新增 `deploy/logstash/config/logstash.yml`。
4. 新增 `deploy/logstash/pipeline/syslog.conf`。
5. Logstash 已监听 UDP `10087`。
6. 真实 Syslog 已写入 `jscn-aiops-syslog-raw-2026.05.17` 和 `jscn-aiops-syslog-parsed-2026.05.17`。
7. 已验证 raw/parsed count 均为 `46`。
8. 已验证 `raw_message` 完整保存。
9. 已验证基础字段解析，包括 `device_name`、`device_ip`、`module`、`severity`、`event_code`、`event_family`。
10. 修复真实 H3C 日志中年份导致 `device_name` 误解析的问题。
11. 调整主机 UDP receive buffer，Logstash 已获得 `16777216` bytes 接收缓冲。
12. 新增 `docs/task4_syslog_ingest.md` 记录部署、验证和风险。

未执行内容：

1. 未接入 SNMP Trap UDP `10086`。
2. 未部署 Redis、MySQL。
3. 未开发 Python Worker。
4. 未做 Kibana Data View 和 dashboard 验证。
5. 未配置 ES Index Template 或 ILM。

## Task 5 Completion Notes

完成内容：

1. 确认 Logstash 镜像已内置 `logstash-input-snmptrap 3.1.0`。
2. 新增 `deploy/logstash/pipeline/trap.conf`。
3. 更新 Compose，为 Logstash 增加 UDP `10086` 映射。
4. 更新环境变量示例，增加 `SNMP_TRAP_UDP_PORT`、`SNMP_TRAP_COMMUNITY`、`ELASTICSEARCH_TRAP_RAW_INDEX_PREFIX`。
5. JSCN-20 已监听 UDP `10086`。
6. Logstash 日志确认 SNMP Trap input 已启动。
7. 真实 Trap 已进入 `jscn-aiops-trap-raw-2026.05.17`。
8. 记录 MIB 库当前不阻塞 Task 5，后续用于增强解析。
9. 用户确认 Trap community 为 `public`，协议不是 SNMPv3，可能为 v1/v2c。
10. 已验证 Trap raw count 为 `51`。
11. 已验证 `raw_message`、来源 IP、varbinds 和基础字段。

未执行内容：

1. 未接入 H3C MIB 完整翻译。
2. 未配置 Trap OID 到 event_family 的规则映射。
3. 未做 Kibana Data View 和 dashboard 验证。

## Task 6 Completion Notes

完成内容：

1. 新增 `scripts/task6_es_24h_summary.py`。
2. 在 JSCN-20 上执行最近 24 小时 ES 查询。
3. 生成 `/data/jscn-aiops/reports/task6/task6-24h-summary.json`。
4. 生成 `/data/jscn-aiops/reports/task6/task6-24h-summary.md`。
5. 将 JSON 和 Markdown 摘要归档到 `docs/outputs/`。
6. Syslog 按 `device_ip`、`device_name`、`event_code`、`event_family`、`severity` 完成 TOP 聚合。
7. Trap 按 `trap_oid`、`source_ip`、`enterprise_oid` 完成 TOP 聚合，未做 MIB 翻译。
8. 新增 `docs/task6_es_query_validation.md` 记录查询方法、输出和数据质量发现。

关键结果：

1. 最近 24 小时 Syslog 总数：`341`。
2. 最近 24 小时 Trap 总数：`55`。
3. Syslog TOP event_code：`PPP_CHASTEN / 155`。
4. Trap TOP source_ip：`172.25.131.3 / 55`。

未执行内容：

1. 未做 AI 报告生成。
2. 未实现定时 Worker。
3. 未做 Trap MIB 翻译。

## Task 7 Completion Notes

Task 7: configurable Syslog parsing rule framework.

Completed:

1. Added `config/event_family_rules.yml` to map `event_code`, `module`, and keywords to `event_family`.
2. Added `config/field_extract_rules.yml` to configure field extraction regexes for PPP, PTP, BFD, OPTICAL, RADIUS, QOS, INTERFACE, device fault, and shell security events.
3. Added `scripts/replay_syslog_rules.py` to query recent Syslog data from Elasticsearch and recompute `event_family`, `extracted_fields`, and `parse_status` without writing back to Elasticsearch.
4. Added `scripts/import_exported_alarm_csv.py` to import exported Syslog and Trap CSV files when Elasticsearch does not contain the full 7-day validation window. The importer uses stable `_id` values and is safe to rerun.
5. Imported the uploaded historical export files on JSCN-20: Syslog `50000`, Trap `5690`, failed `0`.
6. Ran the Task 7 replay on JSCN-20 and generated reports under `/data/jscn-aiops/reports/task7/`.
7. Archived report copies under `reports/task7/`.
8. Updated `docs/data_design.md` and `agent.md` with the parsing-rule contract.

Key results:

1. Seven-day Syslog replay total: `50887`.
2. `parsed`: `49991`.
3. `partial`: `890`.
4. `failed`: `6`.
5. Unknown ratio: `0.01%`.
6. Unknown event_code TOP: `LLDP_NEIGHBOR_AGE_OUT / 5`, `CLK_REF_LOST / 1`.
7. TOP event_family: `ppp_auth / 25335`, `ptp_clock / 20152`, `radius / 1823`, `bfd_flap / 1316`, `qos_congestion / 1314`.

Not implemented:

1. No event aggregation.
2. No AI call.
3. No page or dashboard.

## Task 19 Completion Notes

Task 19: Flask API foundation and user authentication.

Completed:

1. Added a Flask API application factory in `app/__init__.py`.
2. Added authentication blueprint under `app/api/auth.py`.
3. Reused the existing `users` table and Werkzeug password hashing.
4. Added cookie-session login, logout, current-user lookup, and reusable `login_required` / `admin_required` helpers.
5. Added `GET /api/health`, `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me`.
6. Added project `Dockerfile` and `gunicorn`.
7. Added `aiops-api` to `deploy/docker-compose.yml`.
8. Added API-related example env keys to `deploy/.env.example` without real secrets.

Validation on `/opt/jscn-aiops`:

1. `python3 -m py_compile app/__init__.py app/api/auth.py` passed.
2. `docker-compose config --services` includes `aiops-api`.
3. `docker-compose up -d --build aiops-api` started `jscn-aiops-api`.
4. `GET /api/health` returned HTTP `200`.
5. `GET /api/auth/me` returned HTTP `401` before login and after logout.
6. Register and login succeeded for a viewer validation user.
7. Unauthenticated admin self-registration returned HTTP `403`.
8. MySQL password storage was verified as Werkzeug `scrypt` hash, not plaintext.

Current limits:

1. No business data API yet; Task 20 will add runtime/syslog/trap/alarm event endpoints protected by `login_required`.
2. No frontend page yet.
3. The server directory is still not a Git repository; local Git remains the commit source of truth and files are synced to `/opt/jscn-aiops`.
4. No Trap MIB translation.
5. No write-back of replayed `extracted_fields` to Elasticsearch.

## Roadmap After Task 7

| ID | Task | Status | Deliverables | Acceptance |
| --- | --- | --- | --- | --- |
| Task 8 | Event aggregation engine MVP | Pending | Build `alarm_events` from Task 7 `event_family` and `extracted_fields` | Support initial aggregation for `PPP_AUTH_FAILURE`, `PTP_CLOCK_JITTER`, `BFD_FLAP`, `OPTICAL_FAULT`, `INTERFACE_LINK`, and `RADIUS_SERVER_DOWN`; no AI call |
| Task 9 | AI report context construction | Pending | Generate `ai_context.json` from statistics, key event details, and history comparison | Provide structured report context; no AI call |
| Task 10 | AI scheduled report MVP | Pending | Call AI API, generate Markdown daily report, save to `/data/jscn-aiops/reports/` | Report is based on real ES data and Task 9 context; can run manually or by schedule |

## Next Recommended Task

Task 8: event aggregation engine MVP.

## Task 8 Completion Notes

Task 8: offline alarm event aggregation MVP.

Completed:

1. Added `config/event_aggregation_rules.yml` for first-batch event aggregation windows and grouping fields.
2. Added `scripts/generate_alarm_events.py` to read recent Syslog from Elasticsearch, reapply Task 7 parsing in memory when needed, and generate offline alarm events.
3. Generated server outputs under `/data/jscn-aiops/reports/task8/`.
4. Archived outputs under `reports/task8/` and `docs/outputs/task8/`.
5. Updated `docs/data_design.md` with the initial `alarm_events` shape and event types.

Validation result on JSCN-20:

1. ES query window: last 7 days from `jscn-aiops-syslog-parsed-*`.
2. Raw Syslog logs queried: `50995`.
3. Logs matching Task 8 supported event families: `50538`.
4. Unaggregated logs: `457`.
5. Generated alarm events: `29087`.
6. Event types all produced output:
   - `PPP_AUTH_FAILURE`: `25316`
   - `PTP_CLOCK_JITTER`: `1176`
   - `BFD_FLAP`: `302`
   - `OPTICAL_FAULT`: `226`
   - `RADIUS_SERVER_ABNORMAL`: `769`
   - `QOS_CONGESTION`: `1298`

Key compression results:

1. PTP: `20204` logs -> `1176` events, `94.18%` reduction.
2. BFD: `1316` logs -> `302` events, `77.05%` reduction.
3. Optical: `492` logs -> `226` events, `54.07%` reduction.
4. RADIUS: `1823` logs -> `769` events, `57.82%` reduction.
5. PPP: `25387` logs -> `25316` events. Current user-level grouping shows limited compression because usernames are mostly unique within a 5-minute window.

Not implemented:

1. No real-time listener.
2. No Redis active event lifecycle.
3. No AI call.
4. No web page or dashboard.
5. No write-back to Elasticsearch or MySQL.
6. No Logstash pipeline changes.

## Roadmap After Task 8

| ID | Task | Status | Deliverables | Acceptance |
| --- | --- | --- | --- | --- |
| Task 9 | AI report context construction | Pending | Generate `ai_context.json` from event statistics, key event details, and history comparison | Context is based on Task 8 `alarm_events`; no AI call |
| Task 10 | AI scheduled report MVP | Pending | Call AI API, generate Markdown daily report, save to `/data/jscn-aiops/reports/` | Report is based on real ES data and Task 9 context; can run manually or by schedule |

## Next Recommended Task

Task 9: AI report context construction.

## Task 8.1 Completion Notes

Task 8.1: refine alarm event aggregation model.

Completed:

1. Updated `config/event_aggregation_rules.yml` to add `event_mode` and split events into `lifecycle` and `statistical` modes.
2. Changed `PPP_AUTH_FAILURE` from username-level lifecycle-like events to statistical buckets: `device_ip + domain + 5-minute window`.
3. Changed `QOS_CONGESTION` to statistical buckets by `slot + queue_id + 5-minute window`, with top device and queue metrics.
4. Added BFD `session_id` extraction from raw H3C `Sess[...]` messages and used it for BFD aggregation when available.
5. Added `INTERFACE_LINK` lifecycle aggregation.
6. Generated Task 8.1 reports under `reports/task8_1/` and `/data/jscn-aiops/reports/task8_1/`.
7. Updated `docs/data_design.md` with the Task 8.1 event mode model.

Validation result on JSCN-20:

1. Raw Syslog logs queried: `51101`.
2. Logs matching Task 8.1 supported event families: `50796`.
3. Unaggregated logs: `305`.
4. Generated alarm events: `19490`.
5. Event mode counts: `statistical / 17019`, `lifecycle / 2471`.
6. Event type counts:
   - `PPP_AUTH_FAILURE`: `16426`
   - `PTP_CLOCK_JITTER`: `1179`
   - `BFD_FLAP`: `265`
   - `OPTICAL_FAULT`: `226`
   - `RADIUS_SERVER_ABNORMAL`: `769`
   - `QOS_CONGESTION`: `593`
   - `INTERFACE_LINK`: `32`

Comparison with Task 8:

1. Total events: `29087 -> 19490`, delta `-9597`.
2. PPP events: `25316 -> 16426`, delta `-8890`, change `-35.12%`.
3. QoS events: `1298 -> 593`, delta `-705`, change `-54.31%`.
4. BFD events: `302 -> 265`, change `-12.25%`.
5. Optical events: `226 -> 226`, unchanged.
6. PTP events: `1176 -> 1179`, essentially unchanged.
7. Interface link events were newly added: `0 -> 32`.

Not implemented:

1. No AI call.
2. No write-back to Elasticsearch.
3. No MySQL usage.
4. No real-time worker or Redis active lifecycle.
5. No page or dashboard.

## Roadmap After Task 8.1

| ID | Task | Status | Deliverables | Acceptance |
| --- | --- | --- | --- | --- |
| Task 9 | Persist alarm events to Elasticsearch | Pending | `jscn-aiops-alarm-events-*` template and import script | Task 8.1 events can be written idempotently and queried by Kibana |
| Task 10 | Incremental event aggregation Worker | Pending | Checkpoint-based worker | Repeated runs do not duplicate events |
| Task 11 | MySQL app metadata schema | Pending | Flask SQLAlchemy models and initialization | MySQL stores app metadata only |

## Next Recommended Task

Task 9: persist alarm events to Elasticsearch.

## Task 9 Completion Notes

Task 9: persist alarm events to Elasticsearch.

Completed:

1. Added Elasticsearch index template `deploy/elasticsearch/templates/alarm_events_template.json` for `jscn-aiops-alarm-events-*`.
2. Added `scripts/write_alarm_events_to_es.py` to import Task 8.1 event JSON into Elasticsearch.
3. Supported `--dry-run`, template installation, batch bulk upsert, and Markdown import reports.
4. Used `event_id` as Elasticsearch `_id` so repeated imports update existing event documents instead of creating duplicates.
5. Generated import report under `/data/jscn-aiops/reports/task9/` and archived it under `reports/task9/`.
6. Updated `docs/data_design.md` with the alarm event index contract.

Validation result on JSCN-20:

1. Source event file: `reports/task8_1/task8_1_alarm_events.json`.
2. Source event count: `19490`.
3. Dry-run validation: `19490` events accepted, `0` failed.
4. Actual import: `19490` upserted, `0` failed.
5. Repeat import for idempotency check: document count stayed at `19490`.
6. Target index pattern: `jscn-aiops-alarm-events-*`.
7. Top event types after import:
   - `PPP_AUTH_FAILURE`: `16426`
   - `PTP_CLOCK_JITTER`: `1179`
   - `RADIUS_SERVER_ABNORMAL`: `769`
   - `QOS_CONGESTION`: `593`
   - `BFD_FLAP`: `265`
   - `OPTICAL_FAULT`: `226`
   - `INTERFACE_LINK`: `32`

Not implemented:

1. No MySQL usage.
2. No AI call.
3. No real-time worker.
4. No web page or dashboard.

## Next Recommended Task

Task 10: incremental event aggregation Worker.

## Task 10 Completion Notes

Task 10: incremental event aggregation Worker.

Completed:

1. Added `workers/event_aggregation_worker.py`.
2. Worker reads `/data/jscn-aiops/runtime/checkpoints/event_aggregator.json` when present.
3. Worker queries `jscn-aiops-syslog-parsed-*` from the checkpoint timestamp, or from `now - --lookback-minutes` when no checkpoint exists.
4. Worker reuses Task 7 parsing rules and Task 8.1 aggregation rules.
5. Worker writes alarm events to `jscn-aiops-alarm-events-*` with the same idempotent `event_id` upsert behavior from Task 9.
6. Worker supports `--once`, `--lookback-minutes`, and `--dry-run`.
7. Added `docs/task10_event_aggregation_worker.md` with manual, cron, and systemd timer examples.
8. Updated `docs/data_design.md` with the checkpoint schema.

Validation result on JSCN-20:

1. Dry-run with `--once --lookback-minutes 10`: read `73` Syslog documents, generated `30` events, wrote `0`, checkpoint unchanged.
2. Initial write run with `--once --lookback-minutes 10080`: read `51190` Syslog documents, generated `19521` events, upserted `19521`, failed `0`, checkpoint updated.
3. Repeat write run after checkpoint: read only checkpoint-after logs and upserted incremental events without duplicating previous documents.
4. Latest repeat run: read `2` Syslog documents, generated `1` event, upserted `1`, failed `0`.
5. Alarm event index document count after validation: `19530`.
6. Archived worker report under `reports/task10/task10_worker_run_report.md`.

Not implemented:

1. No Redis active event lifecycle.
2. No AI call.
3. No MySQL usage.
4. No web page or dashboard.

## Next Recommended Task

Task 11: MySQL app metadata schema.

## Task 11 Completion Notes

Task 11: MySQL application metadata schema.

Completed:

1. Added a MySQL service to `deploy/docker-compose.yml`.
2. Set the planned MySQL host port to `13306` to avoid conflicts with system MySQL on port `3306`.
3. Set the application MySQL user to `aiops` in example configuration.
4. Added `requirements.txt` with Flask, SQLAlchemy, PyMySQL, python-dotenv, and Werkzeug.
5. Added `app/db.py` for SQLAlchemy engine and session helpers.
6. Added `app/models.py` with `users`, `report_tasks`, `report_records`, `email_send_logs`, `app_settings`, and `audit_logs`.
7. Added `scripts/init_mysql.py` to initialize tables and create the default admin user.
8. Updated `docs/data_design.md` with the ES/MySQL responsibility split and table purposes.

Validation result on JSCN-20:

1. Docker Hub was unreachable from JSCN-20, so runtime `MYSQL_IMAGE` was set to `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/mysql/mysql-server:8.0.32`.
2. MySQL container `jscn-aiops-mysql` is running and healthy.
3. Host port mapping: `0.0.0.0:13306 -> 3306/tcp`.
4. Runtime MySQL settings: user `aiops`, database `jscn_aiops`, host port `13306`.
5. `scripts/init_mysql.py --env-file deploy/.env` completed successfully.
6. Created tables:
   - `users`
   - `report_tasks`
   - `report_records`
   - `email_send_logs`
   - `app_settings`
   - `audit_logs`
7. Default admin user `admin` was created with role `admin`; stored password hash length is `162`.
8. No Syslog, Trap, or alarm event data was moved into MySQL.

Not implemented:

1. No Flask API endpoints.
2. No report task scheduler.
3. No email sending.
4. No login page or permission enforcement.

## Next Recommended Task

Task 12: AI report context builder.

## Task 12 Completion Notes

Task 12: AI report context builder.

Completed:

1. Added `scripts/build_ai_report_context.py`.
2. Script reads Syslog, Trap, and alarm events from Elasticsearch.
3. Script supports `--hours`, `--baseline-days`, and `--top-n`.
4. Script writes AI context JSON to `/data/jscn-aiops/reports/context/YYYYMMDD-HH-ai-context.json`.
5. Script writes a Markdown validation summary to `reports/task12/sample_ai_context.md`.
6. Archived a sample context JSON under `reports/task12/sample_ai_context.json`.
7. Updated `docs/data_design.md` with the AI context schema.

Validation result on JSCN-20:

1. Command: `python3 scripts/build_ai_report_context.py --hours 24 --baseline-days 7 --sample-md reports/task12/sample_ai_context.md`.
2. Output context: `/data/jscn-aiops/reports/context/20260517-08-ai-context.json`.
3. Current 24-hour Syslog total: `10515`.
4. Current 24-hour Trap total: `1062`.
5. Current 24-hour alarm events total: `3456`.
6. Alarm events compressed raw-log count: `10185`.
7. TOP event types:
   - `PPP_AUTH_FAILURE`: `2852`
   - `PTP_CLOCK_JITTER`: `287`
   - `QOS_CONGESTION`: `144`
   - `RADIUS_SERVER_ABNORMAL`: `59`
   - `BFD_FLAP`: `52`
   - `OPTICAL_FAULT`: `52`
   - `INTERFACE_LINK`: `10`
8. Special analysis includes PPP, PTP, BFD, Optical, Radius, QoS, Trap, current-vs-previous, and current-vs-baseline metrics.

Not implemented:

1. No AI call.
2. No MySQL write.
3. No report Markdown generation by AI.
4. No web page or scheduler.

## Next Recommended Task

Task 13: AI report generation MVP.

## Task 12 Topology Enrichment Notes

Enhancement after Task 12:

1. The AI report context builder now reads MySQL `networkDevice` and `networkLinks` when MySQL runtime configuration is available.
2. Device names from alarm event TOP devices are matched against `networkDevice.device_name`.
3. Related links are selected from `networkLinks` when the matched device appears as source or target.
4. The context builder strips literal `\t` suffixes found in imported device names before matching.
5. MySQL enrichment is optional and read-only; the script still runs if MySQL or PyMySQL is unavailable.

Latest JSCN-20 validation:

1. Current 24-hour Syslog total: `10506`.
2. Current 24-hour Trap total: `1085`.
3. Current 24-hour alarm events total: `3376`.
4. Topology inventory devices: `62`.
5. Topology inventory links: `1086`.
6. Matched current event devices: `10`.
7. Related links for matched devices: `228`.

The next task remains Task 13: AI report generation MVP.

## Task 13 Completion Notes

Task 13: AI report generation MVP.

Implemented:

1. Added `scripts/generate_ai_report.py`.
2. Added OpenAI-compatible DeepSeek configuration defaults:
   - `AI_API_BASE_URL=https://api.deepseek.com`
   - `AI_MODEL=deepseek-v4-pro`
   - `AI_REASONING_EFFORT=high`
   - `DEEPSEEK_API_KEY`
3. Added `openai==1.82.0` to `requirements.txt`.
4. Added Elasticsearch template `deploy/elasticsearch/templates/ai_reports_template.json`.
5. Added `docs/task13_ai_report_generation.md`.
6. Updated `docs/data_design.md` with the AI report file, MySQL, and ES persistence contract.

Current JSCN-20 validation:

1. `openai==1.82.0` installed for user `aiops`.
2. `scripts/generate_ai_report.py` passes Python syntax check on JSCN-20.
3. Runtime `deploy/.env` currently has no `DEEPSEEK_API_KEY` or `AI_API_KEY`, so the actual AI call is blocked until the key is provided.
4. The script is designed to write a failed `report_records` entry when a valid context JSON is provided but the AI call/configuration fails.
5. Failure-path validation completed with context `/data/jscn-aiops/reports/context/20260517-09-ai-context.json`.
6. MySQL `report_records.id=1` was written with status `failed` and error `DEEPSEEK_API_KEY or AI_API_KEY is required`.

Pending validation after API key is configured:

1. Generate Markdown report under `/data/jscn-aiops/reports/`.
2. Insert successful metadata into MySQL `report_records`.
3. Index report body into `jscn-aiops-ai-reports-*`.

Success validation after configuring `DEEPSEEK_API_KEY`:

1. Generated report file: `/data/jscn-aiops/reports/2026-05-17-09-aiops-report.md`.
2. Archived report sample: `reports/task13/2026-05-17-09-aiops-report.md`.
3. MySQL `report_records.id=2` status: `success`.
4. MySQL `file_path`: `/data/jscn-aiops/reports/2026-05-17-09-aiops-report.md`.
5. Elasticsearch index: `jscn-aiops-ai-reports-2026.05.17`.
6. Elasticsearch document id: `report-2`.
7. ES `jscn-aiops-ai-reports-*` document count: `1`.
8. Report size: `12220` bytes.

## Task 14 Completion Notes

Task 14: AI context layered refactor with `current_window_summary`.

Completed:

1. Added `aiops/context/current_window_summary.py`.
2. Added reusable `build_current_window_summary()`.
3. Added `scripts/build_current_window_summary.py`.
4. Kept the Task 12 full AI context builder unchanged.
5. Added configurable limits for traps, open incidents, baseline deviations, new anomalies, flapping objects, multi-device correlations, and noise candidates.
6. Limited event evidence to compact samples and avoided emitting full `raw_log_samples`.
7. Added `docs/task14_current_window_summary.md`.
8. Updated `docs/data_design.md` with the Task 14 summary schema.

Validation:

1. `python -m py_compile aiops/context/current_window_summary.py scripts/build_current_window_summary.py` passed.
2. `python scripts/build_current_window_summary.py --help` passed.
3. Requested 7-hour JSCN-20 run generated `outputs/current_window_summary.json`.
4. The 7-hour window had Syslog `2983` and Trap `800`, but `alarm_events` was `0`, indicating the aggregation worker had not produced current event documents for that exact window.
5. Extended 48-hour validation produced alarm event candidates:
   - Alarm events: `4338`
   - Open incidents: `50`
   - Baseline deviations: `22`
   - Flapping objects: `30`
   - Multi-device correlations: `6`
   - Noise candidates: `1`
6. Extended validation confirmed Radius multi-device correlation, BFD/PTP/interface/optical flapping candidates, and stable PPP noise candidates.

Not implemented:

1. No DeepSeek call.
2. No frontend changes.
3. No Agent framework.
4. No database writes.
5. No Syslog/Trap ingestion refactor.

## Pending TODOs After Task 14

1. Trap important candidates in `current_window_summary`:
   - If Trap exists in the current window, aggregate by `trap_oid + source_ip + enterprise_oid`.
   - Do not infer severity directly.
   - Add as `important_trap_candidates` in context.
   - Keep TopN configurable.
   - State in `data_quality` that Trap severity parsing is not implemented.
2. Trap standardized parsing in a later task:
   - OID mapping.
   - Severity mapping.
   - `normalized_event_type`.
   - `object_key` extraction.
   - Correlation with Syslog and `alarm_events`.
   - Eventually turn important Trap into standard `alarm_events` or `incident_candidates`.

## Task 15 Completion Notes

Task 15: AI query/investigation tools MVP.

Completed:

1. Added `aiops/tools/investigation.py`.
2. Added reusable `investigate_candidates()`.
3. Added `scripts/investigate_candidates.py`.
4. Reads Task 14 `current_window_summary` JSON and selects bounded candidates.
5. Returns related current events, historical events, related Trap evidence, baseline snapshots, optional topology context, and optional historical AI memory.
6. Does not expose arbitrary `search_events` to AI and does not implement an unlimited query loop.
7. Added `docs/task15_investigation_tools.md`.
8. Updated `docs/data_design.md` with the investigation context schema.

Validation:

1. Ran on JSCN-20 as `aiops` in `/opt/jscn-aiops`.
2. `python3 -m py_compile aiops/context/current_window_summary.py scripts/build_current_window_summary.py aiops/tools/investigation.py scripts/investigate_candidates.py` passed.
3. `python3 scripts/investigate_candidates.py --help` passed.
4. Generated a 48-hour current-window summary under `/data/jscn-aiops/reports/task15/`.
5. Generated a 5-candidate investigation context under `/data/jscn-aiops/reports/task15/`.
6. Validation output included 5 investigations with related current events and historical events for matching candidates.

Not implemented:

1. No DeepSeek call.
2. No Agent framework.
3. No frontend changes.
4. No database writes.
5. No Trap normalization.

## Task 15 Follow-up Completion Notes

Task 15 follow-up: expose investigation tools for AI Agent.

Completed:

1. Added `aiops/tools/ai_tools.py`.
2. Added controlled `AI_TOOLS` registry.
3. Added OpenAI/DeepSeek-compatible `get_tool_schemas()`.
4. Added `execute_ai_tool(tool_name, arguments)` with structured error returns.
5. Added bounded tools: `investigate_candidates`, `get_related_events`, `get_device_history`, `get_object_history`, `get_topology_context`, and `get_baseline`.
6. Kept `scripts/investigate_candidates.py` as the offline debug script.
7. Updated Task 15 docs to clarify offline package generation and Task 16 Agent tool usage.

Validation:

1. Ran on JSCN-20 as `aiops` in `/opt/jscn-aiops`.
2. `python3 -m py_compile aiops/tools/ai_tools.py aiops/tools/investigation.py scripts/investigate_candidates.py` passed.
3. `get_tool_schemas()` returned 6 tools.
4. `execute_ai_tool("investigate_candidates", args)` returned `ok=true`.
5. `execute_ai_tool("unknown_tool", {})` returned structured `unknown_tool` error.
6. Tool output check confirmed no `raw_log_samples` string in returned JSON.

Not implemented:

1. No DeepSeek call.
2. No frontend changes.
3. No free ES DSL or SQL tools.

## Task 16 Completion Notes

Task 16: lightweight Agent call flow.

Completed:

1. Added `aiops/agent/light_agent.py`.
2. Added `scripts/run_light_agent.py`.
3. Implemented `run_light_agent()` for current-window summary, controlled AI tools, max tool-call loop, and final structured JSON.
4. Reused OpenAI-compatible DeepSeek runtime configuration from `.env`.
5. Supported standard `tool_calls` and pseudo tool-call JSON fallback.
6. Added JSON parsing, code-block extraction, one repair prompt, and raw debug save on failure.
7. Enforced bounded tool execution through Task 15 `execute_ai_tool()`.
8. Added `docs/task16_light_agent.md`.
9. Updated `docs/data_design.md` with the Agent result JSON structure and Task 17 persistence direction.

Validation:

1. Ran on JSCN-20 as `aiops` in `/opt/jscn-aiops`.
2. `python3 -m py_compile aiops/agent/light_agent.py scripts/run_light_agent.py aiops/tools/ai_tools.py` passed.
3. `python3 scripts/run_light_agent.py --help` passed.
4. DeepSeek runtime validation completed with `/data/jscn-aiops/reports/task16/current_window_summary.json`.
5. The Agent called `investigate_candidates` through the Task 15 tool layer.
6. Final output `/data/jscn-aiops/reports/task16/ai_agent_result.json` was valid JSON, not Markdown.
7. Required arrays were present: `must_handle`, `watch`, `noise`, `recovered`, `insufficient`, `correlations`, and `next_actions`.
8. `--max-tool-rounds 1` validation executed only 1 tool call and still produced valid JSON.

Not implemented:

1. No frontend page.
2. No scheduler or email.
3. No user login or permissions.
4. No database writes for AI findings.
5. No Dify, LangGraph, CrewAI, AutoGen, MCP, or multi-Agent framework.
6. Old Markdown report script remains unchanged.

## Next Recommended Task

Task 17: AI findings, memory, and human feedback.


## Task 16 Runtime Analysis Follow-up Notes

Follow-up: real Agent runtime pressure test and behavior analysis.

Completed:

1. Added Agent runtime metrics to `aiops/agent/light_agent.py`.
2. Added per-run trajectory saving under `debug/agent_runs/<run_id>/`.
3. Updated `scripts/run_light_agent.py` to write `runtime_metrics.json` next to the Agent output.
4. Ran real DeepSeek tests for 48-hour summary with `--max-tool-rounds 2` and `--max-tool-rounds 4`.
5. Added `docs/task16_runtime_analysis.md`.

Validation results:

1. Round 2 output: `/data/jscn-aiops/reports/task16/runtime_test_round2/`.
2. Round 4 output: `/data/jscn-aiops/reports/task16/runtime_test_round4/`.
3. Round 2: `193172` total tokens, `475979 ms`, `2` tool calls.
4. Round 4: `89207` total tokens, `251561 ms`, `1` tool call.
5. Both runs produced valid structured JSON and saved full trajectory files.
6. The most valuable tool was `investigate_candidates`; extra follow-up tool calls did not clearly improve result quality.

Recommendation:

Use `max-tool-rounds=2` for MVP/demo by default, and continue compressing `current_window_summary` and `investigate_candidates` output before productionization.

## Task 16.2 Completion Notes

Task 16.2: H3C MIB OID translation for Trap ingestion and backend fallback.

Completed:

1. Added MySQL `mib_oid_mappings` model.
2. Added `scripts/import_mib_oid_map.py`.
3. Added `scripts/export_logstash_mib_dictionary.py`.
4. Added backend lookup/enrichment modules under `aiops/mib/`.
5. Updated Logstash Trap pipeline to translate `trap_oid` into `trap_oid_name`, `trap_oid_module`, and `trap_oid_type`.
6. Mounted `/data/jscn-aiops/logstash/mib` into the Logstash container.
7. Updated `current_window_summary` and `investigate_candidates` to include compact MIB translation fields.
8. Added `docs/task16_2_h3c_mib_translation.md`.

Validation:

1. Imported `43515` MIB OID mappings into MySQL, including `2338` `NOTIFICATION-TYPE` rows.
2. Exported Logstash dictionaries with `2338` entries.
3. Recreated Logstash container so the dictionary mount was active.
4. Verified new Trap documents include `trap_oid_name`, `trap_oid_module`, `mib_translated=true`, and `mib_lookup_source=logstash_dictionary`.
5. Regenerated 48-hour `current_window_summary`; MIB lookup was available and translated Trap names appeared in `important_traps`.
6. Ran light Agent against the Task 16.2 summary; output used readable Trap names such as `hh3cCfgFileChange`, `hh3cRadiusAccServerUpTrap`, `hh3cEntityExtSFPPhony`, and `hh3cEntityExtOpticalWarningClear`.

Not implemented:

1. No full MIB compiler.
2. No severity inference from MIB names.
3. No full Trap normalization into standard alarm events.
4. No frontend changes.
5. No Dify, LangGraph, MCP, or multi-Agent framework.

## Task 17 Completion Notes

Task 17: AI findings, memory, and human feedback persistence.

Completed:

1. Added MySQL models for `ai_analysis_runs`, `ai_findings`, and `ai_finding_feedback`.
2. Added `aiops/agent/persistence.py` for saving Agent runs, splitting findings, writing feedback, and building compact AI memory.
3. Updated `scripts/run_light_agent.py` with optional `--save-to-db` persistence while preserving JSON-only mode.
4. Added `scripts/add_ai_finding_feedback.py` for operator feedback testing.
5. Added `scripts/list_ai_findings.py` for run/finding/feedback validation.
6. Updated `investigate_candidates` to prefer compact historical memory from `ai_findings` and `ai_finding_feedback`.
7. Added `docs/task17_ai_findings_memory_feedback.md`.
8. Updated `docs/data_design.md` with Task 17 table and memory design.

Validation:

1. Ran on JSCN-20 as `aiops` in `/opt/jscn-aiops`.
2. `python3 -m py_compile app/models.py aiops/agent/persistence.py scripts/run_light_agent.py scripts/add_ai_finding_feedback.py scripts/list_ai_findings.py aiops/tools/investigation.py` passed.
3. `python3 scripts/init_mysql.py --env-file deploy/.env` created the new tables.
4. Ran `run_light_agent.py --save-to-db` using the Task 16.2 summary and saved one Agent run.
5. Saved run result: `ai_run_id=1`, `saved_finding_count=26`, `saved_to_db=true`.
6. Added `confirmed` feedback to finding `1`; lifecycle status changed to `active`.
7. Re-ran `investigate_candidates`; CN-16K-M-B candidates returned compact `ai_memory` records with the confirmed feedback.

Not implemented:

1. No frontend feedback page.
2. No login or permissions.
3. No scheduler or email.
4. No automatic dispatch.
5. No AI direct MySQL/ES access.
6. No Dify, LangGraph, MCP, CrewAI, or multi-Agent framework.

## Task 16.4 Completion Notes

Task 16.4: add alarm event aggregation worker to Docker Compose runtime.

Completed:

1. Added `scripts/run_event_aggregation_worker.py` as a fixed-lookback micro-batch runner.
2. Added `scripts/check_alarm_event_freshness.py`.
3. Added `aiops-event-worker` to `deploy/docker-compose.yml`.
4. Added worker environment examples to `deploy/.env.example`.
5. Made `event_id` and `fingerprint` stable from `event_type + aggregation_key`, with ES `_id = event_id`.
6. Added `docs/task16_4_alarm_event_worker.md`.

Validation:

1. `python -m py_compile workers/event_aggregation_worker.py scripts/run_event_aggregation_worker.py scripts/check_alarm_event_freshness.py` passed.
2. On JSCN-20, dry-run over the latest 3 hours scanned `1534` Syslog documents and generated `529` candidate alarm events.
3. One-time 24-hour backfill generated `4173` events and upserted `4173` documents with zero errors.
4. Freshness recovered to `0.18` minutes lag; 24h counts were `syslog=11788`, `trap=290`, `alarm_events=4171`.
5. `docker-compose up -d aiops-event-worker` started `jscn-aiops-event-worker`; first worker round wrote `97` events with zero errors.
6. Rebuilt 24-hour `current_window_summary`; `alarm_event_total=4171`.
7. Re-ran light Agent; output was `ok=true`, `tool_call_count=2`, `must_handle_count=2`, and included alarm event plus Trap evidence.

Not implemented:

1. No Flask page.
2. No unified scheduler table.
3. No email.
4. No login.
5. No Dify, MCP, or LangGraph integration.

## Task 20 Completion Notes

Task 20: realtime data query APIs.

Completed:

1. Added login-protected runtime API routes under `app/api/runtime.py`.
2. Registered the runtime blueprint in the Flask app factory.
3. Added `/api/runtime/overview` with 1h, 3h, and requested-window counts plus latest Syslog and alarm event timestamps.
4. Added `/api/runtime/freshness` to report alarm event lag and freshness state.
5. Added latest Syslog, Trap, and alarm event query APIs with bounded limits and basic filters.
6. Trap query responses enrich raw Trap records with managed object, endpoint, MIB, and topology match fields for direct Web rendering.

Validation:

1. `python -m py_compile app/__init__.py app/api/auth.py app/api/runtime.py` passed locally.
2. On JSCN-20, `python3 -m py_compile app/__init__.py app/api/runtime.py` passed.
3. Restarted `aiops-api`; unauthenticated `/api/runtime/overview` returned `401`.
4. Authenticated `/api/runtime/overview?hours=24` returned Syslog, Trap, and alarm event counts for 1h, 3h, and 24h.
5. `/api/runtime/freshness` returned `is_fresh=true` with alarm lag under 5 minutes at validation time.
6. `/api/syslog/latest`, `/api/trap/latest`, `/api/alarm-events`, and `/api/alarm-events/latest` returned compact records suitable for Vue tables.
7. Validated filtered alarm event query with `event_type=PTP_CLOCK_JITTER`.

Not implemented:

1. No frontend pages.
2. No AI analysis API.
3. No scheduler API.
4. No direct AI access to ES or MySQL.

## Task 21 Completion Notes

Task 21: AI analysis APIs.

Completed:

1. Added `app/api/ai.py` with login-protected AI run, finding, and feedback APIs.
2. Added admin-only `POST /api/ai-runs` for manual AI analysis.
3. Manual runs create an `ai_analysis_runs` row in `running` state, then execute `build_current_window_summary -> run_light_agent -> save_agent_result` in a background thread.
4. Added run listing/detail APIs that expose compact Agent output for Web rendering.
5. Added finding list/detail APIs and per-run finding lookup.
6. Added admin-only feedback API reusing Task 17 persistence.
7. Extended `save_agent_result` to update an existing running run when called by the API.

Validation:

1. `python -m py_compile app/__init__.py app/api/ai.py aiops/agent/persistence.py` passed locally.
2. On JSCN-20, `python3 -m py_compile app/__init__.py app/api/ai.py aiops/agent/persistence.py` passed.
3. Restarted `aiops-api`.
4. Viewer can list AI runs but receives `403` on `POST /api/ai-runs`.
5. Admin triggered a 1-hour validation run with `max_tool_rounds=0`; API returned `202` and the run changed from `running` to `success`.
6. Validation run `1f37d88b-898e-4341-acb7-c75470788f1d` saved `15` findings and reported `18285` total tokens.
7. `/api/ai-runs/<run_uid>/findings`, `/api/findings`, and `/api/findings/<id>` returned expected records.
8. Viewer feedback write returned `403`; admin feedback write returned `201`.

Operational notes:

1. Created validation user `task21_admin` with `admin` role because the existing `admin` password was not available.
2. One failed validation run was marked `failed` after fixing an API container env-file issue.

Not implemented:

1. No scheduler worker.
2. No frontend pages.
3. No direct AI access to ES or MySQL.

## Task 22 Completion Notes

Task 22: scheduled AI analysis task API and scheduler worker.

Completed:

1. Added `aiops/scheduler/ai_scheduler.py` for scheduled AI task execution.
2. Added `scripts/run_ai_scheduler.py` as the independent scheduler worker entrypoint.
3. Added report task CRUD APIs under `/api/report-tasks`.
4. Added enable, disable, and run-now APIs.
5. Reused existing `report_tasks` columns and stored extended scheduler fields in `settings` JSON for compatibility.
6. Added `aiops-scheduler` to `deploy/docker-compose.yml`.
7. Moved the Gunicorn WSGI entrypoint to `app/wsgi.py` so non-Flask scripts can import `app.db` without creating the Flask API app.

Validation:

1. `python -m py_compile app/__init__.py app/wsgi.py app/api/report_tasks.py aiops/scheduler/ai_scheduler.py scripts/run_ai_scheduler.py` passed locally.
2. On JSCN-20, the same py_compile check passed.
3. `docker-compose config --services` includes `aiops-scheduler`.
4. Viewer receives `403` on report task creation.
5. Admin created a validation task, listed it, read details, enabled it, disabled it, and triggered `run-now`.
6. `run-now` created AI run `65b82135-a774-418f-b5fa-69acc6979a20`, completed with `success`, and saved the run to `ai_analysis_runs`.
7. `docker-compose up -d --build aiops-api aiops-scheduler` started both services.
8. `aiops-scheduler` logs show the scheduler loop started with `poll_seconds=60`.
9. `/api/health` returned `200` after switching Gunicorn to `app.wsgi:app`.

Operational notes:

1. The validation report task remains in MySQL and is disabled.
2. Cron expressions are accepted and stored, while the current worker uses interval or daily scheduling behavior for next-run calculation.
3. Scheduler jobs run outside Flask/Gunicorn in the `aiops-scheduler` service.

Not implemented:

1. No Web UI.
2. No email sending from scheduler.
3. No dedicated scheduler run history table beyond `ai_analysis_runs` and `report_tasks.settings`.

## Task 23 Completion Notes

Task 23: Vue and Nginx Web UI MVP.

Completed:

1. Added `frontend/` with Vue 3, Vite, and a production build under `frontend/dist`.
2. Added Nginx config to serve the Vue build and reverse proxy `/api` to `aiops-api:8080`.
3. Added `aiops-web` to `deploy/docker-compose.yml`.
4. Added login, register, logout, and session-aware navigation.
5. Added System Overview, Syslog, Trap, alarm_events, AI Analysis, AI History, and Scheduled Task pages.
6. Added viewer/admin UI affordances: viewers can read, while admin-only actions are disabled in the UI and protected by the API.
7. Trap page explicitly separates `trap_sender_ip` from managed device and managed object fields.

Validation:

1. `npm install` and `npm run build` passed in `frontend/`.
2. `docker-compose config --services` includes `aiops-web`.
3. `docker-compose up -d aiops-web` started `jscn-aiops-web` on port `5772`.
4. Nginx returned `200` for `/`.
5. Nginx reverse proxy returned API health JSON for `/api/health`.
6. Browser verification opened `http://172.25.60.20:5772/`, logged in as the Task 19 viewer, loaded System Overview metrics, and opened the Trap page.
7. Trap table rendered `Trap Sender`, managed object, matched link, MIB, and raw message columns.

Operational notes:

1. The server mirror has `nginx:alpine`, but not `nginx:1.25-alpine`; Compose defaults to the available mirror tag.
2. `frontend/dist` is committed so the Nginx service can start without a Node build step on the server.

Not implemented:

1. No advanced front-end design polish.
2. No frontend-side route library.
3. No charting package.

## Task 24 Completion Notes

Task 24: deployment and demo documentation.

Completed:

1. Added `README.md` with service overview, startup, common checks, and data boundary notes.
2. Added `docs/demo_guide.md` with the Syslog / Trap -> MIB -> alarm_events -> Web -> AI -> feedback -> scheduler demo flow.
3. Added `docs/operation_guide.md` with startup, health checks, freshness, manual AI analysis, scheduled task, and Git hygiene notes.
4. Added `docs/troubleshooting.md` with checks for Web, API, alarm_events lag, Trap sender identity, AI run status, scheduler, and MIB translation.

Validation:

1. Documentation contains no secrets.
2. Documentation references current Compose services: Elasticsearch, Logstash, Kibana, MySQL, aiops-api, aiops-web, aiops-event-worker, and aiops-scheduler.
3. Documentation describes one-command startup from `/opt/jscn-aiops/deploy`.

Not implemented:

1. No new runtime feature changes.
2. No frontend changes.

## Task 25 Completion Notes

Task 25: Trap alarm definition enrichment.

Completed:

1. Added MySQL `trap_alarm_definitions` and `trap_alarm_oid_aliases`.
2. Added `scripts/import_trap_alarm_definitions.py` for private NMS/vendor alarm definition exports.
3. Added `scripts/export_logstash_trap_alarm_dictionary.py` and Logstash alarm translate fields.
4. Added backend alarm definition lookup and Trap enrichment fallback.
5. Added `scripts/backfill_trap_enrichment.py` for idempotent historical Trap enrichment.
6. Updated summary, investigation, and light Agent prompt logic to treat Trap as critical/important evidence without using relay IP as device identity.
7. Added `docs/task16_6_trap_alarm_definition_enrichment.md` and updated data-design/readiness docs.

Validation:

1. Imported `8928` alarm definitions and `26689` unique OID aliases.
2. Vendor distribution: `unknown=5476`, `h3c=2285`, `huawei=1167`.
3. Exported `26689` Logstash alarm dictionary entries.
4. Logstash pipeline restarted and is running.
5. Historical 7d backfill scanned `7055`, updated `7055`, and finished with `0` bulk error items after raising recent Trap index field limit to `2000`.
6. Recent 7d `device_ip=172.25.131.3` count is `0`; invalid `snmp_agent_addr` count is `0`.
7. 24h summary reports `trap_alarm_definition_matched_count=316`, `trap_alarm_definition_unmatched_count=18`, and `trap_sender_as_device_ip_count=0`.
8. `investigate_candidates` Top40 included `30` Trap candidates with related evidence.
9. `run_light_agent.py --max-tool-rounds 2` returned valid JSON and did not treat `172.25.131.3` as a faulty device.

Operational notes:

1. The imported file is not a standard MIB. It is a private alarm definition library containing alarm names, severity, lifecycle, reason, and suggestion.
2. AI context uses truncated fault reason and suggestion text.
3. The 24h Agent run still consumed `308725` tokens, so a smaller frontend/API summary profile is still recommended.

Not implemented:

1. No frontend changes.
2. No unified scheduler changes.
3. No direct AI access to ES/MySQL.
