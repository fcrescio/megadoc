# megadoc

`megadoc` è una piattaforma self-hosted di document intelligence per PDF reali: upload, storage versionato, OCR strutturato, segmentazione in documenti logici, knowledge base navigabile, review umana, consolidamento e primi worker specialistici.

Il progetto è nato come pipeline OCR, ma lo stato attuale è più ampio: il PDF originale resta preservato, mentre OCR, knowledge, topic, entità e risultati specialistici vengono aggiunti come strati separati e revisionabili.

## Stato Attuale

Funzionalità implementate:

- upload PDF via API, CLI e frontend;
- versioning tramite `external_id` e deduplica opzionale per hash;
- storage originale e derivati in MinIO;
- job asincroni Celery su Redis;
- OCR con backend intercambiabili (`docling`, `dots_native`, `llm_vision`, `fake`);
- preflight, orientamento e fallback OCR;
- segmentazione `scan_unit -> document_unit`;
- classificazione, summary, entità e topic assignment;
- topic multipli per documento con ruoli distinti;
- proposal, merge, alias e consolidamento graph-based;
- indice entità e canonical entities revisionabili;
- specialisti per bollette e rendiconti contabili;
- manuale online commentabile;
- frontend per documenti, PDF embedded, OCR, knowledge, search, topic, entità, review e specialisti;
- stato backend LLM/OCR visibile nel frontend.

## Architettura

- `services/api`: FastAPI. Espone documenti, job, OCR, knowledge, specialisti, manuale e status runtime.
- `services/worker`: Celery worker OCR/ingestion.
- `services/knowledge_worker`: Celery worker per segmentazione, classificazione, topic assignment e consolidamento scan-level.
- `services/specialist_worker`: worker specialistici per bollette e rendiconti.
- `services/frontend`: React/Vite, servito da nginx.
- `services/cli`: CLI Typer per upload, bulk ingestion, submit job e status.
- `services/knowledge_classifier`: README e modulo logico della fase knowledge.
- `packages/common`: dominio, DB models, repository, servizi applicativi, storage, adapter OCR, knowledge e specialisti.
- `docker-compose.yml`: stack completo con `postgres`, `redis`, `minio`, `mc-init`, `migrate`, `api`, `worker`, `worker_llm_vision`, `knowledge_worker`, specialisti e `frontend`.
- rete interna `megadoc-net` per tutto lo stack applicativo; `ml-infra-net` per i servizi che devono parlare con l'infrastruttura ML esterna.

## Struttura Repo Per Nuovi Agenti

- `docs/agent_handoff.md`: stato operativo sintetico per ripartire in una nuova sessione.
- `docs/system_manual.md`: manuale architetturale servito dal frontend.
- `docs/api.md`: reference HTTP aggiornata.
- `PLAN.txt`: piano iniziale OCR con stato di completamento.
- `PLAN-segmentation.txt`: piano knowledge con stato di completamento.
- `docker-compose.yml`: topologia runtime.
- `services/api/src/api/main.py`: endpoint base, manuale, status.
- `services/api/src/api/routers/knowledge.py`: endpoint knowledge, specialisti e consolidamento.
- `services/worker/src/worker/tasks.py`: task OCR.
- `services/knowledge_worker/src/knowledge_worker/tasks.py`: task knowledge.
- `services/specialist_worker/src/specialist_worker/tasks.py`: task specialistici.
- `packages/common/src/common/db/models.py`: modello dati principale.
- `packages/common/src/common/application/knowledge.py`: pipeline knowledge e consolidamento.
- `packages/common/src/common/application/specialists.py`: routing specialistico.
- `packages/common/src/common/processing/dots_native.py`: backend OCR dots.
- `services/frontend/src/components/DocumentDetail.tsx`: pagina documento.
- `services/frontend/src/components/KnowledgeBase.tsx`: pagina knowledge.

## Avvio

1. Copia `.env.example` in `.env`.
2. Avvia lo stack con `docker compose --env-file .env up --build`.
3. Verifica `http://localhost:8080/health` e `http://localhost:8080/ready`.

Il container `mc-init` crea automaticamente i bucket MinIO e `migrate` applica le migration Alembic prima di avviare API e worker.

## Configurazione Runtime

Variabili principali:

- `DATABASE_URL`: connessione PostgreSQL.
- `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`: broker e backend Celery.
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_RAW`, `S3_BUCKET_DERIVATIVES`: object storage MinIO.
- `DEDUPLICATE_BY_HASH`: attiva idempotenza per PDF identici.
- `external_id` nell'upload API o nel comando CLI `upload`: identifica il documento logico da versionare.
- `OCR_BACKEND`: oggi tipicamente `dots_native`; `docling` resta disponibile; `fake` serve per test rapidi.
- `OCR_DOTS_NATIVE_MODEL`: modello OCR dots, tipicamente `ggml-org/dots.ocr-GGUF:Q8_0`.
- `OCR_DOTS_NATIVE_ENDPOINT`: endpoint OpenAI-compatible visto dall'API.
- `OCR_WORKER_DOTS_NATIVE_ENDPOINT`: endpoint OpenAI-compatible visto dal worker OCR.
- `KN_LLM_MODEL`: modello knowledge, oggi tipicamente `qwen3.6-A3B`.
- `KN_LLM_ENDPOINT`: endpoint LLM visto dall'API.
- `KN_WORKER_LLM_ENDPOINT`: endpoint LLM visto dal worker knowledge.
- `STORAGE_BACKEND`: `s3` in compose, `filesystem` nei test.

Nota: il backend locale LLM/OCR carica un solo modello alla volta. La pipeline dà priorità agli OCR rispetto alla knowledge per evitare thrashing tra `dots.ocr` e Qwen.

## Uso API

Upload con auto submit:

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=true" \
  -F "file=@tests/fixtures/sample.pdf;type=application/pdf"
```

