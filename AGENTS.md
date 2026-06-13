# AGENTS.md

Guidelines for agents and maintainers working on Megadoc.

This project is a document ingestion and knowledge extraction system. Changes should be developed as small, verifiable steps that preserve the raw source document, make derived data inspectable, and keep human review paths available when automated extraction is uncertain.

## Development Strategy

Treat the system as a pipeline, not as a single application. A change is usually safer when it is scoped to one stage and verified at the boundary with the next stage.

Main stages:

- Upload and persistence of original documents.
- OCR and structured extraction.
- Scan unit creation and document segmentation.
- Document type classification and topic assignment.
- Specialist extraction for domains such as accounting and utility bills.
- Projection into facts, contexts, graph entities, and UI views.
- Human review and correction workflows.

Prefer additive metadata and explicit confidence signals over hidden heuristics. If a transformation changes document order, page ranges, table structure, category mapping, or extracted amounts, record enough information for later audit.

Do not optimize only for one sample document. Use real documents as regression fixtures, but express fixes as general rules: document families, table roles, confidence gates, review states, or schema extensions.

## Code Change Principles

Keep raw input immutable. Never overwrite or discard the uploaded document as part of normal processing.

Keep derived data reproducible. If a pipeline stage changes, it should be possible to clear derived tables and re-run ingestion or downstream processing.

Separate concerns:

- OCR code should normalize physical scan issues and emit text/structure with metadata.
- Knowledge classification should decide document units, types, topics, entities, and context.
- Specialist workers should understand domain-specific structures and emit typed results.
- Projection code should convert specialist output into queryable facts.
- UI code should expose navigation, review, and correction without embedding extraction logic.

Use existing patterns before adding abstractions. If a new concept is needed, introduce it with a narrow schema and one concrete consumer.

## Verification Strategy

Use a verification ladder. Do not jump directly from code changes to manual UI inspection.

1. Static/local sanity
   - Check changed files and imports.
   - Run focused unit tests for the touched modules.
   - Run frontend type/build checks when UI or API response types change.

2. Service-level verification
   - Rebuild only the services affected by the change.
   - Confirm required containers are running and healthy.
   - Check queue infrastructure before starting ingestion.
   - For frontend changes, confirm the running container is serving the expected bundle, not only that the source tree contains the patch.

3. Data-level verification
   - Query Postgres directly for document counts, job statuses, scan units, document units, specialist jobs, and specialist results.
   - Inspect representative JSON fields, not only UI summaries.
   - Verify page ranges, document type codes, confidence, review status, and section/table counts.

4. End-to-end verification
   - Reprocess a small set of known documents.
   - Compare expected pipeline boundaries with actual database output.
   - Confirm UI endpoints expose the same structure seen in the database.

5. Regression capture
   - Add or update focused tests for the rule that changed.
   - Prefer deterministic unit tests for heuristics, parsing, classification helpers, projection, and UI type contracts.

## Recommended Commands

Use the project commands where possible:

```bash
npm --prefix services/frontend run build
```

For Python tests, prefer the project/container environment when host dependencies are incomplete:

```bash
docker run --rm --user root -w /app -v "$PWD":/app megadoc-api \
  sh -lc 'pip install --no-cache-dir pytest >/tmp/pip-pytest.log && python -m pytest <tests>'
```

Check service status:

```bash
docker compose ps
```

Rebuild the frontend with an explicit git hash when validating UI changes:

```bash
VITE_GIT_HASH=$(git rev-parse --short HEAD) docker compose up -d --build frontend
```

The frontend Docker build context is `services/frontend`, so it may not contain the repository `.git` directory. Do not rely on `git rev-parse` inside the container build unless the build context is changed deliberately.

Check recent logs for a specific container:

```bash
docker logs --tail 100 <container>
```

Query Postgres:

```bash
docker exec megadoc-postgres-1 psql -U megadoc -d megadoc -P pager=off -c "<sql>"
```

## Database and Reprocessing

Derived tables may be cleared during experiments only when the goal explicitly requires reprocessing. Preserve original documents, versions, and assets unless the task is specifically to reset the whole system.

Before clearing derived data:

- Check current branch and uncommitted changes.
- Record what documents are present.
- Decide whether OCR must be rerun or whether downstream stages can be rerun from existing OCR results.

Prefer rerunning only the necessary stage:

- OCR/preflight/orientation changes require re-ingestion or OCR rerun.
- Segmentation/classification/topic changes can usually reuse existing OCR.
- Specialist extraction changes can usually reuse existing document units.
- Projection/API/UI changes often only require recalculating derived facts or rebuilding services.

## Job and Queue Health

Redis is required for Celery queues. Before starting ingestion, verify that Redis is healthy. A running API with a broken Redis instance can still make the UI look alive while background processing is unable to progress.

If Redis is restarting, check logs first. Do not repair or delete queue persistence automatically unless the user has explicitly authorized it. Queue data can be operationally disposable in development, but the action is still destructive.

Postgres is the source of truth for pipeline state. Verify job status in tables such as:

- `ingestion_jobs`
- `knowledge_jobs`
- `specialist_jobs`
- `ocr_results`
- `scan_units`
- `document_units`
- `specialist_results`

## Document Extraction Rules

Extraction should support both human navigation and LLM querying.

For humans:

- Keep page ranges accurate.
- Group dense outputs into sections.
- Surface confidence and review status.
- Provide exports or raw JSON when useful.

For LLMs:

- Produce normalized facts with stable keys.
- Preserve evidence: document unit, page range, table id, row id, column name, raw value.
- Avoid forcing uncertain data into authoritative facts.
- Mark inferred or reconciled values explicitly.

When tables vary by year, vendor, administrator, or scan quality, prefer a reconciliation workflow over ad hoc parsing exceptions. The system should be able to propose structural corrections, but ambiguous numeric changes must remain reviewable.

## UI Expectations

The UI should be navigable without requiring users to inspect raw JSON first.

Dense data should use:

- Tabs for major modes.
- Section filters for large extraction results.
- Modals or panels for detailed review.
- Local scrolling inside dense panels rather than page-level sprawl.

UI labels should describe the archive concept directly. Avoid generated titles that merely restate similarity or weak clustering unless the user is reviewing proposals.

For review workflows, distinguish clearly between free-text filters and authoritative selections. If an action requires an existing database object, the UI must force selection of an existing id and disable submission until that id is valid. Do not treat typed labels as identifiers.

When a screen can render many proposals, topics, tables, or facts, avoid repeated sorting/filtering inside each row or card. Compute shared ordered lists once in the parent, cap large option lists, and provide local filtering.

## Runtime Verification Notes

After a rebuild or restart, verify the deployed process, not just the build output:

- `docker compose ps <service>` to confirm the service was recreated and is running.
- For frontend changes, inspect the served bundle or visible footer hash and make sure it matches the current commit.
- If the UI still shows an old hash, suspect browser cache, stale container image, or a build arg fallback before debugging the application logic.
- Compose may rebuild dependent images even when targeting one service. Watch the command until it exits and check dependent healthchecks before declaring the UI ready.

## Git Discipline

Use commits as rollback points.

Before making broad changes:

- Check `git status`.
- Identify unrelated local changes and leave them untouched.
- Commit coherent slices with messages that describe behavior, not implementation trivia.

Do not commit generated caches, local state, or private working artifacts.

## Definition of Done

A change is done when:

- The intended behavior is implemented.
- Focused tests or builds have passed.
- Runtime services affected by the change have been rebuilt or the reason for not rebuilding is stated.
- Representative database/API output has been inspected for pipeline changes.
- Remaining risks are known and documented in the final handoff.
