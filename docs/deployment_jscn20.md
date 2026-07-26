# JSCN-20 Deployment Plan

## Scope

本文记录 JSCN-20 临时单机部署方案、目录规划、端口规划和后续迁移注意事项。

当前 Task 0 不连接 JSCN-20，不部署任何服务。本文只记录计划。

## Deployment Mode

本项目采用服务器驻场开发模式。后续从 Task 1 开始，代码、部署、调试应直接在 JSCN-20 上进行。

当前部署状态：

1. Docker Engine 已安装。
2. `docker-compose` v1.25.0 已安装。
3. Elasticsearch `7.17.27` 已部署。
4. Kibana `7.17.27` 已部署。
5. Logstash `7.17.27` 已部署并监听 UDP `10087` 和 UDP `10086`。
6. Redis、MySQL、Python Worker 尚未部署。

## Directory Plan

```text
/opt/jscn-aiops              # 项目程序和部署文件
/data/jscn-aiops             # 数据目录，后续可迁移
/data/jscn-aiops/es          # Elasticsearch 数据
/data/jscn-aiops/logstash    # Logstash pipeline 和日志
/data/jscn-aiops/reports     # AI 报告输出
/data/jscn-aiops/backups     # 备份
```

设计原则：

1. 程序目录和数据目录分离。
2. 数据目录不放入 Git。
3. 运行配置不写死在代码中。
4. 后续迁移时以 `/data/jscn-aiops` 为主要数据迁移边界。

## Port Plan

| Service | Port | Protocol | Purpose |
| --- | ---: | --- | --- |
| Syslog input | 10087 | UDP | 接收城域网设备 Syslog |
| SNMP Trap input | 10086 | UDP | 接收城域网设备 SNMP Trap |
| Elasticsearch | 9200 | TCP | Elasticsearch HTTP API |
| Kibana | 5601 | TCP | Kibana Web UI |
| Redis | 6379 | TCP | 后续实时事件状态 |
| MySQL | 3306 | TCP | 后续报告、规则、设备清单、事件状态 |

当前 Elasticsearch 和 Kibana 已监听 TCP `9200`、`5601`。Logstash 已监听 UDP `10087` 和 UDP `10086`。Trap 真实流量验收尚未完成。

## Environment Variables

实际运行配置应来自 `.env` 或服务器环境变量。`.env.example` 只提供示例项，不包含真实密码、API Key 或 SSH 密钥。

关键配置类别：

1. 部署路径：`AIOPS_DEPLOY_ROOT`、`AIOPS_DATA_ROOT`。
2. 接收端口：`SYSLOG_UDP_PORT`、`SNMP_TRAP_UDP_PORT`。
3. Elasticsearch：地址、用户名、密码、索引前缀。
4. AI 服务：接口地址、模型名、API Key。
5. 报告任务：回看小时数、报告目录、定时表达式。

## Migration Notes

JSCN-20 是临时单机环境，不能形成不可迁移依赖。

后续迁移到三台服务器时需要关注：

1. Elasticsearch 数据迁移或重新建集群后的索引同步。
2. Logstash pipeline 和接收端口迁移。
3. 设备侧 Syslog 和 Trap 目标地址切换。
4. Redis、MySQL 数据备份恢复。
5. `.env` 配置按新拓扑重写。
6. Kibana saved objects 导出导入。
7. 报告目录和历史 Markdown 文件迁移。

## Future Task 1 Checklist

Task 1 需要在 JSCN-20 上检查：

1. SSH 登录方式。
2. 操作系统版本和内核版本。
3. CPU、内存、磁盘容量。
4. Docker 和 Docker Compose 是否已安装。
5. Git 是否已安装。
6. UDP 10087 和 UDP 10086 是否被占用。
7. 防火墙和安全组是否允许接收 UDP 10087、UDP 10086。
8. `/opt/jscn-aiops` 和 `/data/jscn-aiops` 是否可创建。