Upload versionato dello stesso documento logico:

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=false" \
  -F "external_id=contract-001" \
  -F "file=@tests/fixtures/sample.pdf;type=application/pdf"
```

Submit job esplicito:

```bash
curl -X POST "http://localhost:8080/jobs/ingest" \
  -H "Content-Type: application/json" \
  -d '{"document_id":"<document-id>","priority":5}'
```

Stato job:

```bash
curl "http://localhost:8080/jobs/<job-id>"
```

Ultimo OCR disponibile:

```bash
curl "http://localhost:8080/documents/<document-id>/ocr"
```

Versioni e asset:

```bash
curl "http://localhost:8080/documents/<document-id>/versions"
curl "http://localhost:8080/documents/<document-id>/assets"
```

Download originale e derivati:

```bash
curl -OJ "http://localhost:8080/documents/<document-id>/download"
curl -OJ "http://localhost:8080/documents/<document-id>/assets/<asset-id>/download"
```

## Uso CLI

Upload singolo:

```bash
python -m cli.main upload tests/fixtures/sample.pdf
python -m cli.main upload tests/fixtures/sample.pdf --external-id contract-001
```

Bulk ingestion ricorsiva:

```bash
python -m cli.main bulk /path/cartella --recursive
```

Submit e status:

```bash
python -m cli.main submit-job <document-id>
python -m cli.main status <job-id>
python -m cli.main reprocess <document-id>
```

Per output macchina leggibile, usa `--json-output`.

## Output OCR

Per ogni documento la pipeline salva:

- PDF originale in bucket `raw-documents`
- markdown OCR in `derived-documents/<document_id>/<version_id>/ocr/result.md`
- testo piano in `derived-documents/<document_id>/<version_id>/ocr/result.txt`
- JSON strutturato in `derived-documents/<document_id>/<version_id>/ocr/result.json`
- record relazionali in `documents`, `document_versions`, `ingestion_jobs`, `ocr_results`, `document_assets`
- API per listing di versioni e asset, più download dell'originale e dei derivati

## Knowledge E Specialistici

Dopo OCR riuscito il sistema può creare o riusare uno `scan_unit` e processarlo con la pipeline knowledge:

```bash
curl -X POST "http://localhost:8080/knowledge/documents/<document-id>/ensure"
curl "http://localhost:8080/knowledge/documents/<document-id>"
curl "http://localhost:8080/knowledge/search?q=condominio"
```

Gli specialisti si attivano sui `document_unit` compatibili:

```bash
curl -X POST "http://localhost:8080/knowledge/documents/<document-id>/ensure-specialists"
curl "http://localhost:8080/knowledge/specialists/utility-bills"
curl "http://localhost:8080/knowledge/specialists/accounting-statements"
```

La pagina `http://localhost:3000/knowledge` espone ricerca, topic, proposal, entità, canonical entities, graph consolidation e viste specialistiche.

## Frontend

Percorsi principali:

- `http://localhost:3000/documents`
- `http://localhost:3000/upload`
- `http://localhost:3000/knowledge`
- `http://localhost:3000/manual`

Il frontend mostra anche lo stato del backend LLM/OCR tramite `GET /system/status`.

## Test

Esegui:

```bash
docker compose run --rm --build api sh -lc 'pip install --no-cache-dir ".[dev]" && python -m pytest'
```

I test usano SQLite, storage filesystem e backend OCR `fake` per restare leggeri e riproducibili.

## Tradeoff e Limiti Attuali

- Il backend storico è `Docling`; il backend attuale più promettente per OCR è `dots_native`.
- I test di integrazione non usano il runtime Docling reale per evitare immagini pesanti e tempi lunghi in CI locale; il wiring applicativo resta identico.
- Non sono ancora presenti auth multi-tenant, vector DB o RAG.
- Il consolidamento è volutamente human-in-the-loop: non deve schiacciare topic utili solo per ridurne il numero.
- Il backend LLM/OCR è single-model, quindi l'orchestrazione OCR/knowledge è un vincolo reale.
- Alcune estensioni schema sono ancora bootstrap applicativo oltre ad Alembic; vanno consolidate in migration versionate.
- È stato osservato un deadlock PostgreSQL su rerun knowledge/consolidation di documenti contabili complessi; serve retry/locking più robusto.
- Con `external_id`, un nuovo contenuto crea una nuova `document_version` sullo stesso documento logico; se il contenuto è identico e `DEDUPLICATE_BY_HASH=true`, l'upload viene deduplicato senza creare una nuova versione.
