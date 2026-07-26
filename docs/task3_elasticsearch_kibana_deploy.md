# Task 3: Elasticsearch + Kibana 部署

## Scope

本任务只完成 JSCN-20 上 Elasticsearch 和 Kibana 的 Docker Compose 单机部署与验证。

未接入 Syslog，未接入 SNMP Trap，未部署 Logstash，未部署 Redis/MySQL，未开发 Python Worker。

执行时间：2026-05-17

执行用户：`aiops`

## Version Selection

本阶段采用 Elastic Stack `7.17.27`。

选择原因：

1. 与 Ubuntu 20.04 仓库中的 `docker-compose` v1.25.0 兼容。
2. 单机部署复杂度低，便于先完成数据底座验证。
3. 可关闭安全认证，避免在初期提交或传播默认密码。
4. 后续迁移集群时可再设计认证、证书和高可用拓扑。

## Images

已成功从 Elastic 官方镜像仓库拉取：

```text
docker.elastic.co/elasticsearch/elasticsearch:7.17.27
docker.elastic.co/kibana/kibana:7.17.27
```

说明：Task 2 中 Docker Hub 拉取 `hello-world` 超时，但本次访问 `docker.elastic.co` 正常。

## Compose Services

部署文件：

```text
/opt/jscn-aiops/deploy/docker-compose.yml
```

服务：

| Service | Container | Image | Port |
| --- | --- | --- | --- |
| Elasticsearch | `jscn-aiops-elasticsearch` | `docker.elastic.co/elasticsearch/elasticsearch:7.17.27` | `9200:9200` |
| Kibana | `jscn-aiops-kibana` | `docker.elastic.co/kibana/kibana:7.17.27` | `5601:5601` |

关键配置：

| Item | Value |
| --- | --- |
| ES cluster name | `jscn-aiops-cluster` |
| ES node name | `jscn-aiops-es01` |
| ES mode | `single-node` |
| ES security | disabled for initial single-node MVP |
| ES JVM | `-Xms2g -Xmx2g` |
| Kibana locale | `zh-CN` |
| Timezone | `Asia/Shanghai` |

## Runtime Paths

Elasticsearch 数据目录：

```text
/data/jscn-aiops/es
```

目录权限：

```bash
sudo chown -R 1000:0 /data/jscn-aiops/es
sudo chmod -R g+rwX /data/jscn-aiops/es
```

说明：Elastic 官方容器内 Elasticsearch 用户 UID 为 `1000`，因此 ES 数据目录需要允许 UID `1000` 写入。

## Host Kernel Setting

已设置：

```bash
sudo sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-jscn-aiops.conf
```

原因：Elasticsearch 需要较高的 `vm.max_map_count`。

## Start Command

```bash
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d elasticsearch kibana
```

## Verification

容器状态：

```text
jscn-aiops-elasticsearch   Up (healthy)   0.0.0.0:9200->9200/tcp
jscn-aiops-kibana          Up             0.0.0.0:5601->5601/tcp
```

Elasticsearch API：

```bash
curl -s http://127.0.0.1:9200
```

返回版本：

```text
number: 7.17.27
cluster_name: jscn-aiops-cluster
node: jscn-aiops-es01
```

Elasticsearch cluster health：

```bash
curl -s http://127.0.0.1:9200/_cluster/health?pretty
```

返回：

```text
status: green
number_of_nodes: 1
number_of_data_nodes: 1
active_shards_percent_as_number: 100.0
```

Kibana status：

```bash
curl -s -H 'kbn-xsrf: true' http://127.0.0.1:5601/api/status
```

返回：

```text
HTTP 200
overall status: green
version: 7.17.27
```

本地到 JSCN-20 访问验证：

```bash
curl http://172.25.60.20:9200
curl -H 'kbn-xsrf: true' http://172.25.60.20:5601/api/status
```

结果：ES 返回版本信息，Kibana status 返回 HTTP `200`。

## Access URLs

| Service | URL |
| --- | --- |
| Elasticsearch | `http://172.25.60.20:9200` |
| Kibana | `http://172.25.60.20:5601` |

当前安全认证关闭，仅适用于临时单机内网 MVP。后续迁移或开放访问前必须重新设计认证、证书和访问控制。

## Commands Executed

```bash
curl -I --connect-timeout 10 https://docker.elastic.co
docker pull docker.elastic.co/elasticsearch/elasticsearch:7.17.27
docker pull docker.elastic.co/kibana/kibana:7.17.27
sudo sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-jscn-aiops.conf
sudo chown -R 1000:0 /data/jscn-aiops/es
sudo chmod -R g+rwX /data/jscn-aiops/es
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d elasticsearch kibana
docker-compose ps
curl -s http://127.0.0.1:9200
curl -s http://127.0.0.1:9200/_cluster/health?pretty
curl -s -H 'kbn-xsrf: true' http://127.0.0.1:5601/api/status
```

## Risks and Notes

1. 当前 ES security disabled，仅适合临时单机内网环境。
2. 当前未配置账号、密码、TLS 和反向代理。
3. Docker Root Dir 仍在 `/var/lib/docker`，实际业务数据通过 bind mount 落到 `/data/jscn-aiops/es`。
4. ES 数据目录属主为容器 UID `1000`，这是 Elastic 官方镜像运行要求。
5. 后续 Task 4 接入 Syslog 前，需要新增 Logstash 服务和 pipeline。

## Acceptance Result

Task 3 验收项已完成：

1. Elasticsearch 已启动并可访问。
2. Kibana 已启动并可访问。
3. ES cluster health 为 green。
4. ES 数据目录已持久化到 `/data/jscn-aiops/es`。
5. 部署过程、验证命令和风险已记录。
