# Deployment

本目录保存 JSCN AIOps 的部署文件。统一网管接入后的目标形态采用控制面/数据面拆分：

| 项目 | 生产约束 |
| --- | --- |
| 用户入口 | `233:5772/2026/legacy-aiops/`，由统一平台菜单打开 |
| API | 浏览器只调用 `233:5772/api/netops2026/aiops/*` |
| 本地鉴权 | 注册、密码登录、Session 兜底全部禁用 |
| 20 旧 Web | `AIOPS_WEB_BIND=127.0.0.1`，仅供本机健康检查和回滚 |
| 身份 | 233 BFF 使用 HMAC 签名的平台身份；内部服务使用共享密钥身份 |

- `docker-compose.20-data-plane.yml`：20 上的 ELK、事件聚合和 QQ 适配器。
- `systemd/`：233 上的 AIOps API 与调度器。
- `split-deployment-runbook.md`：MySQL 合并、灰度、验证和回滚步骤。
- 原 `docker-compose.yml` 仅保留为单机历史部署与紧急回滚参考，不再作为目标态。

## Current Scope

当前已完成 Task 4：Syslog 接入 Elasticsearch。

`docker-compose.yml` 当前包含：

1. Elasticsearch `7.17.27` 单节点服务。
2. Kibana `7.17.27` 服务。
3. Logstash `7.17.27` 服务，监听 Syslog UDP `10087`。
4. 项目级 Docker network。
5. Elasticsearch 数据目录挂载到 `/data/jscn-aiops/es`。
6. Logstash 数据目录挂载到 `/data/jscn-aiops/logstash/data`。

说明：JSCN-20 当前安装的是 Ubuntu 20.04 仓库提供的 `docker-compose` v1.25.0，因此 Compose 文件使用 v1 兼容写法。

## Runtime Paths

JSCN-20 当前规划：

```text
/opt/jscn-aiops
/data/jscn-aiops
/data/jscn-aiops/es
/data/jscn-aiops/logstash
/data/jscn-aiops/reports
/data/jscn-aiops/backups
```

## Basic Commands

在 JSCN-20 上执行：

```bash
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d elasticsearch kibana logstash
```

验证：

```bash
curl -s http://127.0.0.1:9200
curl -I http://127.0.0.1:5601
docker-compose logs --tail=100 logstash
curl -s 'http://127.0.0.1:9200/_cat/indices/jscn-aiops-syslog-*?v'
```

当前只部署 ES/Kibana/Logstash，不包含 Trap 接入、Redis、MySQL 或 Python Worker。
