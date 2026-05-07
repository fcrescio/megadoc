"""Tests for classification service."""

import pytest

from knowledge_classifier.llm.base import ChatMessage, LLMResponse
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.services.classification import ClassificationService


class FailingProvider:
    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.1,
        response_format: dict | None = None,
    ) -> LLMResponse:
        raise RuntimeError("LLM unavailable")

    def chat_with_json(
        self,
        messages: list[ChatMessage],
        schema,
        temperature: float = 0.1,
        max_retries: int = 3,
    ):
        raise RuntimeError("LLM unavailable")

    @property
    def model_name(self) -> str:
        return "failing"

    @property
    def provider_name(self) -> str:
        return "failing"


def test_classification_verbale():
    """Test classification of verbale assemblea."""
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = ClassificationService(llm, MockSession())
    
    text = """VERBALE DI ASSEMBLEA
    
    Condominio Via Roma
    Assemblea Ordinaria del 15 Marzo 2024
    
    Presenti: Rossi Mario, Bianchi Luca
    
    Deliberazioni approvate all'unanimità."""
    
    result = service.classify_document(text)
    
    assert result.primary_type.type_code in ["verbale_assemblea", "altro"]
    assert result.primary_type.confidence > 0


def test_classification_fattura():
    """Test classification of fattura."""
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = ClassificationService(llm, MockSession())
    
    text = """FATTURA N. 2024/001
    
    Ditta Elettrica Srl
    Spett.le Condominio Via Roma
    
    Importo: €1.250,00
    Scadenza: 31/01/2024"""
    
    result = service.classify_document(text)
    
    assert result.primary_type.type_code in ["fattura", "altro"]
    assert result.primary_type.confidence > 0


def test_classification_bolletta():
    """Test classification of bolletta."""
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = ClassificationService(llm, MockSession())
    
    text = """BOLLETTA ACQUA
    
    Azienda Servizi Idrici
    Condominio Via Roma
    
    Periodo: Gennaio - Marzo 2024
    Importo da pagare: €85,50"""
    
    result = service.classify_document(text)
    
    assert result.primary_type.type_code in ["bolletta", "altro"]
    assert result.primary_type.confidence > 0


def test_classification_fails_explicitly_when_llm_fails():
    """Classification must not fabricate a heuristic result when the LLM fails."""
    class MockSession:
        pass
    
    llm = FailingProvider()
    service = ClassificationService(llm, MockSession())
    
    text = "Verbale assemblea ordinaria presenti Rossi Bianchi"

    with pytest.raises(RuntimeError, match="LLM unavailable"):
        service.classify_document(text)
