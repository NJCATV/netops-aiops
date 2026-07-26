#!/usr/bin/env python3
"""Create the Kibana AIOps cockpit dashboard saved objects."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


KIBANA = "http://127.0.0.1:5601"
HEADERS = {"kbn-xsrf": "true", "Content-Type": "application/json"}


def request(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(KIBANA + path, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc


def create_saved_object(obj_type: str, obj_id: str, attributes: dict, references: list[dict] | None = None) -> dict:
    return request(
        "POST",
        f"/api/saved_objects/{obj_type}/{obj_id}?overwrite=true",
        {"attributes": attributes, "references": references or []},
    )


def markdown_vis(title: str, markdown: str) -> dict:
    vis_state = {
        "title": title,
        "type": "markdown",
        "aggs": [],
        "params": {"markdown": markdown, "openLinksInNewTab": True, "fontSize": 12},
    }
    return {
        "title": title,
        "visState": json.dumps(vis_state, ensure_ascii=False),
        "uiStateJSON": "{}",
        "description": "",
        "version": 1,
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
        },
    }


def vega_vis(title: str, spec: dict) -> dict:
    vis_state = {
        "title": title,
        "type": "vega",
        "aggs": [],
        "params": {"spec": json.dumps(spec, ensure_ascii=False, indent=2)},
    }
    return {
        "title": title,
        "visState": json.dumps(vis_state, ensure_ascii=False),
        "uiStateJSON": "{}",
        "description": "",
        "version": 1,
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
        },
    }


def vega_lite_base(title: str) -> dict:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title,
        "config": {
            "axis": {"labelFontSize": 11, "titleFontSize": 12, "gridColor": "#edf1f7"},
            "legend": {"labelFontSize": 11, "titleFontSize": 12},
            "view": {"stroke": "transparent"},
        },
    }


def build_visualizations() -> list[tuple[str, dict]]:
    overview_md = """## AIOps 运维驾驶舱

把实时告警、Trap、Syslog、值班处置流水和故障知识库放到同一页。实时趋势跟随右上角时间范围；历史知识库面板展示全量沉淀。

