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
        """CREATE TABLE IF NOT EXISTS manual_comments (
            id UUID PRIMARY KEY,
            manual_slug VARCHAR(128) NOT NULL,
            selected_text TEXT NOT NULL,
            selection_start INTEGER NULL,
            selection_end INTEGER NULL,
            comment_text TEXT NOT NULL,
            author_name VARCHAR(255) NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'open',
            resolution_note TEXT NULL,
            resolved_by VARCHAR(255) NULL,
            resolved_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "ALTER TABLE manual_comments ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'open'",
        "ALTER TABLE manual_comments ADD COLUMN IF NOT EXISTS resolution_note TEXT NULL",
        "ALTER TABLE manual_comments ADD COLUMN IF NOT EXISTS resolved_by VARCHAR(255) NULL",
        "ALTER TABLE manual_comments ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ NULL",
        "CREATE INDEX IF NOT EXISTS ix_manual_comments_slug_created_at ON manual_comments(manual_slug, created_at)",
        """CREATE TABLE IF NOT EXISTS graph_consolidation_reviews (
            id UUID PRIMARY KEY,
            axis VARCHAR(32) NOT NULL,
            source_topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            target_topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            action VARCHAR(64) NOT NULL,
            note TEXT NULL,
            acted_by VARCHAR(255) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_graph_consolidation_reviews_pair ON graph_consolidation_reviews(axis, source_topic_id, target_topic_id, created_at)",
        """CREATE TABLE IF NOT EXISTS specialist_jobs (
            id UUID PRIMARY KEY,
            document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            specialist_type VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            input_version VARCHAR(128) NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ NULL,
            finished_at TIMESTAMPTZ NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_specialist_jobs_status_created_at ON specialist_jobs(status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_specialist_jobs_unit_type ON specialist_jobs(document_unit_id, specialist_type)",
        """CREATE TABLE IF NOT EXISTS specialist_results (
            id UUID PRIMARY KEY,
            document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            specialist_type VARCHAR(64) NOT NULL,
            schema_version VARCHAR(64) NOT NULL,
            confidence DOUBLE PRECISION NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto_accepted',
            result_json JSON NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_specialist_results_unit_type ON specialist_results(document_unit_id, specialist_type)",
        """CREATE TABLE IF NOT EXISTS document_unit_links (
            id UUID PRIMARY KEY,
            source_document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            target_document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            link_type VARCHAR(64) NOT NULL,
            confidence DOUBLE PRECISION NULL,
            rationale TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_document_unit_links_source_type ON document_unit_links(source_document_unit_id, link_type)",
        "CREATE INDEX IF NOT EXISTS ix_document_unit_links_target_type ON document_unit_links(target_document_unit_id, link_type)",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
