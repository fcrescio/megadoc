# megadoc

`megadoc` e una pipeline self-hosted di ingestione documentale basata su FastAPI, Celery, PostgreSQL, Redis, MinIO e Docling. La v1 gestisce upload PDF, job asincroni di ingestione, OCR strutturato e persistenza di input e derivati senza dipendenze SaaS.

## Architettura

- `services/api`: API REST per upload, creazione job, stato e recupero risultati.
- `services/worker`: worker Celery che scarica il PDF da MinIO, esegue Docling e salva risultato e derivati.
- `services/cli`: CLI Typer per upload singolo, bulk ingestion, submit job e status.
- `packages/common`: dominio, repository, servizi applicativi, storage backend, security e adapter OCR.
- `docker-compose.yml`: stack completo con `postgres`, `redis`, `minio`, `mc-init`, `migrate`, `api`, `worker`.

## Struttura Repo

- `services/api/src/api/main.py`
- `services/worker/src/worker/tasks.py`
- `services/cli/src/cli/main.py`
- `packages/common/src/common/application/services.py`
- `packages/common/src/common/processing/backends.py`
- `alembic/versions/20260422_0001_initial.py`
- `infra/init/create-buckets.sh`
- `tests/`

## Avvio

1. Copia `.env.example` in `.env`.
2. Avvia lo stack con `docker compose --env-file .env up --build`.
3. Verifica `http://localhost:8080/health` e `http://localhost:8080/ready`.

Il container `mc-init` crea automaticamente i bucket MinIO e `migrate` applica le migration Alembic prima di avviare API e worker.

## Configurazione

Variabili principali:

- `DATABASE_URL`: connessione PostgreSQL.
- `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`: broker e backend Celery.
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_RAW`, `S3_BUCKET_DERIVATIVES`: object storage MinIO.
- `DEDUPLICATE_BY_HASH`: attiva idempotenza per PDF identici.
- `OCR_BACKEND`: `docling` in produzione, `fake` per test rapidi.
- `STORAGE_BACKEND`: `s3` in compose, `filesystem` nei test.

## Uso API

Upload con auto submit:

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=true" \
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

## Uso CLI

Upload singolo:

```bash
python -m cli.main upload tests/fixtures/sample.pdf
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

## Test

Esegui:

```bash
pytest
```

I test usano SQLite, storage filesystem e backend OCR `fake` per restare leggeri e riproducibili.

## Tradeoff e limiti v1

- Il backend principale e `Docling`, ma l’astrazione `DocumentProcessingBackend` permette di aggiungere altri engine senza refactor invasivi.
- I test di integrazione non usano il runtime Docling reale per evitare immagini pesanti e tempi lunghi in CI locale; il wiring applicativo resta identico.
- Non sono ancora presenti auth multi-tenant, vector DB, summarization LLM o orchestration avanzata.
- La policy di deduplica riusa il documento esistente quando `DEDUPLICATE_BY_HASH=true`; non crea una nuova versione per lo stesso contenuto binario.
