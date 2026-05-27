from common.db.models import Topic
from knowledge_classifier.schemas import ExtractedEntity
from knowledge_classifier.services.topic_retrieval import TopicRetrievalService


def _service() -> TopicRetrievalService:
    return TopicRetrievalService.__new__(TopicRetrievalService)


def test_score_topic_rejects_conflicting_building_anchor():
    service = _service()
    topic = Topic(
        slug="condominio_via_roma_bilancio_2024",
        title="Condominio Via Roma - Bilancio 2024",
        topic_class="financial_period",
        description="Financial year documents",
    )
    terms = {
        "title_words": set(),
        "summary_words": {"rendiconto", "bilancio"},
        "entity_values": set(),
        "entity_normalized": set(),
        "anchors": [{"studiati"}],
    }

    score, reasons = service._score_topic(topic, "rendiconto_contabile", terms)

    assert score == 0.0
    assert reasons == ["Anchor mismatch: document building/address differs from topic"]


def test_score_topic_keeps_generic_topic_without_address_anchor():
    service = _service()
    topic = Topic(
        slug="assemblea_straordinaria_2024_03_12",
        title="Assemblea Straordinaria 12 Marzo 2024",
        topic_class="meeting",
    )
    terms = {
        "title_words": {"assemblea"},
        "summary_words": set(),
        "entity_values": set(),
        "entity_normalized": set(),
        "anchors": [{"studiati"}],
    }

    score, _ = service._score_topic(topic, "verbale_assemblea", terms)

    assert score > 0


def test_build_search_terms_does_not_use_unrelated_organization_as_building_anchor():
    service = _service()
    terms = service._build_search_terms(
        title=None,
        summary=None,
        entities=[
            ExtractedEntity(
                entity_type="indirizzo",
                entity_value="Via Cesare Studiati 6-10/A, Pisa",
                normalized_value="via_cesare_studiati_6_10a_pisa",
                confidence=0.95,
            ),
            ExtractedEntity(
                entity_type="organizzazione",
                entity_value="Banco BPM",
                normalized_value="banco_bpm",
                confidence=0.95,
            ),
        ],
    )

    assert terms["anchors"] == [{"cesare", "studiati", "pisa"}]
