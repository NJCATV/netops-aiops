import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.tools import ai_tools


def test_search_fault_kb_uses_safe_filters_and_compacts(monkeypatch):
    calls = []

    def fake_search_docs(es_url, index, query, limit, sort=None, source=None):
        calls.append({"es_url": es_url, "index": index, "query": query, "limit": limit, "sort": sort, "source": source})
        if index == "topic-index":
            return [
                {
                    "topic_key": "rule:tv:replay_fault",
                    "topic_label": "回看异常",
                    "total_count": 12,
                    "representative_cases": [{"title": "case1"}, {"title": "case2"}, {"title": "case3"}, {"title": "case4"}],
                }
            ]
        return [
            {
                "record_id": "r1",
                "source_type": "formal_fault_report",
                "title": "DVB回看黑屏",
                "fault_content": "a" * 600,
                "fix_method": "b" * 900,
                "knowledge_value": "reference",
            }
        ]

    monkeypatch.setattr(ai_tools, "search_docs", fake_search_docs)

    result = ai_tools.search_fault_kb(
        {
            "query": "DVB回看黑屏",
            "service": "tv",
            "include_low_value": "false",
            "include_noise": "false",
            "es_url": "http://es:9200",
            "formal_index": "formal-index",
            "duty_index": "duty-index",
            "topic_index": "topic-index",
        }
    )

    assert calls[0]["index"] == "formal-index"
    assert calls[1]["index"] == "duty-index"
    assert calls[2]["index"] == "topic-index"
    filters = calls[0]["query"]["bool"]["filter"]
    assert {"term": {"service": "tv"}} in filters
    assert {"terms": {"knowledge_value": ["reference", "aggregate_only"]}} in filters
    assert result["records"][0]["fault_content"] == "a" * 500
    assert result["records"][0]["fix_method"] == "b" * 800
    assert len(result["topics"][0]["representative_cases"]) == 3
