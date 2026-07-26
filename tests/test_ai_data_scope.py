from __future__ import annotations

from aiops.context.current_window_summary import SummaryConfig, device_scope_query as summary_scope_query
from aiops.tools.investigation import InvestigationConfig, device_scope_query as investigation_scope_query


def assert_scoped(query: dict) -> None:
    assert query["bool"]["filter"] == [{"match_all": {}}]
    assert query["bool"]["minimum_should_match"] == 1
    assert query["bool"]["should"] == [
        {"terms": {"device_ip": ["10.0.0.7"]}},
        {"terms": {"managed_device_ip": ["10.0.0.7"]}},
    ]


def test_summary_queries_apply_device_scope():
    assert_scoped(summary_scope_query(SummaryConfig(allowed_device_ips=("10.0.0.7",)), {"match_all": {}}))


def test_investigation_queries_apply_device_scope():
    assert_scoped(investigation_scope_query(InvestigationConfig(allowed_device_ips=("10.0.0.7",)), {"match_all": {}}))


def test_empty_device_scope_never_falls_back_to_global():
    assert summary_scope_query(SummaryConfig(allowed_device_ips=()), {"match_all": {}}) == {"match_none": {}}
    assert investigation_scope_query(InvestigationConfig(allowed_device_ips=()), {"match_all": {}}) == {"match_none": {}}


def test_unrestricted_scope_preserves_original_query():
    query = {"term": {"event_type": "BFD_FLAP"}}
    assert summary_scope_query(SummaryConfig(), query) is query
    assert investigation_scope_query(InvestigationConfig(), query) is query
