# AIOps Project Agent Guide

## Project Name

城域网 AIOps 告警数据底座与 AI 定时分析系统

## Long-Term Goal

建设面向城域网 Syslog 和 SNMP Trap 告警数据的 AIOps 数据底座，支撑原始告警留存、结构化解析、聚合统计、AI 定时分析报告，以及后续实时事件聚合、智能降噪和联动处置。

## Current Stage

Task 0：初始化项目文档和任务计划。

当前阶段只完成文档、仓库和目录初始化，不部署 ELK，不连接 JSCN-20，不安装 Docker，不开发 Python Worker，不编写 Logstash pipeline。

## Short-Term Goals

1. 完成 JSCN-20 服务器环境检查。
2. 确认 UDP 10087 可以接收 Syslog。
3. 确认 UDP 10086 可以接收 SNMP Trap。
4. 使用 Docker Compose 部署 Elasticsearch、Kibana、Logstash。
5. 接入 Syslog 并完整保存 raw_message。
6. 对 Syslog 做初步结构化解析。
7. 对 Trap 做原始留存和基础字段提取。
8. 完成 Kibana 查询和统计验证。
9. 实现 Python Worker 定时聚合统计和 AI Markdown 报告 MVP。

## Medium-Term Goals

1. 实现 10 秒静默聚合。
2. 建立活跃事件生命周期管理。
3. 按设备、接口、事件族聚合日志。
4. 形成事件后调用 AI 进行初判。
5. 恢复日志出现后生成恢复总结。
6. 超时未恢复时生成升级分析。

## Long-Term Goals

1. 支持从 JSCN-20 临时单机迁移到三台服务器集群。
2. 支持实时事件聚合、实时 AI 分析、智能降噪和联动处置。
3. 建立可回滚、可迁移、可重跑的生产化部署体系。
4. 沉淀设备清单、规则库、事件状态和报告归档。

## Technical Route

初期采用 JSCN-20 单机部署，优先使用 Docker Compose 组织 Elasticsearch、Kibana、Logstash、Redis、MySQL 和 Python Worker。后续迁移到三机集群时，保持配置、数据目录、环境变量和服务拆分方式可迁移。

临时单机架构：

```text
JSCN-20
├── Logstash / rsyslog：接收 Syslog UDP 10087
├── snmptrapd / Logstash：接收 Trap UDP 10086
├── Elasticsearch：保存原始日志和结构化字段
├── Kibana：查询和可视化
├── Python Worker：定时聚合、AI 报告生成
├── Redis：后续用于实时活跃事件状态
├── MySQL：保存报告、规则、设备清单、事件状态
└── AI 服务配置：通过环境变量配置模型接口
```

## Development Principles

1. 每次只完成一个明确任务，完成后停止等待下一步指令。
2. 后续任务开始前必须先阅读本文件。
3. 服务器驻场开发模式：实际代码、部署、调试应直接在 JSCN-20 上完成。
4. Task 0 不连接服务器，后续从 Task 1 开始再通过 SSH 检查 JSCN-20。
5. 每完成一个 Task，必须更新 `docs/tasks.md`、提交 Git 并 push。
6. 不提交真实密码、API Key、SSH 私钥或生产 `.env`。
7. 示例配置和实际运行配置必须区分。
8. 程序负责采集、解析、聚合、统计、关联；AI 负责总结、解释、判断、建议。
9. AI 不直接承担底层日志解析，不对每条原始日志逐条调用 AI。
10. 实时 AI 分析必须基于事件聚合后再调用。
11. 目录、端口、环境变量和数据路径必须考虑后续三机集群迁移。
12. 优先保证可迁移、可重跑、可回滚。

## Safety Notes

1. 不自动执行危险操作。
2. 对服务器执行操作前先做环境检查。
3. 不删除用户已有文件。
4. 所有部署命令必须记录到文档。
5. 所有监听、日志接收、ES 写入和 AI 报告生成都必须基于真实 Syslog 和 Trap 数据验证。

## Task 7 Parsing Rule Framework

Syslog parsing is now rule-configurable. Future tasks must read these files before changing event classification or field extraction:

- `config/event_family_rules.yml`
- `config/field_extract_rules.yml`

Rules are validated with `scripts/replay_syslog_rules.py`. The replay is read-only for Elasticsearch and writes reports under `reports/task7/` or the configured output directory. Unknown event discovery is part of the workflow: events that do not match configured families remain `unknown` and must be reviewed before expanding rules.

Historical CSV exports can be imported with `scripts/import_exported_alarm_csv.py` when Elasticsearch does not contain the full validation window. The importer uses stable document IDs so repeated imports are idempotent.