建议：看实时态势选 Last 24 hours；看历史经验选 Last 10 years。知识库问答优先使用 `reference` 和 `aggregate_only`，`noise` 默认排除。
"""

    alarm_status_spec = vega_lite_base("告警事件状态分布（全量）")
    alarm_status_spec.update(
        {
            "data": {
                "url": {
                    "index": "jscn-aiops-alarm-events-*",
                    "body": {
                        "size": 0,
                        "aggs": {"status": {"terms": {"field": "event_status", "size": 10}}},
                    },
                },
                "format": {"property": "aggregations.status.buckets"},
            },
            "mark": {"type": "bar", "tooltip": True, "color": "#3b82f6"},
            "encoding": {
                "x": {"field": "key", "type": "nominal", "sort": "-y", "title": "状态"},
                "y": {
                    "field": "doc_count",
                    "type": "quantitative",
                    "title": "事件数",
                    "scale": {"domainMin": 0},
                },
            },
        }
    )

    alarm_trend_spec = vega_lite_base("告警事件趋势")
    alarm_trend_spec.update(
        {
            "data": {
                "url": {
                    "%context%": True,
                    "%timefield%": "@timestamp",
                    "index": "jscn-aiops-alarm-events-*",
                    "body": {
                        "size": 0,
                        "aggs": {
                            "trend": {
                                "date_histogram": {
                                    "field": "@timestamp",
                                    "fixed_interval": "1h",
                                    "min_doc_count": 0,
                                    "extended_bounds": {
                                        "min": {"%timefilter%": "min"},
                                        "max": {"%timefilter%": "max"},
                                    },
                                }
                            }
                        },
                    },
                },
                "format": {"property": "aggregations.trend.buckets"},
            },
            "mark": {"type": "line", "point": False, "tooltip": True, "color": "#ef4444"},
            "encoding": {
                "x": {"field": "key", "type": "temporal", "title": "时间"},
                "y": {
                    "field": "doc_count",
                    "type": "quantitative",
                    "title": "事件数",
                    "scale": {"domainMin": 0},
                },
            },
        }
    )

    trap_trend_spec = vega_lite_base("Trap 接收趋势")
    trap_trend_spec.update(
        {
            "data": {
                "url": {
                    "%context%": True,
                    "%timefield%": "@timestamp",
                    "index": "jscn-aiops-trap-raw-*",
                    "body": {
                        "size": 0,
                        "aggs": {
                            "trend": {
                                "date_histogram": {
                                    "field": "@timestamp",
                                    "fixed_interval": "1h",
                                    "min_doc_count": 0,
                                    "extended_bounds": {
                                        "min": {"%timefilter%": "min"},
                                        "max": {"%timefilter%": "max"},
                                    },
                                }
                            }
                        },
                    },
                },
                "format": {"property": "aggregations.trend.buckets"},
            },
            "mark": {"type": "area", "tooltip": True, "color": "#14b8a6"},
            "encoding": {
                "x": {"field": "key", "type": "temporal", "title": "时间"},
                "y": {
                    "field": "doc_count",
                    "type": "quantitative",
                    "title": "Trap 数",
                    "scale": {"domainMin": 0},
                },
            },
        }
    )

    fault_topics_spec = vega_lite_base("历史故障主题 Top")
    fault_topics_spec.update(
        {
            "data": {
                "url": {
                    "index": "jscn-aiops-fault-topic-aggregates",
                    "body": {
                        "size": 0,
                        "aggs": {
                            "topics": {
                                "terms": {
                                    "field": "topic_label.keyword",
                                    "size": 12,
                                    "order": {"max_count": "desc"},
                                },
                                "aggs": {"max_count": {"max": {"field": "total_count"}}},
                            }
                        },
                    },
                },
                "format": {"property": "aggregations.topics.buckets"},
            },
            "mark": {"type": "bar", "tooltip": True, "color": "#8b5cf6"},
            "encoding": {
                "y": {"field": "key", "type": "nominal", "sort": "-x", "title": "主题"},
                "x": {"field": "max_count.value", "type": "quantitative", "title": "历史记录数"},
            },
        }
    )

    knowledge_value_spec = vega_lite_base("值班流水知识价值分布")
    knowledge_value_spec.update(
        {
            "data": {
                "url": {
                    "index": "jscn-aiops-duty-repair-records-*",
                    "body": {
                        "size": 0,
                        "aggs": {"value": {"terms": {"field": "knowledge_value", "size": 10}}},
                    },
                },
                "format": {"property": "aggregations.value.buckets"},
            },
            "mark": {"type": "arc", "tooltip": True},
            "encoding": {
                "theta": {"field": "doc_count", "type": "quantitative"},
                "color": {"field": "key", "type": "nominal", "title": "价值分级"},
            },
        }
    )

    syslog_family_spec = vega_lite_base("Syslog 事件族 Top（全量）")
    syslog_family_spec.update(
        {
            "data": {
                "url": {
                    "index": "jscn-aiops-syslog-parsed-*",
                    "body": {
                        "size": 0,
                        "aggs": {"family": {"terms": {"field": "event_family.keyword", "size": 10}}},
                    },
                },
                "format": {"property": "aggregations.family.buckets"},
            },
            "mark": {"type": "bar", "tooltip": True, "color": "#f59e0b"},
            "encoding": {
                "y": {"field": "key", "type": "nominal", "sort": "-x", "title": "事件族"},
                "x": {
                    "field": "doc_count",
                    "type": "quantitative",
                    "title": "日志数",
                    "scale": {"domainMin": 0},
                },
            },
        }
    )

    return [
        ("aiops-cockpit-overview", markdown_vis("AIOps驾驶舱说明", overview_md)),
        ("aiops-cockpit-alarm-status", vega_vis("告警事件状态分布（全量）", alarm_status_spec)),
        ("aiops-cockpit-alarm-trend", vega_vis("告警事件趋势", alarm_trend_spec)),
        ("aiops-cockpit-trap-trend", vega_vis("Trap接收趋势", trap_trend_spec)),
        ("aiops-cockpit-fault-topics", vega_vis("历史故障主题Top", fault_topics_spec)),
        ("aiops-cockpit-knowledge-value", vega_vis("值班流水知识价值分布", knowledge_value_spec)),
        ("aiops-cockpit-syslog-family", vega_vis("Syslog事件族Top（全量）", syslog_family_spec)),
    ]


def create_dashboard() -> dict:
    visualizations = build_visualizations()
    for obj_id, attrs in visualizations:
        create_saved_object("visualization", obj_id, attrs)

    layout = [
        ("aiops-cockpit-overview", 0, 0, 48, 5),
        ("aiops-cockpit-alarm-status", 0, 5, 16, 12),
        ("aiops-cockpit-alarm-trend", 16, 5, 32, 12),
        ("aiops-cockpit-trap-trend", 0, 17, 24, 12),
        ("aiops-cockpit-syslog-family", 24, 17, 24, 12),
        ("aiops-cockpit-fault-topics", 0, 29, 30, 16),
        ("aiops-cockpit-knowledge-value", 30, 29, 18, 16),
    ]
    panels: list[dict] = []
    refs: list[dict] = []
    for i, (vis_id, x, y, w, h) in enumerate(layout):
        ref_name = f"panel_{i}"
        panel_index = str(i + 1)
        panels.append(
            {
                "version": "7.17.27",
                "type": "visualization",
                "panelIndex": panel_index,
                "panelRefName": ref_name,
                "gridData": {"x": x, "y": y, "w": w, "h": h, "i": panel_index},
                "embeddableConfig": {},
            }
        )
        refs.append({"name": ref_name, "type": "visualization", "id": vis_id})

    dashboard_attrs = {
        "title": "AIOps 运维驾驶舱",
        "description": "告警事件、Trap、Syslog、故障知识库和值班处置流水的统一总览。",
        "hits": 0,
        "panelsJSON": json.dumps(panels, ensure_ascii=False),
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "hidePanelTitles": False}, ensure_ascii=False),
        "version": 1,
        "timeRestore": False,
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
        },
    }
    create_saved_object("dashboard", "aiops-ops-cockpit", dashboard_attrs, refs)
    return {"ok": True, "dashboard_id": "aiops-ops-cockpit", "visualizations": [item[0] for item in visualizations]}


def main() -> int:
    print(json.dumps(create_dashboard(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
