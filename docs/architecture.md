# Architecture

## Overview

本项目围绕城域网设备上报的 Syslog 和 SNMP Trap 构建告警数据底座。系统先完成原始数据接入、留存、结构化解析和聚合统计，再基于聚合结果调用 AI 生成分析报告。

核心边界：

1. 程序负责采集、解析、聚合、统计、关联。
2. AI 负责总结、解释、判断、建议。
3. AI 不直接承担底层日志解析。
4. 不对每条原始日志逐条调用 AI。
5. 后续实时 AI 分析必须基于事件聚合结果。

## Initial Single-Node Architecture

```text
Network Devices
├── Syslog UDP 10087
└── SNMP Trap UDP 10086
        |
        v
JSCN-20
├── Logstash / rsyslog
│   ├── Receive Syslog
│   ├── Receive or normalize Trap input
│   └── Parse and route events
├── Elasticsearch
│   ├── jscn-aiops-syslog-raw-YYYY.MM.DD
│   ├── jscn-aiops-trap-raw-YYYY.MM.DD
│   └── jscn-aiops-syslog-parsed-YYYY.MM.DD
├── Kibana
│   └── Query, dashboard, validation
├── Python Worker
│   ├── Query Elasticsearch
│   ├── Aggregate statistics
│   ├── Call AI API
│   └── Write Markdown reports
├── Redis
│   └── Future active event state
└── MySQL
    └── Future reports, rules, devices, event state
```

## Data Flow

1. 城域网设备将 Syslog 转发到 JSCN-20 UDP 10087。
2. 城域网设备将 SNMP Trap 转发到 JSCN-20 UDP 10086。
3. Logstash 或配套接收组件接收原始数据。
4. 原始数据完整写入 Elasticsearch raw 索引。
5. Syslog 经过初步结构化解析后写入 parsed 索引。
6. Kibana 用于查询、验证和可视化。
7. Python Worker 定时读取 Elasticsearch 聚合结果。
8. Worker 将统计 JSON 发送给 AI 服务生成 Markdown 报告。
9. 报告保存到 `/data/jscn-aiops/reports`。

## Migration-Oriented Design

JSCN-20 是临时单机环境。所有设计必须支持后续迁移到三机集群：

1. 服务配置通过 `.env` 或环境变量注入。
2. 程序目录和数据目录分离。
3. 数据目录统一规划在 `/data/jscn-aiops`。
4. 部署目录统一规划在 `/opt/jscn-aiops`。
5. 索引命名使用固定前缀加日期。
6. 不在代码中写死单机 IP、密码、API Key 或绝对私有路径。
7. Docker Compose 文件后续应避免绑定单机不可迁移假设。

## Future Cluster Direction

后续三机集群可按以下方向拆分：

1. 接入层：Syslog、Trap、Logstash 或接收代理。
2. 存储层：Elasticsearch、MySQL、Redis。
3. 分析层：Python Worker、AI 报告、事件聚合服务。

具体部署拓扑需要在完成 JSCN-20 单机验证后，根据服务器资源和网络规划再定。
