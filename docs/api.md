# API Reference

Questa documentazione descrive l'API HTTP effettivamente implementata nel progetto allo stato attuale.
Non documenta funzionalità future non ancora presenti nel codice.

Base URL tipica in locale:

```text
http://localhost:8080
```

## Panoramica

L'API espone la prima fase della pipeline documentale:

- upload di PDF
- versioning logico dei documenti tramite `external_id`
- creazione e monitoraggio di job OCR asincroni
- recupero del risultato OCR più recente
- listing e download di versioni e asset generati
- health e readiness checks

## Convenzioni

- Gli identificatori sono UUID.
- Le risposte JSON usano il formato serializzato di FastAPI/Pydantic.
- Gli upload usano `multipart/form-data`.
- L'API aggiunge sempre l'header `x-request-id` in risposta.
- Non è presente autenticazione applicativa in questa fase.

## Modello Concettuale

- `document`: identità logica del documento
- `document_version`: singolo binario associato a quel documento
- `ingestion_job`: job asincrono di processing OCR/layout
- `ocr_result`: risultato OCR persistito per una specifica versione
- `document_asset`: artefatto persistito associato al documento

Tipi di asset oggi usati:

- `original_pdf`
- `markdown`
- `text`
- `ocr_json`

## Versioning Logico

Il comportamento dipende da come viene fatto l'upload:

- Senza `external_id`:
  - il sistema tratta il file come nuovo documento logico
  - se `DEDUPLICATE_BY_HASH=true` e l'hash è già presente, il documento esistente viene riusato
- Con `external_id`:
  - il sistema cerca il documento logico esistente con quel valore
  - se il contenuto è diverso, crea una nuova `document_version`
  - se il contenuto è identico e `DEDUPLICATE_BY_HASH=true`, non crea una nuova versione

## Endpoint

### `GET /health`

Liveness check minimale dell'applicazione.

Response `200`:

```json
{
  "status": "ok"
}
```

### `GET /ready`

Readiness check su database, Redis e storage.

Response `200`:

```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok",
  "storage": "ok"
}
```

Valori possibili:

- `status`: `ok` oppure `degraded`
- `database`, `redis`, `storage`: `ok` oppure `error`

Nota:

- oggi l'endpoint restituisce `200` anche quando `status=degraded`

### `POST /documents/upload`

Upload di un PDF con creazione del documento e della versione corrente.

Query params:

- `auto_submit`: opzionale, boolean, default `true`

Campi `multipart/form-data`:

- `file`: obbligatorio, PDF
- `external_id`: opzionale, stringa identificativa del documento logico

Validazioni:

- `file.content_type` deve essere `application/pdf` oppure `application/octet-stream`
- il file viene validato anche via magic bytes PDF
- il file non deve superare `MAX_UPLOAD_SIZE_BYTES`

Esempio:

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=true" \
  -F "file=@sample.pdf;type=application/pdf"
```

Esempio con versioning logico:

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=false" \
  -F "external_id=contract-001" \
  -F "file=@sample.pdf;type=application/pdf"
```

Response `200`:

```json
{
  "document_id": "uuid",
  "version_id": "uuid",
  "status": "queued",
  "deduplicated": false,
  "job_id": "uuid",
  "sha256": "hex",
  "size_bytes": 123456
}
```

Significato dei campi:

- `document_id`: UUID del documento logico
- `version_id`: UUID della versione creata o riusata
- `status`:
  - `stored` se `auto_submit=false`
  - tipicamente `queued` se `auto_submit=true`
- `deduplicated`: `true` se il contenuto è stato riusato senza nuova versione
- `job_id`: presente se `auto_submit=true`
- `sha256`: hash SHA-256 del contenuto
- `size_bytes`: dimensione del file in byte

Errori:

- `400`: PDF invalido oppure file troppo grande
- `415`: content type non supportato

### `POST /jobs/ingest`

Crea o riusa un job di ingestione OCR per un documento.

Content-Type:

```text
application/json
```

Body:

```json
{
  "document_id": "uuid",
  "priority": 5
}
```

Note:

- `priority` è opzionale, default `5`
- se esiste già un job attivo (`queued` o `running`) per quel documento, viene riusato
- dopo la creazione il job viene dispatchato al worker

Response `200`:

```json
{
  "id": "uuid",
  "document_id": "uuid",
  "job_type": "ingest",
  "status": "queued",
  "priority": 5,
  "attempt_count": 0,
  "error_message": null,
  "created_at": "timestamp",
  "started_at": null,
  "finished_at": null
}
```

Errori:

- `404`: documento non trovato

