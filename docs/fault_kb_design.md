# 故障知识库与值班报修流水设计

## 数据分层

本项目建议把故障知识库分成两类数据：

1. 正式故障报告：来自故障排查报告和故障台账，单条记录质量高，适合作为问答引用的主要依据。
2. 值班报修流水：来自每日值班 Excel，数量大但噪声多，适合做高频问题聚合、处置经验补充、噪声统计和案例召回。

两类数据都可以进入 Elasticsearch，但问答召回时需要区分权重。正式报告默认权重最高；值班流水中 `knowledge_value=reference` 和 `aggregate_only` 可进入经验召回；`noise` 默认不进入问答，只用于统计分析。

## 值班流水结构化字段

`scripts/import_duty_repair_excel.py` 会把 Excel 行清洗成以下核心字段：

- 原始来源：`source_file`、`source_sheet`、`source_row`、`source_seq`、`raw_row`
- 时间字段：`occurred_date`、`occurred_time`、`recovery_time`
- 原始业务字段：`fault_category`、`report_type`、`fault_type`、`fault_content`、`handling_result`
- 归一字段：`service`、`area`、`canonical_symptom`、`canonical_symptom_label`
- 处置动作：`normalized_actions`
- 知识价值：`knowledge_value`、`knowledge_score`、`noise_reasons`
- 聚合字段：`aggregation_key`
- 向量预留：`embedding_candidate`、`embedding_status`、`embedding_text`、`embedding_model`

## 知识价值分级

- `reference`：可作为历史经验引用，例如省公司协查、设备/链路/出口/配置类故障、明确处置闭环。
- `aggregate_only`：单条参考价值一般，但适合聚合观察，例如多次出现的点8卡顿、回看异常。
- `low_value`：信息不足或处置弱，不优先进入问答。
- `noise`：账号在线、查拨号、查丢包、一般咨询等低价值流水，默认不进入知识库问答。

## 高频主题聚合

第一版内置的 `canonical_symptom` 包括：

- `dot8_stutter_or_failure`：点8卡顿、黑屏、加载失败
- `replay_fault`：回看黑屏、无声音、未录制、快进后退异常
- `vod_fault`：点播黑屏、卡顿、失败
- `stb_boot_or_launcher_stuck`：机顶盒开机、首页、初始化卡死
- `ipqam_frequency_or_capacity`：IPQAM 频点和容量问题
- `olt_policy_or_vlan`：OLT 策略、ACL、VLAN 配置问题
- `access_loop_broadcast_storm`：接入环路、广播风暴、MAC 漂移
- `broadband_routing_or_export`：出口、路由、NAT、DNS、VPN 相关问题
- `account_dialing_query`：账号、拨号、在线查询

## 向量检索策略

当前导入阶段先落 `embedding_text` 和 `embedding_status=pending`，不直接写死向量维度。原因是 Elasticsearch 7.x 的 `dense_vector` 需要固定维度，而维度取决于最终选用的 embedding 模型。

后续上向量检索时建议新增模型版本化索引，例如：

- `jscn-aiops-duty-repair-vectors-v1`
- `jscn-aiops-fault-report-vectors-v1`

向量文档用 `record_id` 关联原始记录，保存 `embedding_model`、`embedding_dims`、`embedding_vector`、`embedding_text_hash`。这样可以更换 embedding 模型而不重建原始知识库索引。

## 今日落库命令

Dry-run：

```bash
python3 scripts/import_duty_repair_excel.py \
  --input /path/to/20260611故障汇总.xlsx \
  --dry-run
```

写入 Elasticsearch：

```bash
python3 scripts/import_duty_repair_excel.py \
  --input /path/to/20260611故障汇总.xlsx
```

如只想落知识库候选记录，不落噪声记录：

```bash
python3 scripts/import_duty_repair_excel.py \
  --input /path/to/20260611故障汇总.xlsx \
  --drop-noise
```
