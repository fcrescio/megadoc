-- Fix topic classification and assignment roles
-- Based on analysis: single documents should be 'entity', grouping topics 'family'
-- Mapping: entity→subject, family→document_family, issue→case_or_issue, project→case_or_issue, context→person_or_org_context

BEGIN;

-- ============================================================
-- STEP 1: Fix topic_kind for single-document topics misclassified as 'family'
-- These are fatture, bollette, bollettini, pagamenti, assegni, ricevute, buoni
-- ============================================================

UPDATE topics SET topic_kind = 'entity'
WHERE topic_kind = 'family'
  AND (title ILIKE '%fattura%'
    OR title ILIKE '%bolletta%'
    OR title ILIKE '%bollettino%'
    OR title ILIKE '%pagamento%'
    OR title ILIKE '%assegno%'
    OR title ILIKE '%ricevuta%'
    OR title ILIKE '%buono%');

-- ============================================================
-- STEP 2: Fix topic_kind for single-document topics misclassified as 'project'
-- These are fatture, bollette, preventivi, verbali that are single documents
-- ============================================================

UPDATE topics SET topic_kind = 'entity'
WHERE topic_kind = 'project'
  AND (title ILIKE '%fattura%'
    OR title ILIKE '%bolletta%'
    OR title ILIKE '%preventivo%'
    OR title ILIKE '%verbale%');

-- ============================================================
-- STEP 3: Remove duplicate assignments (same topic_id + same document_unit_id)
-- Keep only the one with the role matching the topic_kind
-- ============================================================

-- For family topics: keep document_family, remove subject
DELETE FROM document_unit_topic_assignments duta
USING topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'family'
  AND duta.assignment_role = 'subject'
  AND EXISTS (
    SELECT 1 FROM document_unit_topic_assignments duta2
    WHERE duta2.topic_id = duta.topic_id
      AND duta2.document_unit_id = duta.document_unit_id
      AND duta2.assignment_role = 'document_family'
  );

-- For entity topics: keep subject, remove document_family
DELETE FROM document_unit_topic_assignments duta
USING topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'entity'
  AND duta.assignment_role = 'document_family'
  AND EXISTS (
    SELECT 1 FROM document_unit_topic_assignments duta2
    WHERE duta2.topic_id = duta.topic_id
      AND duta2.document_unit_id = duta.document_unit_id
      AND duta2.assignment_role = 'subject'
  );

-- For issue topics: keep case_or_issue, remove subject (when duplicate)
DELETE FROM document_unit_topic_assignments duta
USING topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'issue'
  AND duta.assignment_role = 'subject'
  AND EXISTS (
    SELECT 1 FROM document_unit_topic_assignments duta2
    WHERE duta2.topic_id = duta.topic_id
      AND duta2.document_unit_id = duta.document_unit_id
      AND duta2.assignment_role = 'case_or_issue'
  );

-- For project topics: keep case_or_issue, remove subject (when duplicate)
DELETE FROM document_unit_topic_assignments duta
USING topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'project'
  AND duta.assignment_role = 'subject'
  AND EXISTS (
    SELECT 1 FROM document_unit_topic_assignments duta2
    WHERE duta2.topic_id = duta.topic_id
      AND duta2.document_unit_id = duta.document_unit_id
      AND duta2.assignment_role = 'case_or_issue'
  );

-- For context topics: keep person_or_org_context, remove subject (when duplicate)
DELETE FROM document_unit_topic_assignments duta
USING topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'context'
  AND duta.assignment_role = 'subject'
  AND EXISTS (
    SELECT 1 FROM document_unit_topic_assignments duta2
    WHERE duta2.topic_id = duta.topic_id
      AND duta2.document_unit_id = duta.document_unit_id
      AND duta2.assignment_role = 'person_or_org_context'
  );

-- ============================================================
-- STEP 4: Fix remaining non-duplicate assignments with wrong role
-- Only fix clear mismatches. Skip cross-kind assignments that
-- are intentional (e.g., context→document_family).
-- ============================================================

-- entity topics should have subject role
UPDATE document_unit_topic_assignments duta
SET assignment_role = 'subject'
FROM topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'entity'
  AND duta.assignment_role NOT IN ('subject');

-- family topics should have document_family role
UPDATE document_unit_topic_assignments duta
SET assignment_role = 'document_family'
FROM topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'family'
  AND duta.assignment_role NOT IN ('document_family');

-- issue topics should have case_or_issue role
UPDATE document_unit_topic_assignments duta
SET assignment_role = 'case_or_issue'
FROM topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'issue'
  AND duta.assignment_role NOT IN ('case_or_issue');

-- project topics should have case_or_issue role
UPDATE document_unit_topic_assignments duta
SET assignment_role = 'case_or_issue'
FROM topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'project'
  AND duta.assignment_role NOT IN ('case_or_issue');

-- context topics: keep person_or_org_context and document_family as valid
UPDATE document_unit_topic_assignments duta
SET assignment_role = 'person_or_org_context'
FROM topics t
WHERE duta.topic_id = t.id
  AND t.topic_kind = 'context'
  AND duta.assignment_role NOT IN ('person_or_org_context', 'document_family');

COMMIT;