### `GET /jobs`

Lista dei job più recenti.

Query params:

- `limit`: opzionale, integer, default `100`, massimo `500`

Response `200`:

```json
[
  {
    "id": "uuid",
    "document_id": "uuid",
    "job_type": "ingest",
    "status": "queued",
    "priority": 5,
    "attempt_count": 0,
    "error_message": null,
    "created_at": "timestamp",
    "started_at": null,
    "finished_at": null
  }
]
```

Ordinamento:

- `created_at` decrescente

### `GET /jobs/{job_id}`

Dettaglio di un job.

Path params:

- `job_id`: UUID

Response `200`:

```json
{
  "id": "uuid",
  "document_id": "uuid",
  "job_type": "ingest",
  "status": "running",
  "priority": 5,
  "attempt_count": 1,
  "error_message": null,
  "created_at": "timestamp",
  "started_at": "timestamp",
  "finished_at": null
}
```

Errori:

- `404`: job non trovato

### `GET /documents`

Lista dei documenti più recenti.

Query params:

- `limit`: opzionale, integer, default `100`, massimo `500`

Response `200`:

```json
[
  {
    "id": "uuid",
    "external_id": "string|null",
    "original_filename": "sample.pdf",
    "mime_type": "application/pdf",
    "sha256": "hex",
    "size_bytes": 123456,
    "source_type": "api",
    "created_at": "timestamp"
  }
]
```

Nota importante:

- i campi del documento rappresentano lo stato corrente del documento logico
- quando una nuova versione viene caricata tramite `external_id`, metadati come `original_filename`, `sha256`, `size_bytes` e `source_type` vengono aggiornati all'ultima versione

### `GET /documents/{document_id}`

Dettaglio di un documento logico.

Path params:

- `document_id`: UUID

Response `200`:

```json
{
  "id": "uuid",
  "external_id": "contract-001",
  "original_filename": "sample-v2.pdf",
  "mime_type": "application/pdf",
  "sha256": "hex",
  "size_bytes": 123456,
  "source_type": "api",
  "created_at": "timestamp"
}
```

Errori:

- `404`: documento non trovato

### `GET /documents/{document_id}/versions`

Lista delle versioni del documento.

Path params:

- `document_id`: UUID

Response `200`:

```json
[
  {
    "id": "uuid",
    "document_id": "uuid",
    "version_number": 2,
    "storage_bucket": "raw-documents",
    "storage_object_key": "document-id/v2/original.pdf",
    "created_at": "timestamp"
  }
]
```

Ordinamento:

- `version_number` decrescente

Errori:

- `404`: documento non trovato

### `GET /documents/{document_id}/assets`

Lista degli asset associati al documento.

Path params:

- `document_id`: UUID

Response `200`:

```json
[
  {
    "id": "uuid",
    "document_id": "uuid",
    "asset_type": "ocr_json",
    "storage_bucket": "derived-documents",
    "storage_object_key": "document-id/version-id/ocr/result.json",
    "content_type": "application/json",
    "created_at": "timestamp"
  }
]
```

Note:

- gli asset sono legati al documento logico
- oggi non esiste un filtro diretto per versione
- la versione va dedotta dallo `storage_object_key`

Ordinamento:

- `created_at` decrescente

Errori:

- `404`: documento non trovato

### `GET /documents/{document_id}/ocr`

Restituisce l'ultimo risultato OCR disponibile per quel documento.

Path params:

- `document_id`: UUID

Response `200`:

```json
{
  "id": "uuid",
  "document_id": "uuid",
  "document_version_id": "uuid",
  "engine_name": "docling",
  "engine_version": "2.90.0",
  "pipeline_version": "v1",
  "status": "succeeded",
  "full_text": "...",
  "markdown_text": "...",
  "structured_json": {},
  "page_count": 14,
  "confidence_summary": null,
  "created_at": "timestamp"
}
```

Note:

- `document_version_id` indica la versione a cui appartiene il risultato
- `structured_json` contiene il payload strutturato esportato dal backend OCR

Errori:

- `404`: nessun OCR disponibile

### `GET /documents/{document_id}/download`

Scarica il PDF originale.

Path params:

- `document_id`: UUID

Query params:

- `version_id`: opzionale, UUID

Semantica:

- se `version_id` è assente, viene scaricata l'ultima versione
- se `version_id` è presente, viene scaricata quella specifica

Response `200`:

- body binario del PDF
- `Content-Type`: mime del documento, oggi `application/pdf`
- `Content-Disposition`: attachment con filename basato su `document.original_filename`

Errori:

