# AIOps 模块架构与安全边界

## 设计

20 承担日志/Trap/Syslog 接入、事件聚合、规则、AI 分析、知识库和 ELK。用户始终经 233:5772 的网管 BFF 访问，20 不提供独立的用户登录入口。

## 数据服务

| 服务 | 用途 |
| --- | --- |
| AIOps MySQL | 任务、运行记录、Finding、规则、模型、知识库和审计 |
| Elasticsearch | Syslog、Trap、事件和检索索引 |
| Kibana | 运维检索界面，仅限受控内网访问 |

## 端口与安全

| 接口 | 策略 |
| --- | --- |
| AIOps API 18080 / 18190 | 仅本机和 233 |
| MySQL 13306、Kibana 5601 | 仅本机和 `172.31.0.0/16` |
| Elasticsearch 9200 | 仅本机和 Docker bridge，禁止外部来源 |
| HTTP 8080/18088/3000/3001/6099 | 仅本机和 Docker bridge |
| SSH 5332 | Fail2ban：10 分钟 5 次失败，封禁 24 小时 |
| UDP 10086/10087、Cockpit 9090 | 待完整来源盘点后再收敛，不可凭空关停 |

`deploy/security/` 的端口守卫必须同时维护 `INPUT` 和 `DOCKER-USER`；Docker bridge 放行是应用内部依赖，不等同于对外开放。
