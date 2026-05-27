from types import SimpleNamespace

import specialist_worker.tasks as tasks


def _settings():
    return SimpleNamespace(
        llm_endpoint="http://llm.test/v1",
        llm_model="fixture-model",
        llm_api_key=None,
        llm_timeout=120,
        llm_max_tokens=4096,
    )


def test_accounting_reconciliation_allows_cold_model_start_by_default(monkeypatch):
    monkeypatch.setattr(tasks, "get_knowledge_settings", _settings)
    monkeypatch.delenv("KN_WORKER_LLM_ENDPOINT", raising=False)
    monkeypatch.delenv("SPECIALIST_ACCOUNTING_LLM_RECONCILIATION_TIMEOUT", raising=False)
    monkeypatch.delenv("SPECIALIST_ACCOUNTING_LLM_RECONCILIATION_MAX_TOKENS", raising=False)

    provider = tasks._accounting_reconciliation_provider()

    assert provider is not None
    assert provider.timeout == 240
    assert provider.max_tokens == 4096
    provider.close()


def test_accounting_reconciliation_timeout_override_is_not_capped(monkeypatch):
    monkeypatch.setattr(tasks, "get_knowledge_settings", _settings)
    monkeypatch.delenv("KN_WORKER_LLM_ENDPOINT", raising=False)
    monkeypatch.setenv("SPECIALIST_ACCOUNTING_LLM_RECONCILIATION_TIMEOUT", "360")

    provider = tasks._accounting_reconciliation_provider()

    assert provider is not None
    assert provider.timeout == 360
    provider.close()
