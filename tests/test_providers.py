"""Provider behavior with a fake HTTP session: retries, fallback, and parsing.
No network calls."""

import json

import pytest

from src.llm import GeminiProvider, LLMError, OllamaProvider, to_openapi_schema
from src.schemas import extraction_schema


class FakeHTTP:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.requests.append({"url": url, "headers": headers or {}, "json": json})
        status, body = self.replies.pop(0)
        return _Resp(status, body)


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return self._body


def ok_body(text, thought=None):
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    return {"candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}],
            "modelVersion": "gemini-3.6-flash", "usageMetadata": {"totalTokenCount": 10}}


def gemini(replies, waits=(15, 30, 60, 120)):
    http = FakeHTTP(replies)
    slept = []
    p = GeminiProvider("test-key", "gemini-3.6-flash", retry_waits=waits, session=http, sleep=slept.append)
    return p, http, slept


def test_busy_responses_are_retried_with_the_benchmark_waits():
    p, http, slept = gemini([(503, "busy"), (503, "busy"), (200, ok_body('{"a": 1}'))])
    r = p.generate_json("check", "s", "u", {"type": "object"})
    assert json.loads(r.text) == {"a": 1}
    assert slept == [15, 30] and r.attempts == 3 and r.waited_seconds == 45


def test_gives_up_after_the_last_wait():
    p, _, slept = gemini([(503, "busy")] * 5)
    with pytest.raises(LLMError, match="HTTP 503"):
        p.generate_json("check", "s", "u", {"type": "object"})
    assert slept == [15, 30, 60, 120]


def quota_429(quota_id, retry_delay=None):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": quota_id}]}]
    if retry_delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay})
    return json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                 "message": "You exceeded your current quota.\n* Quota exceeded for metric",
                                 "details": details}})


def test_429_waits_at_least_as_long_as_the_server_asks():
    p, _, slept = gemini([(429, quota_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "37s")),
                          (200, ok_body("{}"))], waits=(5, 10, 20, 40))
    p.generate_json("x", "s", "u", {})
    assert slept == [37.0]


def test_server_retry_delay_is_capped():
    p, _, slept = gemini([(429, quota_429("PerMinute", "600s")), (200, ok_body("{}"))], waits=(5,))
    p.generate_json("x", "s", "u", {})
    assert slept == [90]


def test_daily_quota_fails_fast_without_retrying():
    p, http, slept = gemini([(429, quota_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))])
    with pytest.raises(LLMError, match="daily free-tier quota used up") as exc:
        p.generate_json("x", "s", "u", {})
    assert slept == [] and len(http.requests) == 1
    assert "midnight Pacific" in str(exc.value)


def test_failed_call_reports_attempts_and_waits():
    p, _, _ = gemini([(503, "busy")] * 3, waits=(5, 10))
    with pytest.raises(LLMError) as exc:
        p.generate_json("x", "s", "u", {})
    assert exc.value.attempts == 3 and exc.value.waited_seconds == 15
    assert "HTTP 503 model overloaded" in str(exc.value)


def test_error_message_is_one_short_line():
    p, _, _ = gemini([(429, quota_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"))], waits=())
    with pytest.raises(LLMError) as exc:
        p.generate_json("x", "s", "u", {})
    assert "\n" not in str(exc.value)
    assert "GenerateRequestsPerMinutePerProjectPerModel-FreeTier" in str(exc.value)


def test_http_400_falls_back_to_response_schema_once():
    p, http, _ = gemini([(400, "Unknown field responseJsonSchema"), (200, ok_body("{}"))])
    p.generate_json("extract", "s", "u", extraction_schema())
    cfg1, cfg2 = (r["json"]["generationConfig"] for r in http.requests)
    assert "responseJsonSchema" in cfg1 and "responseSchema" in cfg2
    assert cfg2["responseSchema"]["type"] == "OBJECT"


def test_thought_parts_are_ignored():
    p, _, _ = gemini([(200, ok_body('{"ok": true}', thought="Let me think..."))])
    assert p.generate_json("x", "s", "u", {}).text == '{"ok": true}'


def test_key_is_sent_in_a_header_never_in_the_url():
    p, http, _ = gemini([(200, ok_body("{}"))])
    p.generate_json("x", "s", "u", {})
    assert "test-key" not in http.requests[0]["url"]
    assert http.requests[0]["headers"]["x-goog-api-key"] == "test-key"


def test_missing_key_fails_clearly():
    p = GeminiProvider(None, "gemini-3.6-flash")
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        p.generate_json("x", "s", "u", {})


def test_truncated_answer_is_an_error():
    body = ok_body("{")
    body["candidates"][0]["finishReason"] = "MAX_TOKENS"
    p, _, _ = gemini([(200, body)])
    with pytest.raises(LLMError, match="MAX_TOKENS"):
        p.generate_json("x", "s", "u", {})


def test_openapi_conversion_keeps_enums_and_order():
    s = to_openapi_schema({"type": "object", "properties": {"b": {"type": "string", "enum": ["met"]}, "a": {"type": "integer"}}})
    assert s["propertyOrdering"] == ["b", "a"] and s["properties"]["b"]["enum"] == ["met"]


def test_ollama_sends_schema_and_reads_content():
    http = FakeHTTP([(200, {"message": {"content": '{"x": 1}'}, "model": "qwen3.5:4b", "eval_count": 5})])
    p = OllamaProvider("http://localhost:11434", "qwen3.5:4b", think=False, session=http)
    r = p.generate_json("check", "s", "u", {"type": "object"})
    sent = http.requests[0]["json"]
    assert sent["format"] == {"type": "object"} and sent["think"] is False and sent["stream"] is False
    assert r.text == '{"x": 1}' and r.provider == "ollama"
