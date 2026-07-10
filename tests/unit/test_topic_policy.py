from api.routers.knowledge import _get_or_create_topic_from_payload
from common.application.topic_policy import assignment_role_for_topic_kind, collection_topic_kind
from common.db.models import Topic
from knowledge_classifier.schemas import TopicCreate


def test_collection_topic_kind_rewrites_entity_by_topic_class():
    assert collection_topic_kind("entity", "vendor_relationship") == "family"
    assert collection_topic_kind(None, "financial_period") == "family"
    assert collection_topic_kind("", "building_issue") == "issue"
    assert collection_topic_kind("project", "vendor_relationship") == "project"
    assert collection_topic_kind("entity", "unknown_class") == "context"


def test_assignment_role_for_collection_topic_kind():
    assert assignment_role_for_topic_kind("family") == "document_family"
    assert assignment_role_for_topic_kind("issue") == "case_or_issue"
    assert assignment_role_for_topic_kind("project") == "case_or_issue"
    assert assignment_role_for_topic_kind("context") == "person_or_org_context"
    assert assignment_role_for_topic_kind("entity") == "secondary"


def test_api_create_topic_payload_normalizes_entity_to_collection(db_session):
    payload = TopicCreate(
        slug="acque-spa",
        title="Acque S.p.A.",
        topic_class="vendor_relationship",
        topic_kind="entity",
    )

    topic = _get_or_create_topic_from_payload(payload, db_session)
    db_session.flush()

    assert topic.topic_kind == "family"
    assert db_session.query(Topic).filter_by(slug="acque-spa").one().topic_kind == "family"
