# Task 5: SNMP Trap 接入 Elasticsearch

## Scope

本任务部署 SNMP Trap UDP `10086` 接入链路，用于 Trap 原始留存和基础字段提取。

当前已完成：

1. Logstash 增加 SNMP Trap input。
2. JSCN-20 已监听 UDP `10086`。
3. Trap pipeline 已准备写入 `jscn-aiops-trap-raw-YYYY.MM.DD`。
4. 已确认 Logstash 启动日志中 SNMP Trap input 正常启动。
5. 已收到真实设备 Trap 并写入 Elasticsearch。

执行时间：2026-05-17

执行用户：`aiops`

## MIB Decision

用户提供了 H3C 新风格 MIB 对象说明参考文件：

```text
D:/xwechat_files/wxid_1109341050512_6c26/msg/file/2026-05/Quick reference of H3C new style MIB objects description.txt
```

当前阶段不需要立即接入 MIB 库，原因：

1. Task 5 目标是 Trap 原始留存和基础字段提取，不追求完整 MIB 翻译。
2. 先保存原始 Trap 和 OID，可以保证数据不丢。
3. MIB 翻译属于后续增强解析，可以在有真实 Trap 样本后再补充。
4. 该文件是本地参考资料，未复制到服务器，未提交 Git。

后续需要 MIB 的场景：

1. 将 OID 翻译为 H3C 对象名。
2. 将 varbind 值转换为更易读的枚举或含义说明。
3. 建立 Trap OID 到 `event_family`、告警级别、设备部件的映射。

## Services

| Service | Container | Image | Port |
| --- | --- | --- | --- |
| Logstash | `jscn-aiops-logstash` | `docker.elastic.co/logstash/logstash:7.17.27` | `10086/udp`, `10087/udp` |

## Files

新增或更新：

```text
deploy/logstash/pipeline/trap.conf
deploy/logstash/pipeline/syslog.conf
deploy/docker-compose.yml
deploy/.env.example
.env.example
```

JSCN-20 运行文件：

```text
/opt/jscn-aiops/deploy/logstash/pipeline/trap.conf
/opt/jscn-aiops/deploy/logstash/pipeline/syslog.conf
/opt/jscn-aiops/deploy/docker-compose.yml
/opt/jscn-aiops/deploy/.env
```

## Trap Input Configuration

当前配置：

```text
host: 0.0.0.0
port: 10086
community: public
target: [trap][varbinds]
type: snmptrap
```

说明：

1. 当前默认 community 为 `public`。
2. 用户已确认设备侧 community 为 `public`。
3. 用户确认设备不是 SNMPv3，可能为 SNMP v1 或 v2c。
4. 当前使用 Logstash `logstash-input-snmptrap 3.1.0`，可接收 SNMP v1/v2c Trap。

## Pipeline Behavior

Trap pipeline 行为：

1. 监听 UDP `10086`。
2. 将 Trap 对象字符串保存为 `raw_message`。
3. 将 varbinds 保存到 `[trap][varbinds]`。
4. 提取基础字段：
   - `source_ip`
   - `device_ip`
   - `trap_oid`
   - `enterprise_oid`
   - `varbind_count`
   - `trap_varbind_oids`
   - `parse_status`
   - `key_signals`
5. 写入索引：

```text
jscn-aiops-trap-raw-YYYY.MM.DD
```

## Verification

Logstash 插件确认：

```text
logstash-input-snmptrap (3.1.0)
```

监听确认：

```bash
ss -lun | egrep ':10086|:10087'
```

结果：

```text
UNCONN 0 0 0.0.0.0:10086 0.0.0.0:*
UNCONN 0 0 0.0.0.0:10087 0.0.0.0:*
```

Logstash 启动日志：

```text
[jscn_snmptrap_udp_10086] It's a Trap! {:Port=>10086, :Community=>["public"], :Host=>"0.0.0.0"}
```

Trap 索引轮询：

```bash
curl -s 'http://127.0.0.1:9200/_cat/indices/jscn-aiops-trap-*?v'
curl -s 'http://127.0.0.1:9200/jscn-aiops-trap-raw-*/_count'
```

结果：

```text
trap raw count: 51
```

结论：真实设备 Trap 已进入 Elasticsearch。

真实 Trap 样例字段，原始内容在本文档中脱敏：

```json
{
  "source_ip": "172.25.131.3",
  "device_ip": "172.25.131.3",
  "varbind_count": 4,
  "parse_status": "partial",
  "trap_varbind_oids": [
    "SNMPv2-SMI::mib-2.67.2.2.1.1.3.1.2.2",
    "SNMPv2-SMI::mib-2.67.2.2.1.1.3.1.3.2",
    "SNMPv2-SMI::enterprises.25506.2.13.7.1.0",
    "SNMPv2-SMI::enterprises.25506.4.2.2.1.102"
  ],
  "raw_message": "<redacted real SNMP trap message>"
}
```

说明：设备侧确认不是 SNMPv3。Logstash 插件将部分 enterprise-specific Trap 表示为 `SNMPv1_Trap` 对象，这是插件内部表示，不影响当前原始留存和基础字段提取。

## Commands Executed

```bash
docker exec jscn-aiops-logstash bin/logstash-plugin list --verbose | grep -i snmp
ss -lun | grep ':10086' || true
cd /opt/jscn-aiops/deploy
docker-compose config
docker-compose up -d logstash
docker-compose ps logstash
docker logs --since 10m jscn-aiops-logstash
curl -s 'http://127.0.0.1:9200/_cat/indices/jscn-aiops-trap-*?v'
curl -s 'http://127.0.0.1:9200/jscn-aiops-trap-raw-*/_count'
```

## Acceptance Status

当前状态：Done。

已满足：

1. UDP `10086` 已监听。
2. Trap pipeline 已部署。
3. Trap raw 索引输出路径已配置。
4. 真实 Trap 已进入 Elasticsearch。
5. 已验证 `raw_message`、`source_ip`、`device_ip`、`varbind_count`、`trap_varbind_oids`、`parse_status`。

后续增强：

1. 接入 H3C MIB/YAML 映射。
2. 将 H3C OID 映射为更明确的 `trap_oid`、`device_name`、`event_family` 和告警含义。
3. 配置 ES Index Template 和 ILM。
