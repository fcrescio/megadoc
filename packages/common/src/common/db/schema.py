from sqlalchemy import text


def ensure_knowledge_schema(engine) -> None:
    statements = [
        "ALTER TABLE topics ADD COLUMN IF NOT EXISTS topic_kind VARCHAR(32) NOT NULL DEFAULT 'entity'",
        "ALTER TABLE topic_proposals ADD COLUMN IF NOT EXISTS proposed_topic_kind VARCHAR(32) NOT NULL DEFAULT 'entity'",
        "ALTER TABLE document_unit_topic_assignments ALTER COLUMN assignment_role TYPE VARCHAR(32)",
        "UPDATE document_unit_topic_assignments SET assignment_role = 'subject' WHERE assignment_role = 'primary'",
        "UPDATE document_unit_topic_assignments SET assignment_role = 'document_family' WHERE assignment_role = 'secondary'",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_document_unit_topic_assignments_unit_topic_role ON document_unit_topic_assignments(document_unit_id, topic_id, assignment_role)",
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
        """CREATE TABLE IF NOT EXISTS knowledge_contexts (
            id UUID PRIMARY KEY,
            context_kind VARCHAR(32) NOT NULL DEFAULT 'entity',
            canonical_entity_id UUID NOT NULL REFERENCES canonical_entities(id) ON DELETE CASCADE,
            label VARCHAR(512) NOT NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NULL,
            CONSTRAINT uq_knowledge_contexts_kind_entity UNIQUE (context_kind, canonical_entity_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_contexts_kind_label ON knowledge_contexts(context_kind, label)",
        """CREATE TABLE IF NOT EXISTS knowledge_context_anchors (
            id UUID PRIMARY KEY,
            context_id UUID NOT NULL REFERENCES knowledge_contexts(id) ON DELETE CASCADE,
            canonical_entity_id UUID NOT NULL REFERENCES canonical_entities(id) ON DELETE CASCADE,
            anchor_role VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_context_anchors_entity UNIQUE (context_id, canonical_entity_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_context_anchors_entity ON knowledge_context_anchors(canonical_entity_id)",
        """CREATE TABLE IF NOT EXISTS knowledge_context_memberships (
            id UUID PRIMARY KEY,
            context_id UUID NOT NULL REFERENCES knowledge_contexts(id) ON DELETE CASCADE,
            document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            membership_role VARCHAR(32) NOT NULL,
            confidence DOUBLE PRECISION NULL,
            source_type VARCHAR(32) NOT NULL,
            evidence_json JSON NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_context_memberships_unit UNIQUE (context_id, document_unit_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_context_memberships_unit ON knowledge_context_memberships(document_unit_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_context_memberships_context_role ON knowledge_context_memberships(context_id, membership_role)",
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
        """CREATE TABLE IF NOT EXISTS knowledge_nodes (
            id UUID PRIMARY KEY,
            node_kind VARCHAR(32) NOT NULL,
            canonical_key VARCHAR(512) NOT NULL,
            label VARCHAR(512) NOT NULL,
            description TEXT NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NULL,
            CONSTRAINT uq_knowledge_nodes_kind_key UNIQUE (node_kind, canonical_key)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_nodes_kind_label ON knowledge_nodes(node_kind, label)",
        """CREATE TABLE IF NOT EXISTS knowledge_node_aliases (
            id UUID PRIMARY KEY,
            node_id UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            alias VARCHAR(512) NOT NULL,
            normalized_alias VARCHAR(512) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_node_aliases_node_alias UNIQUE (node_id, normalized_alias)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_node_aliases_normalized ON knowledge_node_aliases(normalized_alias)",
        """CREATE TABLE IF NOT EXISTS knowledge_predicates (
            code VARCHAR(64) PRIMARY KEY,
            label VARCHAR(255) NOT NULL,
            value_kind VARCHAR(32) NOT NULL,
            description TEXT NULL,
            is_facetable BOOLEAN NOT NULL DEFAULT true,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS document_unit_mentions (
            id UUID PRIMARY KEY,
            document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            node_id UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            mention_role VARCHAR(32) NOT NULL DEFAULT 'mentioned',
            source_type VARCHAR(32) NOT NULL DEFAULT 'entity',
            surface_text VARCHAR(512) NOT NULL,
            confidence DOUBLE PRECISION NULL,
            page_from INTEGER NULL,
            page_to INTEGER NULL,
            evidence_json JSON NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_document_unit_mentions_unit ON document_unit_mentions(document_unit_id)",
        "CREATE INDEX IF NOT EXISTS ix_document_unit_mentions_node ON document_unit_mentions(node_id)",
        """CREATE TABLE IF NOT EXISTS knowledge_assertions (
            id UUID PRIMARY KEY,
            document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            predicate_code VARCHAR(64) NOT NULL REFERENCES knowledge_predicates(code) ON DELETE RESTRICT,
            subject_node_id UUID NULL REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
            object_node_id UUID NULL REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
            value_json JSON NULL,
            value_text VARCHAR(1024) NULL,
            confidence DOUBLE PRECISION NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            source_type VARCHAR(32) NOT NULL,
            specialist_result_id UUID NULL REFERENCES specialist_results(id) ON DELETE SET NULL,
            evidence_json JSON NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_assertions_unit_predicate ON knowledge_assertions(document_unit_id, predicate_code)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_assertions_subject_predicate ON knowledge_assertions(subject_node_id, predicate_code)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_assertions_object_predicate ON knowledge_assertions(object_node_id, predicate_code)",
        """CREATE TABLE IF NOT EXISTS accounting_accounts (
            id UUID PRIMARY KEY,
            scope_node_id UUID NULL REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
            scope_key VARCHAR(512) NOT NULL,
            account_key VARCHAR(512) NOT NULL,
            unit_code VARCHAR(64) NULL,
            subject_label VARCHAR(512) NOT NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NULL,
            CONSTRAINT uq_accounting_accounts_scope_key UNIQUE (scope_key, account_key)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_accounting_accounts_label_unit ON accounting_accounts(subject_label, unit_code)",
        """CREATE TABLE IF NOT EXISTS accounting_account_aliases (
            id UUID PRIMARY KEY,
            account_id UUID NOT NULL REFERENCES accounting_accounts(id) ON DELETE CASCADE,
            alias VARCHAR(512) NOT NULL,
            normalized_alias VARCHAR(512) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_accounting_account_aliases_account_alias UNIQUE (account_id, normalized_alias)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_accounting_account_aliases_normalized ON accounting_account_aliases(normalized_alias)",
        """CREATE TABLE IF NOT EXISTS accounting_facts (
            id UUID PRIMARY KEY,
            document_unit_id UUID NOT NULL REFERENCES document_units(id) ON DELETE CASCADE,
            specialist_result_id UUID NULL REFERENCES specialist_results(id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES accounting_accounts(id) ON DELETE CASCADE,
            accounting_role VARCHAR(64) NULL,
            fact_type VARCHAR(64) NOT NULL,
            category_key VARCHAR(512) NULL,
            category_label VARCHAR(512) NULL,
            amount NUMERIC(14, 2) NOT NULL,
            raw_amount NUMERIC(14, 2) NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
            period_context_from DATE NULL,
            period_context_to DATE NULL,
            period_source VARCHAR(32) NULL,
            period_review_status VARCHAR(32) NULL,
            is_total BOOLEAN NOT NULL DEFAULT false,
            confidence DOUBLE PRECISION NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'auto',
            evidence_json JSON NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "ALTER TABLE accounting_facts ADD COLUMN IF NOT EXISTS accounting_role VARCHAR(64) NULL",
        "CREATE INDEX IF NOT EXISTS ix_accounting_facts_account_type ON accounting_facts(account_id, fact_type)",
        "CREATE INDEX IF NOT EXISTS ix_accounting_facts_unit_type ON accounting_facts(document_unit_id, fact_type)",
        "CREATE INDEX IF NOT EXISTS ix_accounting_facts_category ON accounting_facts(category_key)",
        """DO $$
        BEGIN
            IF to_regclass('public.specialist_results') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'knowledge_assertions'::regclass
                     AND confrelid = 'specialist_results'::regclass
               )
            THEN
                ALTER TABLE knowledge_assertions
                ADD CONSTRAINT fk_knowledge_assertions_specialist_result
                FOREIGN KEY (specialist_result_id) REFERENCES specialist_results(id) ON DELETE SET NULL;
            END IF;
        END $$""",
        "ALTER TABLE document_units ADD COLUMN IF NOT EXISTS archive_identity_json JSON NULL",
        "ALTER TABLE topic_proposals ADD COLUMN IF NOT EXISTS review_payload_json JSON NULL",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
