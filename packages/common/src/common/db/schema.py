from sqlalchemy import text


def ensure_knowledge_schema(engine) -> None:
    statements = [
        "ALTER TABLE topics ADD COLUMN IF NOT EXISTS topic_kind VARCHAR(32) NOT NULL DEFAULT 'entity'",
        "ALTER TABLE topic_proposals ADD COLUMN IF NOT EXISTS proposed_topic_kind VARCHAR(32) NOT NULL DEFAULT 'entity'",
        "ALTER TABLE document_unit_topic_assignments ALTER COLUMN assignment_role TYPE VARCHAR(32)",
        "UPDATE document_unit_topic_assignments SET assignment_role = 'subject' WHERE assignment_role = 'primary'",
        "UPDATE document_unit_topic_assignments SET assignment_role = 'document_family' WHERE assignment_role = 'secondary'",
        """UPDATE topics
        SET topic_kind = CASE topic_class
            WHEN 'financial_period' THEN 'family'
            WHEN 'meeting' THEN 'family'
            WHEN 'general_administration' THEN 'family'
            WHEN 'building_issue' THEN 'issue'
            WHEN 'legal_matter' THEN 'issue'
            WHEN 'case_file' THEN 'project'
            WHEN 'other' THEN 'context'
            ELSE 'entity'
        END
        WHERE topic_kind IS NULL OR topic_kind = 'entity'""",
        """UPDATE topic_proposals
        SET proposed_topic_kind = CASE topic_class
            WHEN 'financial_period' THEN 'family'
            WHEN 'meeting' THEN 'family'
            WHEN 'general_administration' THEN 'family'
            WHEN 'building_issue' THEN 'issue'
            WHEN 'legal_matter' THEN 'issue'
            WHEN 'case_file' THEN 'project'
            WHEN 'other' THEN 'context'
            ELSE 'entity'
        END
        WHERE proposed_topic_kind IS NULL OR proposed_topic_kind = 'entity'""",
        """CREATE TABLE IF NOT EXISTS canonical_entities (
            id UUID PRIMARY KEY,
            entity_type VARCHAR(64) NOT NULL,
            canonical_value VARCHAR(512) NOT NULL,
            display_value VARCHAR(512) NOT NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_canonical_entities_type_value ON canonical_entities(entity_type, canonical_value)",
        """CREATE TABLE IF NOT EXISTS canonical_entity_variants (
            id UUID PRIMARY KEY,
            canonical_entity_id UUID NOT NULL REFERENCES canonical_entities(id) ON DELETE CASCADE,
            entity_type VARCHAR(64) NOT NULL,
            entity_key VARCHAR(512) NOT NULL,
            display_value VARCHAR(512) NOT NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_canonical_entity_variants_type_key ON canonical_entity_variants(entity_type, entity_key)",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