- `404`: documento non trovato
- `404`: versione non trovata o non appartenente al documento

Nota:

- il filename di risposta usa il nome corrente del documento logico, non un nome storico per versione

### `GET /documents/{document_id}/assets/{asset_id}/download`

Scarica un asset associato al documento.

Path params:

- `document_id`: UUID
- `asset_id`: UUID

Response `200`:

- body binario dell'asset
- `Content-Type`: uguale a `asset.content_type`
- `Content-Disposition`: attachment con filename ricavato dall'ultimo segmento di `storage_object_key`

Errori:

- `404`: documento non trovato
- `404`: asset non trovato o non appartenente al documento

## Stati

### Stati Job

- `queued`
- `running`
- `succeeded`
- `failed`

### Risultato OCR

Attualmente l'API espone il risultato OCR riuscito più recente.
I fallimenti vengono riflessi nello stato del job, non in un endpoint separato di OCR failures.

## Esempi di Workflow

### 1. Upload con OCR immediato

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=true" \
  -F "file=@sample.pdf;type=application/pdf"
```

Poi:

```bash
curl "http://localhost:8080/jobs/<job-id>"
curl "http://localhost:8080/documents/<document-id>/ocr"
```

### 2. Upload e job esplicito

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=false" \
  -F "file=@sample.pdf;type=application/pdf"

curl -X POST "http://localhost:8080/jobs/ingest" \
  -H "Content-Type: application/json" \
  -d '{"document_id":"<document-id>","priority":5}'
```

### 3. Versioning dello stesso documento logico

```bash
curl -X POST "http://localhost:8080/documents/upload?auto_submit=false" \
  -F "external_id=contract-001" \
  -F "file=@documento-v1.pdf;type=application/pdf"

curl -X POST "http://localhost:8080/documents/upload?auto_submit=false" \
  -F "external_id=contract-001" \
  -F "file=@documento-v2.pdf;type=application/pdf"
```

Poi:

```bash
curl "http://localhost:8080/documents/<document-id>/versions"
```

### 4. Download degli artefatti OCR

```bash
curl "http://localhost:8080/documents/<document-id>/assets"
curl -OJ "http://localhost:8080/documents/<document-id>/assets/<asset-id>/download"
```

## Error Handling

Messaggi oggi presenti nel codice:

- `Only PDF uploads are supported.`
- `Uploaded file is not a valid PDF.`
- `File exceeds configured upload size limit.`
- `Document not found.`
- `Document version not found.`
- `Document asset not found.`
- `Job not found.`
- `OCR result not found.`

## Limiti Attuali

- nessuna autenticazione o autorizzazione
- nessun endpoint di delete o update esplicito
- nessun filtro per asset per versione
- nessun endpoint di listing storico degli OCR results
- nessuna paginazione completa oltre al semplice `limit`
- `GET /ready` restituisce `200` anche in stato degradato
- il download del documento usa il filename corrente del documento logico

## Header di Tracciamento

Ogni risposta include:

```text
x-request-id: <uuid-o-header-propagato>
```

Se il client invia `x-request-id`, il middleware lo propaga.
Altrimenti viene generato automaticamente.

## Estensioni Implementate Dopo La Fase OCR

Le sezioni precedenti descrivono il nucleo documentale. Lo stato attuale include anche knowledge, specialisti, manuale e stato backend.

### `GET /system/status`

Restituisce lo stato operativo del backend applicativo e del server locale LLM/OCR.

Uso:

```bash
curl "http://localhost:8080/system/status"
```

La risposta è usata dal frontend per mostrare un badge di stato. Il probing del server locale non dipende solo da `/v1/models`: se l'endpoint modelli non è affidabile, l'API usa anche segnali come `/health` e la raggiungibilità dell'endpoint configurato.

### `GET /manuals/{manual_slug}`

Serve un manuale markdown con commenti associati.

Manuale disponibile:

- `system`: legge `docs/system_manual.md`

Uso:

```bash
curl "http://localhost:8080/manuals/system"
```

### `POST /manuals/{manual_slug}/comments`

Crea un commento ancorato a una selezione del manuale.

Body tipico:

```json
{
  "quote": "testo selezionato",
  "comment": "nota utente",
  "author": "utente",
  "start_offset": 10,
  "end_offset": 42
}
```

### `PATCH /manuals/{manual_slug}/comments/{comment_id}`

Aggiorna stato o nota di risoluzione di un commento.

Stati supportati:

- `open`
- `resolved`
- `wontfix`

## API Knowledge

Tutti gli endpoint knowledge sono sotto:

```text
/knowledge
```

