from urllib.error import URLError

import api.main as api_main


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
