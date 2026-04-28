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
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
