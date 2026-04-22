"""Tests for classification service."""

import pytest

from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.services.classification import ClassificationService


@pytest.mark.asyncio
async def test_classification_verbale():
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
    
    result = await service.classify_document(text)
    
    assert result.primary_type.type_code in ["verbale_assemblea", "altro"]
    assert result.primary_type.confidence > 0


@pytest.mark.asyncio
async def test_classification_fattura():
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
    
    result = await service.classify_document(text)
    
    assert result.primary_type.type_code in ["fattura", "altro"]
    assert result.primary_type.confidence > 0


@pytest.mark.asyncio
async def test_classification_bolletta():
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
    
    result = await service.classify_document(text)
    
    assert result.primary_type.type_code in ["bolletta", "altro"]
    assert result.primary_type.confidence > 0


@pytest.mark.asyncio
async def test_heuristic_classification():
    """Test heuristic fallback classification."""
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = ClassificationService(llm, MockSession())
    
    # Test with clear keywords
    text = "Verbale assemblea ordinaria presenti Rossi Bianchi"
    result = service._heuristic_classification(text)
    
    assert result.primary_type.type_code == "verbale_assemblea"
    assert result.primary_type.confidence > 0.5
