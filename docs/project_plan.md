# Project Plan

## Short-Term Plan

短期目标是完成第一阶段数据底座和第二阶段 AI 定时分析报告 MVP。

### Phase 1: Data Foundation

目标：让真实 Syslog 和 SNMP Trap 数据稳定进入 Elasticsearch，并能在 Kibana 中按时间、设备和事件类型查询。

关键任务：

1. 检查 JSCN-20 基础环境。
2. 验证 UDP 10087 Syslog 接收。
3. 验证 UDP 10086 SNMP Trap 接收。
4. 部署 Elasticsearch、Kibana、Logstash。
5. 保存完整原始 Syslog 到 raw_message。
6. 初步解析 Syslog 结构化字段。
7. 保存 Trap 原始数据和基础字段。
8. 建立 Kibana 查询和统计验证方法。

验收标准：

1. Syslog 能进入 Elasticsearch。
2. 能看到 raw_message。
3. 能按 device_ip、device_name、event_code 查询。
4. 能统计每天日志总数。
5. 能统计 TOP 设备和 TOP event_code。
6. 文档记录部署过程和问题。

### Phase 2: AI Scheduled Report MVP

目标：基于 Elasticsearch 中的真实告警数据生成过去 24 小时 AI 分析报告。

关键任务：

1. Python Worker 定时查询 Elasticsearch。
2. 输出结构化统计 JSON。
3. 调用 AI 接口生成 Markdown 报告。
4. 将报告保存到 `/data/jscn-aiops/reports/YYYY-MM-DD-aiops-report.md`。
5. 支持手动运行和定时运行。

验收标准：

1. 可以手动运行命令生成报告。
2. 可以通过 cron 或 APScheduler 定时生成报告。
3. 报告内容基于真实 Elasticsearch 数据。
4. 报告文件可追溯保存。

## Medium-Term Plan

中期目标是实时事件聚合与 AI 分析。

1. 实现 10 秒静默聚合。
2. 管理活跃事件生命周期。
3. 同设备、同接口、同事件族日志聚合。
4. 将光模块告警、接口 Down、Vlan-interface Down 聚合为一个事件。
5. PPP 类日志按用户、设备、时间窗口聚合。
6. 事件成型后调用 AI 初判。
7. 恢复日志出现后调用 AI 生成恢复总结。
8. 超时未恢复后调用 AI 升级分析。

## Long-Term Plan

长期目标是形成可迁移、可扩展、可运营的城域网 AIOps 平台。

1. 从 JSCN-20 单机迁移到三台服务器集群。
2. 支持 Elasticsearch、Redis、MySQL 的生产级高可用或备份恢复。
3. 建立规则库、设备清单、事件状态、报告归档和通知通道。
4. 支持实时智能降噪、根因辅助判断和联动处置。
5. 建立完整的运维文档、部署文档、回滚文档和故障处理手册。
