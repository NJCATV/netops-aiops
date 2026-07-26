# QQ 群接入：NapCat + OneBot

本文档说明如何把 AIOps 故障报修文档助手接入 QQ 群。当前实现采用 NapCat 的 OneBot HTTP 能力：

- NapCat 负责登录 QQ 号、接收群消息、执行发群消息 API。
- `aiops-qq-adapter` 负责接收 OneBot 事件、过滤群和触发词、调用 AIOps 故障知识库问答接口。
- AIOps API 继续使用现有登录态鉴权，适配器使用专用机器人账号登录。

## 1. 准备 AIOps 机器人账号

在 AIOps Web 控制台中创建一个普通查看账号，例如：

```text
username: qq-bot
role: viewer
```

QQ Adapter 只允许使用平台服务身份，不再支持 AIOps 本地账号密码：

```env
AIOPS_INTERNAL_SHARED_SECRET=与统一平台 BFF 相同的长随机密钥
AIOPS_BOT_SERVICE_SUBJECT=service:qq-adapter
```

## 2. 配置 QQ 适配器

在 `deploy/.env` 中增加或修改：

```env
QQ_ADAPTER_HTTP_PORT=18088
QQ_ADAPTER_EVENT_TOKEN=替换为随机长字符串
QQ_GROUP_ALLOWLIST=123456789
QQ_BOT_SELF_ID=机器人QQ号
QQ_TRIGGER_PREFIX=/故障,/报修,/kb,#故障,#报修
QQ_REPLY_TIMEOUT_SECONDS=90
QQ_MAX_REPLY_CHARS=1600

ONEBOT_API_BASE=http://host.docker.internal:3000
ONEBOT_ACCESS_TOKEN=替换为NapCat里的OneBot访问令牌
ONEBOT_TOKEN_IN_QUERY=false
QQ_ADAPTER_AIOPS_API_BASE=http://aiops-api:8080
```

说明：

- `QQ_GROUP_ALLOWLIST` 必填。为空时适配器会拒绝所有群消息，避免误接入。
- `QQ_ADAPTER_EVENT_TOKEN` 用于保护事件上报地址。NapCat 端可以把它追加到 URL：`?token=...`。
- `ONEBOT_API_BASE` 是 NapCat 的 OneBot HTTP API 地址。如果 NapCat 不在 Docker 宿主机上，改成实际 IP，例如 `http://192.168.1.20:3000`。
- `ONEBOT_ACCESS_TOKEN` 必须和 NapCat OneBot HTTP 服务配置一致。

## 3. 启动适配器

在服务器上执行：

```bash
cd /opt/jscn-aiops/deploy
docker-compose up -d --build aiops-qq-adapter
docker-compose logs --tail=100 -f aiops-qq-adapter
```

健康检查：

```bash
curl -s http://127.0.0.1:18088/health
```

期望返回：

```json
{"service":"aiops-qq-adapter","status":"ok"}
```

## 4. 配置 NapCat

在 NapCat WebUI 中启用 OneBot HTTP 服务：

```text
HTTP API 地址: http://0.0.0.0:3000
Access Token: 与 ONEBOT_ACCESS_TOKEN 一致
```

启用 HTTP POST 事件上报，URL 填：

```text
http://AIOps服务器IP:18088/onebot/event?token=QQ_ADAPTER_EVENT_TOKEN的值
```

如果 NapCat 和 AIOps 运行在同一台服务器，也可以填：

```text
http://127.0.0.1:18088/onebot/event?token=QQ_ADAPTER_EVENT_TOKEN的值
```

## 5. 群内使用方式

当前只响应白名单群里的触发消息：

```text
/故障 DVB机顶盒回看黑屏怎么排查
/报修 EOC广播风暴导致批量用户异常
/kb OLT策略配置缺失会导致点播打不开吗
@故障助手 IPQAM频点异常怎么处理
```

适配器会先回复：

```text
已收到，正在查询故障知识库...
```

随后发送知识库问答结果。连续追问会按 `群 + 用户` 维度复用后端会话，适配器重启后会话映射会清空。

## 6. 手工模拟事件

可用下面命令验证事件入口，不依赖真实 QQ 群：

```bash
curl -s -X POST "http://127.0.0.1:18088/onebot/event?token=QQ_ADAPTER_EVENT_TOKEN的值" \
  -H "Content-Type: application/json" \
  -d '{
    "post_type": "message",
    "message_type": "group",
    "group_id": 123456789,
    "user_id": 10001,
    "self_id": 机器人QQ号,
    "message_id": 1,
    "raw_message": "/故障 DVB回看黑屏"
  }'
```

如果返回 `{"ok":true,"status":"accepted"}`，说明适配器已接受事件。之后若发群失败，检查：

- `ONEBOT_API_BASE` 是否能从适配器容器访问。
- `ONEBOT_ACCESS_TOKEN` 是否与 NapCat 一致。
- NapCat 登录 QQ 是否已在目标群内。

## 7. 安全边界

- 不要把 NapCat WebUI、OneBot HTTP API、`/onebot/event` 暴露到公网。
- 机器人 QQ 号建议只加入目标运维群。
- `QQ_GROUP_ALLOWLIST` 必须只填允许使用的群号。
- 机器人账号使用 AIOps 普通查看权限即可，不需要管理员权限。
