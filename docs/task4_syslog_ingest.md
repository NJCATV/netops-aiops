# Task 4: Syslog 接入 Elasticsearch

## Scope

本任务只完成 Syslog UDP `10087` 接入 Elasticsearch。

已部署 Logstash，已编写 Syslog pipeline，已验证真实设备 Syslog 写入 ES。未接入 SNMP Trap，未做 Kibana 查询验证任务，未开发 Python Worker。

执行时间：2026-05-17

执行用户：`aiops`

## Services

| Service | Container | Image | Port |
| --- | --- | --- | --- |
| Elasticsearch | `jscn-aiops-elasticsearch` | `docker.elastic.co/elasticsearch/elasticsearch:7.17.27` | `9200/tcp` |
| Kibana | `jscn-aiops-kibana` | `docker.elastic.co/kibana/kibana:7.17.27` | `5601/tcp` |
| Logstash | `jscn-aiops-logstash` | `docker.elastic.co/logstash/logstash:7.17.27` | `10087/udp` |

Logstash 当前只监听 Syslog UDP `10087`，不监听 SNMP Trap UDP `10086`。

## Files

仓库文件：

```text
deploy/docker-compose.yml
deploy/logstash/config/logstash.yml
deploy/logstash/pipeline/syslog.conf
deploy/.env.example
```

JSCN-20 运行文件：

```text
/opt/jscn-aiops/deploy/docker-compose.yml
/opt/jscn-aiops/deploy/logstash/config/logstash.yml
/opt/jscn-aiops/deploy/logstash/pipeline/syslog.conf
/opt/jscn-aiops/deploy/.env
```

运行数据目录：

```text
/data/jscn-aiops/logstash/data
```

## Pipeline Behavior

Logstash pipeline 行为：

1. 使用 UDP input 监听 `0.0.0.0:10087`。
2. 将原始日志完整保存到 `raw_message`。
3. 提取来源 IP 到 `source_ip`。
4. 初步解析字段：
   - `log_time`
   - `source_ip`
   - `device_name`
   - `device_ip`
   - `module`
   - `severity`
   - `event_code`
   - `interface`
   - `slot`
   - `raw_message`
   - `parse_status`
   - `event_family`
   - `key_signals`
5. 同一事件同时写入 raw 索引和 parsed 索引。

索引：

```text
jscn-aiops-syslog-raw-YYYY.MM.DD
jscn-aiops-syslog-parsed-YYYY.MM.DD
```

## Host UDP Buffer

Logstash 初次启动时提示 UDP receive buffer 只能获得 `212992` bytes。为降低高峰期丢包风险，已设置：

```bash
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.rmem_default=262144
```

并写入：

```text
/etc/sysctl.d/98-jscn-aiops-syslog.conf
```

Logstash 重启后确认：

```text
UDP listener started {:address=>"0.0.0.0:10087", :receive_buffer_bytes=>"16777216", :queue_size=>"2000"}
```

## Start Command

```bash
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d logstash
```

## Verification

容器状态：

```text
jscn-aiops-elasticsearch   Up (healthy)   0.0.0.0:9200->9200/tcp
jscn-aiops-kibana          Up             0.0.0.0:5601->5601/tcp
jscn-aiops-logstash        Up             0.0.0.0:10087->10087/udp
```

主机 UDP 监听：

```bash
ss -lun | grep ':10087'
```

结果：

```text
UNCONN 0 0 0.0.0.0:10087 0.0.0.0:*
```

索引检查：

```bash
curl -s 'http://127.0.0.1:9200/_cat/indices/jscn-aiops-syslog-*?v'
```

结果已出现：

```text
jscn-aiops-syslog-raw-2026.05.17
jscn-aiops-syslog-parsed-2026.05.17
```

计数检查：

```bash
curl -s 'http://127.0.0.1:9200/jscn-aiops-syslog-raw-*/_count'
curl -s 'http://127.0.0.1:9200/jscn-aiops-syslog-parsed-*/_count'
```

结果：

```text
raw count: 46
parsed count: 46
```

最新真实 Syslog 字段抽样，原始日志内容已在本文档中脱敏：

```json
{
  "source_ip": "172.25.131.2",
  "device_name": "CXHJ-16K-M-A",
  "device_ip": "172.25.2.33",
  "module": "10PPP",
  "severity": "4",
  "event_code": "PPP_CHASTEN",
  "parse_status": "parsed",
  "event_family": "ppp",
  "key_signals": "172.25.2.33|CXHJ-16K-M-A|PPP_CHASTEN|ppp",
  "raw_message": "<redacted real syslog message>"
}
```

## Issue Fixed During Task

真实 H3C 样式日志格式中，日志时间后存在年份：

```text
<PRI>May 17 HH:mm:ss 2026 DEVICE ...
```

初版 pipeline 将 `2026` 误识别为 `device_name`。已修正 header grok 规则，并补充 `DevIP`、`Slot` 提取逻辑。修正后真实样例可正确得到：

```text
device_name: CXHJ-16K-M-A
device_ip: 172.25.2.33
slot: 18
```

## Commands Executed

```bash
ss -lun | grep ':10087' || true
docker pull docker.elastic.co/logstash/logstash:7.17.27
mkdir -p /opt/jscn-aiops/deploy/logstash/config
mkdir -p /opt/jscn-aiops/deploy/logstash/pipeline
sudo mkdir -p /data/jscn-aiops/logstash/data
sudo chown -R 1000:0 /data/jscn-aiops/logstash/data
sudo chmod -R g+rwX /data/jscn-aiops/logstash/data
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d logstash
docker-compose restart logstash
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.rmem_default=262144
docker-compose ps
docker-compose logs --tail=120 logstash
curl -s 'http://127.0.0.1:9200/_cat/indices/jscn-aiops-syslog-*?v'
curl -s 'http://127.0.0.1:9200/jscn-aiops-syslog-raw-*/_count'
curl -s 'http://127.0.0.1:9200/jscn-aiops-syslog-parsed-*/_count'
```

## Risks and Notes

1. 当前索引为 yellow 是单节点环境默认 replica 无法分配导致，不影响单机 MVP 写入和查询。
2. 当前 pipeline 是基础解析，后续仍需根据更多设备日志样本持续补充规则。
3. 当前同一事件同时写入 raw 和 parsed 索引，便于初期验收和回溯；后续可按存储成本优化。
4. 当前未配置 Index Template、ILM 和字段 mapping，后续 Kibana 查询验证前建议补齐。
5. 当前 ES security disabled，仅适用于临时单机内网 MVP。

## Acceptance Result

Task 4 验收项已完成：

1. Logstash 已监听 UDP `10087`。
2. 真实 Syslog 已进入 Elasticsearch。
3. `raw_message` 已完整保存。
4. raw 和 parsed 索引均已创建并写入。
5. 基础字段解析可用，已验证 `device_ip`、`device_name`、`event_code`。
6. 部署过程、验证命令和问题修复已记录。
