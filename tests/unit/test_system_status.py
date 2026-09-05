import io
import json
from urllib.error import HTTPError, URLError

import pytest

import api.main as api_main


@pytest.mark.parametrize("catalog", [None, {}, {"data": "invalid"}, {"data": [{}]}])
def test_health_alone_does_not_verify_inference_backend(monkeypatch, catalog):
    def urlopen(request, timeout):
        if request.full_url.endswith("/health"):
            return io.BytesIO(b'{"status":"ok"}')
        if catalog is None:
            raise HTTPError(request.full_url, 404, "Not found", {}, None)
        return io.BytesIO(json.dumps(catalog).encode())

    monkeypatch.setattr(api_main, "urlopen", urlopen)
    result = api_main._probe_openai_compatible_backend(
        name="test", endpoint="http://backend/v1", model="chat", api_key=None,
    )
    assert result.status == "degraded"
    assert result.server_reachable is True
    assert result.model_available is None
    assert result.available_models == []


@pytest.mark.parametrize("model,expected", [("chat", "ok"), ("missing", "degraded")])
def test_valid_catalog_is_returned_even_without_health_route(monkeypatch, model, expected):
    def urlopen(request, timeout):
        if request.full_url.endswith("/health"):
            raise HTTPError(request.full_url, 404, "Not found", {}, None)
        return io.BytesIO(b'{"data":[{"id":"embed"},{"id":"chat"}]}')

    monkeypatch.setattr(api_main, "urlopen", urlopen)
    result = api_main._probe_openai_compatible_backend(
        name="test", endpoint="http://backend/v1", model=model, api_key=None,
    )
    assert result.status == expected
    assert result.available_models == ["chat", "embed"]
    assert "Health check failed" not in result.detail


def test_remote_backend_probe_does_not_fallback_to_api_host(monkeypatch):
    requested_urls: list[str] = []

    def failing_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        raise URLError("connection refused")

    monkeypatch.setattr(api_main, "urlopen", failing_urlopen)

    status = api_main._probe_openai_compatible_backend(
        name="knowledge_llm",
        endpoint="http://10.89.0.3:8080/v1",
        model="qwen3.6-A3B",
        api_key=None,
    )

    assert status.status == "error"
    assert status.server_reachable is False
    assert status.endpoint == "http://10.89.0.3:8080/v1"
    assert requested_urls == [
        "http://10.89.0.3:8080/health",
        "http://10.89.0.3:8080/v1/models",
    ]
