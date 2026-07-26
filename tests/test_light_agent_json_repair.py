from aiops.agent.light_agent import safe_json_loads


def test_safe_json_loads_repairs_redundant_root_closure():
    content = '{"metadata":{"ok":true}}, "must_handle":[{"title":"告警"}]}'

    assert safe_json_loads(content) == {
        "metadata": {"ok": True},
        "must_handle": [{"title": "告警"}],
    }


def test_safe_json_loads_does_not_guess_unrelated_invalid_json():
    assert safe_json_loads('{"metadata": invalid}') is None
