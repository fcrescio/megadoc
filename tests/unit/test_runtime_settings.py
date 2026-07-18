from common.application.runtime_settings import load_runtime_settings, resolve_runtime_settings


def test_runtime_settings_api_persists_effective_values(client, db_session):
    initial = client.get("/settings/runtime")
    assert initial.status_code == 200
    values = initial.json()["values"]
    values["llm_endpoint"] = "http://host.docker.internal:9090/v1"
    values["llm_model"] = "test-chat-model"

    saved = client.put("/settings/runtime", json=values)

    assert saved.status_code == 200
    assert saved.json()["values"]["llm_model"] == "test-chat-model"
    assert "llm_model" in saved.json()["overridden_keys"]
    assert load_runtime_settings(db_session)["llm_endpoint"].endswith(":9090/v1")
    assert resolve_runtime_settings(db_session, {"llm_model": "environment"})["llm_model"] == "test-chat-model"


def test_runtime_settings_api_rejects_non_url_endpoint(client):
    values = client.get("/settings/runtime").json()["values"]
    values["embedding_endpoint"] = "localhost:8080/v1"

    response = client.put("/settings/runtime", json=values)

    assert response.status_code == 422
    assert "embedding_endpoint" in response.text
