import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiops.qq_adapter import AdapterConfig, RecentMessageCache, extract_question, should_accept_event, split_reply


def config(**overrides):
    values = {
        "onebot_api_base": "http://onebot:3000",
        "onebot_access_token": "",
        "onebot_token_in_query": False,
        "event_token": "",
        "aiops_api_base": "http://aiops:8080",
        "aiops_username": "bot",
        "aiops_password": "secret",
        "allowed_groups": {"10001"},
        "trigger_prefixes": ["/故障", "/报修", "/kb"],
        "bot_self_id": "12345",
        "reply_timeout_seconds": 30,
        "max_reply_chars": 1000,
        "startup_notice": False,
    }
    values.update(overrides)
    return AdapterConfig(**values)


def test_extract_question_by_prefix():
    triggered, question = extract_question("/故障 DVB回看黑屏", config())
    assert triggered
    assert question == "DVB回看黑屏"


def test_extract_question_by_at_mention():
    triggered, question = extract_question("[CQ:at,qq=12345] OLT策略导致点播异常", config())
    assert triggered
    assert question == "OLT策略导致点播异常"


def test_extract_question_ignores_plain_group_chat():
    triggered, question = extract_question("今天有故障吗", config())
    assert not triggered
    assert question == ""


def test_should_accept_event_requires_allowed_group_and_trigger():
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 10001,
        "user_id": 20002,
        "self_id": 12345,
        "message_id": 1,
        "raw_message": "/报修 EOC广播风暴",
    }
    accepted, reason = should_accept_event(event, config())
    assert accepted
    assert reason == "accepted"


def test_should_reject_unknown_group():
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 99999,
        "user_id": 20002,
        "raw_message": "/故障 DVB黑屏",
    }
    accepted, reason = should_accept_event(event, config())
    assert not accepted
    assert reason == "group_not_allowed"


def test_recent_message_cache_deduplicates():
    cache = RecentMessageCache(ttl_seconds=60)
    assert not cache.seen_or_add("m1")
    assert cache.seen_or_add("m1")


def test_split_reply_limits_chunk_size():
    chunks = split_reply("abc\n\n" + "x" * 120, 50)
    assert len(chunks) > 1
    assert all(len(item) <= 50 for item in chunks)



def test_extract_question_by_onebot_at_segment():
    cfg = config(bot_self_id="12345", trigger_prefixes=["/kb"])
    message = [
        {"type": "at", "data": {"qq": "12345"}},
        {"type": "text", "data": {"text": " check dvb replay black screen"}},
    ]
    triggered, question = extract_question("", cfg, "12345", message)
    assert triggered
    assert question == "check dvb replay black screen"


def test_rate_limiter_limits_user_without_consuming_extra_group_slot():
    from aiops.qq_adapter import SlidingWindowRateLimiter

    limiter = SlidingWindowRateLimiter(window_seconds=60, user_limit=2, group_limit=10)
    assert limiter.allow("g1", "u1") == (True, "ok")
    assert limiter.allow("g1", "u1") == (True, "ok")
    assert limiter.allow("g1", "u1") == (False, "user_rate_limited")
    assert limiter.allow("g1", "u2") == (True, "ok")


def test_mask_sensitive_text_redacts_tokens():
    from aiops.qq_adapter import mask_sensitive_text

    text = "token=abcdefghijklmnopqrstuvwxyz1234567890 and Bearer abcdefghijklmnopqrstuvwxyz123456"
    masked = mask_sensitive_text(text)
    assert "abcdefghijklmnopqrstuvwxyz1234567890" not in masked
    assert "Bearer abcdefghijklmnopqrstuvwxyz123456" not in masked
    assert "[REDACTED]" in masked
