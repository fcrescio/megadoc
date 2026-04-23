"""Tests for the OpenAI-compatible provider."""

import httpx
from pydantic import BaseModel

from knowledge_classifier.llm.base import ChatMessage
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider


class TestSchema(BaseModel):
    ok: bool
    kind: str


def test_chat_with_json_accepts_nested_usage_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5-27B",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"ok": true, "kind": "nested_usage"}',
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "total_tokens": 17,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(base_url="http://test/v1", model="qwen3.5-27B")
    provider._client = httpx.Client(transport=transport, base_url="http://test/v1")

    parsed, raw = provider.chat_with_json(
        [ChatMessage(role="user", content="Return JSON")],
        TestSchema,
    )

    assert parsed.ok is True
    assert parsed.kind == "nested_usage"
    assert "nested_usage" in raw


def test_chat_with_json_retries_without_response_format_after_server_error():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        calls.append({"body": payload})
        if len(calls) == 1:
            return httpx.Response(500, json={"error": {"message": "template failure"}})
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5-27B",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '```json\n{"ok": true, "kind": "retry"}\n```',
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(base_url="http://test/v1", model="qwen3.5-27B")
    provider._client = httpx.Client(transport=transport, base_url="http://test/v1")

    parsed, _ = provider.chat_with_json(
        [
            ChatMessage(role="system", content="You are a classifier."),
            ChatMessage(role="user", content="Return JSON"),
        ],
        TestSchema,
        max_retries=2,
    )

    assert parsed.kind == "retry"
    assert len(calls) == 2
    assert '"response_format"' in calls[0]["body"]
    assert '"response_format"' not in calls[1]["body"]


def test_chat_includes_max_tokens_by_default():
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        import json

        seen_payloads.append(json.loads(payload))
        return httpx.Response(
            200,
            json={
                "model": "qwen3.6-A3B",
                "choices": [{"message": {"role": "assistant", "content": "OK"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(base_url="http://test/v1", model="qwen3.6-A3B")
    provider._client = httpx.Client(transport=transport, base_url="http://test/v1")

    provider.chat([ChatMessage(role="user", content="Say OK")])

    assert seen_payloads[0]["max_tokens"] == 4096


def test_chat_can_disable_max_tokens_for_compatibility():
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        import json

        seen_payloads.append(json.loads(payload))
        return httpx.Response(
            200,
            json={
                "model": "qwen3.6-A3B",
                "choices": [{"message": {"role": "assistant", "content": "OK"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(
        base_url="http://test/v1",
        model="qwen3.6-A3B",
        max_tokens=None,
    )
    provider._client = httpx.Client(transport=transport, base_url="http://test/v1")

    provider.chat([ChatMessage(role="user", content="Say OK")])

    assert "max_tokens" not in seen_payloads[0]