### Documento Knowledge

```bash
GET  /knowledge/documents/{document_id}
POST /knowledge/documents/{document_id}/ensure
POST /knowledge/documents/{document_id}/ensure-specialists
```

- `GET` restituisce scan unit, document unit, entità, topic assignment, job specialistici e risultati specialistici collegati al documento.
- `ensure` crea o riusa la knowledge per l'ultimo OCR disponibile e mette in coda il job se necessario.
- `ensure-specialists` crea job specialistici per i `document_unit` compatibili.

### Scan Unit E Document Unit

```bash
POST /knowledge/scan-units/from-ocr/{ocr_result_id}
GET  /knowledge/scan-units
GET  /knowledge/scan-units/{scan_unit_id}
GET  /knowledge/scan-units/{scan_unit_id}/document-units
GET  /knowledge/document-units/{document_unit_id}
POST /knowledge/document-units/{document_unit_id}/review
POST /knowledge/document-units/{document_unit_id}/topic-assignments
DELETE /knowledge/document-units/{document_unit_id}/topic-assignments/{assignment_id}
```

Questi endpoint consentono di creare knowledge da OCR, consultare la segmentazione e correggere manualmente titolo, summary, tipo documento, review status e topic assignment.

### Topic

```bash
GET  /knowledge/topics
GET  /knowledge/topics/{topic_id}
POST /knowledge/topics
GET  /knowledge/topic-proposals
POST /knowledge/topic-proposals/{proposal_id}/approve
POST /knowledge/topic-proposals/{proposal_id}/reject
```

`GET /knowledge/topic-proposals` accetta `include_consolidated=true|false`.

L'approvazione può creare un nuovo topic, assegnare un topic esistente, fare merge o aggiungere un assignment secondario in base al payload.

### Search

```bash
GET /knowledge/search?q=<testo>
```

La search cerca in:

- topic e alias;
- document unit e summary;
- filename;
- OCR text/markdown;
- assignment topic.

Parametri comuni:

- `q`
- `include_inactive`
- `topic_kind`
- `topic_class`
- `limit`

### Entità

```bash
GET  /knowledge/entities
GET  /knowledge/entities/detail
GET  /knowledge/canonical-entities
POST /knowledge/canonical-entities/merge
```

`/entities` espone l'indice aggregato delle entità estratte localmente dai documenti.
`/canonical-entities` espone il livello globale revisionabile.

### Consolidamento Graph-Based

```bash
POST /knowledge/consolidate/run-sync
GET  /knowledge/consolidation/suggestions
POST /knowledge/consolidation/review
```

`/consolidation/suggestions` produce merge candidate distinti per asse semantico, per esempio `subject`, `document_family`, `case_or_issue`.

`/consolidation/review` consente all'utente di approvare, rigettare o trasformare suggerimenti in alias/merge.

### Document Types E Knowledge Jobs

```bash
GET  /knowledge/document-types
GET  /knowledge/jobs/{job_id}
POST /knowledge/jobs/{job_id}/run-sync
```

`run-sync` è utile in sviluppo/debug per eseguire direttamente un job knowledge senza attendere il worker.

## API Specialistiche

### Bollette

```bash
GET /knowledge/specialists/utility-bills
```

Filtri principali:

- `q`
- `issuer`
- `payment_status`
- `overdue_only`
- `limit`

Il risultato contiene riepiloghi normalizzati di bollette: fornitore, intestatario, date, importo, scadenza, stato pagamento e riferimenti quando disponibili.

### Rendiconti Contabili

```bash
GET /knowledge/specialists/accounting-statements
```

Filtri principali:

- `q`
- `statement_type`
- `check_status`
- `limit`

Il risultato contiene riepiloghi contabili e diagnostica delle tabelle estratte.

### Export Risultati Specialistici

```bash
GET /knowledge/specialist-results/{result_id}/export?format=json
GET /knowledge/specialist-results/{result_id}/export?format=csv
```

L'export CSV è particolarmente rilevante per i rendiconti, perché consente analisi tabellare esterna.

## Note Operative Correnti

- Il frontend usa gli stessi endpoint tramite proxy `/api/*`.
- La pagina `/knowledge` del frontend non è una API: è l'interfaccia umana per navigare topic, search, entities, proposal e specialisti.
- Il server locale LLM/OCR supporta un solo modello alla volta; la pipeline deve completare prima gli OCR e poi passare alla knowledge quando possibile.
- I fallback OCR non devono essere invisibili all'utente quando il backend principale è indisponibile: lo stato deve emergere da `/system/status` e dal job status.
