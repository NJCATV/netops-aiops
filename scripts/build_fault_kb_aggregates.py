#!/usr/bin/env python3
"""Build fault-topic aggregates from formal KB and duty repair ES records."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Iterable, Optional


KNOWN_LABELS = {
    "dot8_stutter_or_failure": "点8卡顿/黑屏/加载异常",
    "replay_fault": "回看异常",
    "vod_fault": "点播异常",
    "stb_boot_or_launcher_stuck": "机顶盒开机/首页卡死",
    "ipqam_frequency_or_capacity": "IPQAM频点/容量异常",
    "olt_policy_or_vlan": "OLT策略/VLAN配置异常",
    "access_loop_broadcast_storm": "接入环路/广播风暴",
    "broadband_routing_or_export": "宽带出口/路由异常",
    "content_or_epg_issue": "片源/频道/EPG问题",
    "product_ordering_issue": "产品订购问题",
    "broadband_speed_issue": "宽带测速/带宽问题",
    "packet_loss_query": "丢包查询",
    "account_dialing_query": "账号/拨号查询",
}
MINED_TERMS = [
    "微信小程序",
    "省中医院",
    "我的南京",
    "学信网",
    "网址打不开",
    "APP打不开",
    "google mail",
    "苏银豆",
    "VPN",
    "DNS",
    "NAT",
    "DHCP",
    "出口",
    "路由",
    "股票",
    "爱奇艺",
    "EPG",
    "开机广告",
    "机顶盒升级",
    "全省通",
    "6分钟",
    "频道号",
    "频道",
    "产品订购",
    "BOSS",
    "支付",
    "收会员",
    "网络电话",
    "WiFi热点",
    "投屏",
    "无法升级",
    "测速",
    "上行",
    "下行",
    "丢包",
    "拨号",
    "多终端",
    "认证失败",
    "域名访问失败",
    "获取可订购产品列表失败",
    "黑屏",
    "卡顿",
    "花屏",
    "马赛克",
    "失真",
    "音画不同步",
    "声音停顿",
    "语音",
    "无声音",
    "未录制",
    "报错",
    "5004",
    "快进",
    "回看",
    "点播",
    "直播",
    "IPQAM",
    "OLT",
    "ONU",
    "EOC",
    "VLAN",
    "ACL",
    "环路",
    "广播风暴",
    "MAC漂移",
    "MAC地址漂移",
    "CCTV",
    "央视",
    "江苏卫视",
    "南京影视",
    "南京教科",
    "九城游戏",
    "星空棋牌",
    "斗地主",
    "机卡不一致",
]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u200c", "").replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def stable_id(parts: Iterable[Any]) -> str:
    payload = "|".join(clean_text(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def es_request(es_url: str, method: str, path: str, body: Optional[dict] = None, ndjson: Optional[str] = None) -> dict:
    if ndjson is not None:
        data = ndjson.encode("utf-8")
        headers = {"Content-Type": "application/x-ndjson"}
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        data = None
        headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(es_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Elasticsearch request failed: {exc.code} {detail}") from exc
    return json.loads(payload) if payload else {}


def install_template(es_url: str, template_path: pathlib.Path, template_name: str) -> dict:
    body = json.loads(template_path.read_text(encoding="utf-8"))
    return es_request(es_url, "PUT", f"/_index_template/{template_name}", body)


def scroll_docs(es_url: str, index_pattern: str, query: dict, size: int = 500) -> Iterable[dict[str, Any]]:
    result = es_request(es_url, "POST", f"/{index_pattern}/_search?scroll=2m", {"size": size, "query": query, "sort": ["_doc"]})
    scroll_id = result.get("_scroll_id")
    try:
        while True:
            hits = result.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                source = hit.get("_source") or {}
                source["_index"] = hit.get("_index")
                source["_id"] = hit.get("_id")
                yield source
            result = es_request(es_url, "POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
            scroll_id = result.get("_scroll_id")
    finally:
        if scroll_id:
            try:
                es_request(es_url, "DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
            except Exception:
                pass


def record_text(record: dict[str, Any]) -> str:
    return clean_text(
        " ".join(
            str(record.get(field) or "")
            for field in [
                "title",
                "fault_content",
                "handling_result",
                "root_cause",
                "investigation_steps",
                "fix_method",
                "prevention",
                "report_text",
                "embedding_text",
            ]
        )
    )


def mined_terms(record: dict[str, Any]) -> list[str]:
    text = record_text(record)
    found: list[str] = []
    lower = text.lower()
    for term in MINED_TERMS:
        if term.lower() in lower:
            found.append(term)
    for code in re.findall(r"\b(?:0x[0-9a-fA-F]+|[A-Z]{2,}\d{2,}|GDF\d{5,}|GDC\d{5,})\b", text):
        if not code.startswith(("GDF", "GDC")):
            found.append(code)
    return sorted(set(found), key=lambda item: (-len(item), item))[:3]


def topic_for_record(record: dict[str, Any]) -> tuple[str, str, str]:
    symptom = clean_text(record.get("canonical_symptom"))
    service = clean_text(record.get("service")) or "other"
    if symptom and symptom != "unknown":
        return f"rule:{service}:{symptom}", KNOWN_LABELS.get(symptom, symptom), "rule"
    terms = mined_terms(record)
    if terms:
        label = " / ".join(terms)
        return f"mined:{service}:{stable_id(terms)[:12]}", label, "mined"
    return f"mined:{service}:other", "其他未归类故障", "mined"


def parse_time(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        return text
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return iso_z(parsed)


def build_aggregates(records: list[dict[str, Any]], min_count: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, tuple[str, str]] = {}
    for record in records:
        key, label, source = topic_for_record(record)
        groups[key].append(record)
        labels[key] = (label, source)
    now = iso_z(utc_now())
    aggregates: list[dict[str, Any]] = []
    for topic_key, items in groups.items():
        if len(items) < min_count:
            continue
        label, topic_source = labels[topic_key]
        times = [parse_time(item.get("occurred_time") or item.get("@timestamp")) for item in items]
        times = [item for item in times if item]
        source_counter = Counter(item.get("source_type") or "__missing__" for item in items)
        value_counter = Counter(item.get("knowledge_value") or "__missing__" for item in items)
        action_counter: Counter[str] = Counter()
        area_counter: Counter[str] = Counter()
        report_type_counter: Counter[str] = Counter()
        for item in items:
            action_counter.update(item.get("normalized_actions") or [])
            if item.get("area"):
                area_counter[item["area"]] += 1
            if item.get("report_type"):
                report_type_counter[item["report_type"]] += 1
        representatives = sorted(items, key=lambda item: (item.get("knowledge_score") or 0, item.get("occurred_time") or ""), reverse=True)[:5]
        sample_cases = [
            {
                "record_id": item.get("record_id"),
                "source_type": item.get("source_type"),
                "occurred_date": item.get("occurred_date"),
                "title": item.get("title") or (item.get("fault_content") or "")[:80],
                "knowledge_value": item.get("knowledge_value"),
                "source_file": item.get("source_file"),
            }
            for item in representatives
        ]
        canonical = clean_text(representatives[0].get("canonical_symptom")) if representatives else ""
        service = clean_text(representatives[0].get("service")) if representatives else ""
        area = clean_text(representatives[0].get("area")) if representatives else ""
        aggregate = {
            "@timestamp": now,
            "aggregate_id": stable_id([topic_key]),
            "topic_key": topic_key,
            "topic_label": label,
            "topic_source": topic_source,
            "canonical_symptom": canonical,
            "service": service,
            "area": area,
            "total_count": len(items),
            "reference_count": value_counter.get("reference", 0),
            "aggregate_only_count": value_counter.get("aggregate_only", 0),
            "formal_count": source_counter.get("formal_fault_report", 0),
            "duty_count": source_counter.get("duty_repair_excel", 0),
            "noise_count": value_counter.get("noise", 0),
            "embedding_candidate_count": sum(1 for item in items if item.get("embedding_candidate")),
            "first_seen": min(times) if times else None,
            "last_seen": max(times) if times else None,
            "top_actions": [key for key, _ in action_counter.most_common(10)],
            "top_areas": [key for key, _ in area_counter.most_common(10)],
            "top_report_types": [key for key, _ in report_type_counter.most_common(10)],
            "representative_cases": sample_cases,
            "suggested_query": label,
            "updated_at": now,
        }
        aggregates.append(aggregate)
    return sorted(aggregates, key=lambda item: (item["total_count"], item["reference_count"]), reverse=True)


def bulk_replace(es_url: str, index_name: str, aggregates: list[dict[str, Any]]) -> dict[str, Any]:
    lines: list[str] = []
    for aggregate in aggregates:
        lines.append(json.dumps({"index": {"_index": index_name, "_id": aggregate["aggregate_id"]}}, ensure_ascii=False))
        lines.append(json.dumps(aggregate, ensure_ascii=False))
    if not lines:
        return {"indexed": 0, "failed": 0, "errors": []}
    result = es_request(es_url, "POST", "/_bulk", ndjson="\n".join(lines) + "\n")
    failed = 0
    errors: list[dict[str, Any]] = []
    for item in result.get("items", []):
        index = item.get("index", {})
        if index.get("error"):
            failed += 1
            errors.append(index)
    return {"indexed": len(result.get("items", [])) - failed, "failed": failed, "errors": errors[:20]}


def write_report(path: pathlib.Path, report: dict[str, Any]) -> None:
    lines = [
        "# Fault KB Aggregates Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Source records: `{report['source_records']}`",
        f"- Aggregates: `{report['aggregate_count']}`",
        f"- Indexed: `{report['indexed']}`",
        f"- Failed: `{report['failed']}`",
        "",
        "| Topic | Source | Count | Formal | Duty | Reference |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for item in report["top_aggregates"][:30]:
        lines.append(
            "| `%s` | `%s` | %s | %s | %s | %s |"
            % (
                item["topic_label"],
                item["topic_source"],
                item["total_count"],
                item["formal_count"],
                item["duty_count"],
                item["reference_count"],
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--formal-index", default=os.getenv("FAULT_KB_INDEX", "jscn-aiops-fault-kb-*"))
    parser.add_argument("--duty-index", default=os.getenv("DUTY_REPAIR_INDEX", "jscn-aiops-duty-repair-records-*"))
    parser.add_argument("--target-index", default=os.getenv("FAULT_KB_AGGREGATE_INDEX", "jscn-aiops-fault-topic-aggregates"))
    parser.add_argument("--template", default=os.getenv("FAULT_KB_AGGREGATE_TEMPLATE", "deploy/elasticsearch/templates/fault_kb_aggregates_template.json"))
    parser.add_argument("--report", default=os.getenv("FAULT_KB_AGGREGATE_REPORT", "reports/fault_kb/fault_kb_aggregates_report.md"))
    parser.add_argument("--min-count", type=int, default=int(os.getenv("FAULT_KB_AGGREGATE_MIN_COUNT", "2")))
    parser.add_argument("--include-noise", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-template", action="store_true")
    args = parser.parse_args()

    query: dict[str, Any] = {"match_all": {}}
    if not args.include_noise:
        query = {"bool": {"must_not": [{"term": {"knowledge_value": "noise"}}]}}
    records = list(scroll_docs(args.es_url, args.formal_index, query)) + list(scroll_docs(args.es_url, args.duty_index, query))
    aggregates = build_aggregates(records, args.min_count)
    result = {"indexed": 0, "failed": 0, "errors": []}
    if not args.dry_run:
        if not args.skip_template:
            install_template(args.es_url, pathlib.Path(args.template), "jscn-aiops-fault-kb-aggregates")
        try:
            es_request(args.es_url, "DELETE", f"/{urllib.parse.quote(args.target_index, safe='')}")
        except RuntimeError as exc:
            if "Elasticsearch request failed: 404" not in str(exc):
                raise
        result = bulk_replace(args.es_url, args.target_index, aggregates)
    report = {
        "generated_at": iso_z(utc_now()),
        "source_records": len(records),
        "aggregate_count": len(aggregates),
        "indexed": result["indexed"],
        "failed": result["failed"],
        "errors": result["errors"],
        "top_aggregates": aggregates[:50],
    }
    write_report(pathlib.Path(args.report), report)
    print(json.dumps({key: report[key] for key in ["source_records", "aggregate_count", "indexed", "failed"]}, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
