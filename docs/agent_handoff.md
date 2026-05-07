# Agent Handoff - Stato Progetto Megadoc

Ultimo aggiornamento: 2026-05-07.

Questo file è il punto di ingresso per una nuova sessione agentica. Lo scopo è dare una mappa operativa del repository, dello stato del prodotto e dei problemi aperti senza dover ricostruire tutta la storia dalla chat.

## Stato Sintetico

Megadoc è passato dalla fase iniziale di ingestione/OCR a una piattaforma self-hosted di document intelligence con knowledge base navigabile, consolidamento human-in-the-loop e primi worker specialistici.

Il sistema oggi supporta:

- upload PDF e bulk ingestion
- storage originale e derivati in MinIO
- job asincroni Celery su Redis
- OCR con backend intercambiabili, attualmente orientato a `dots_native`
- segmentazione PDF in `document_unit`
- classificazione, summary, entità e topic assignment
- topic multipli per documento con ruoli distinti
- proposal e consolidamento guidato dall'utente
- indice entità e canonical entities revisionabili
- specialisti per bollette e rendiconti contabili
- frontend moderno per documenti, OCR, PDF embedded, knowledge, review e manuale commentabile

## Architettura Runtime

Servizi principali in `docker-compose.yml`:

- `api`: FastAPI, endpoint documentali, knowledge, specialisti, manuale e status.
- `frontend`: React/Vite servito da nginx su `localhost:3000`.
- `worker`: worker OCR/ingestion. Usa la coda `${INGESTION_QUEUE_DEFAULT:-ingestion}`.
- `worker_llm_vision`: worker OCR sperimentale con LLM vision, coda `${INGESTION_QUEUE_LLM_VISION:-ingestion_llm_vision}`.
- `knowledge_worker`: pipeline semantica, coda `knowledge`.
- `specialist_utility_worker`: estrazione bollette, coda `${SPECIALIST_QUEUE_UTILITY:-specialist_utility}`.
- `specialist_accounting_worker`: estrazione rendiconti, coda `${SPECIALIST_QUEUE_ACCOUNTING:-specialist_accounting}`.
- `postgres`: sistema di record.
- `redis`: broker Celery e backend risultati.
- `minio`: object storage S3-compatible.
- `migrate` e `mc-init`: bootstrap DB e bucket.

Nota importante: alcuni worker usano `network_mode: host`. Per questo le variabili endpoint possono differire tra API container e worker.

## LLM/OCR Backend

Il server locale di inferenza supporta un solo modello alla volta. Questo vincolo guida l'orchestrazione:

- i job OCR hanno priorità rispetto ai job knowledge;
- la knowledge deve attendere quando ci sono OCR queued/running;
- il batch ideale è: completare OCR con `dots.ocr`, poi passare a Qwen per knowledge.

Configurazione runtime tipica:

```env
OCR_BACKEND=dots_native
OCR_DOTS_NATIVE_MODEL=ggml-org/dots.ocr-GGUF:Q8_0
OCR_DOTS_NATIVE_ENDPOINT=http://host.docker.internal:8080/v1
OCR_WORKER_DOTS_NATIVE_ENDPOINT=http://10.89.0.3:8080/v1

KN_LLM_MODEL=qwen3.6-A3B
KN_LLM_ENDPOINT=http://host.docker.internal:8080/v1
KN_WORKER_LLM_ENDPOINT=http://10.89.0.3:8080/v1
```

Il frontend mostra lo stato backend tramite `GET /system/status`. L'API prova sia endpoint container-friendly sia endpoint host/private e considera utile anche `/health` quando `/v1/models` non è affidabile.

## Pipeline Documentale

Flusso principale:

1. `POST /documents/upload` salva PDF, calcola hash, crea `document` e `document_version`.
2. `POST /jobs/ingest` o `auto_submit=true` crea `ingestion_job`.
3. `worker` esegue preflight e OCR.
4. OCR salva `ocr_results` e asset in MinIO.
5. Dopo OCR riuscito viene creato/riusato uno `scan_unit`.
6. `knowledge_worker` segmenta in `document_unit`, classifica, estrae entità e assegna topic.
7. Il router specialistico crea job per bollette o rendiconti quando rileva documenti adatti.
8. Il frontend consente review, ricerca, consolidamento e navigazione.

## Backend OCR

Backend disponibili:

- `docling`: backend originale, ancora disponibile.
- `dots_native`: backend attuale preferito per OCR via modello specializzato `dots.ocr`.
- `llm_vision`: backend sperimentale multimodale.
- `fake`: backend deterministico per test.

`dots_native` include:

- prompt nativi compatibili con dots.ocr;
- rendering pagina;
- retry HTTP;
- fallback su rotazioni e scale diverse;
- riconoscimento pagine vuote;
- output normalizzato verso lo stesso contratto usato dal resto del sistema.

La logica di orientamento/preflight vive in `packages/common/src/common/processing/`.

## Knowledge Base

Concetti principali:

- `scan_unit`: un OCR result processabile semanticamente.
- `document_unit`: un sottodocumento logico dentro uno scan.
- `document_type`: tipo archivistico/funzionale, per esempio `bolletta`, `verbale_assemblea`, `rendiconto_contabile`.
- `topic`: fascicolo/argomento navigabile.
- `entity`: entità estratta localmente dal documento.
- `canonical_entity`: entità globale revisionabile, con varianti.

Topic e documenti non sono più uno-a-uno. Ogni `document_unit` può avere più assignment con ruoli:

- `subject`
- `document_family`
- `case_or_issue`
- `person_or_org_context`
- `secondary`

Questa scelta serve a modellare casi reali come garanzie, bollette, rendiconti, verbali e pratiche sovrapposte.

## Consolidamento

Il consolidamento attuale lavora su:

- proposal generate dal modello;
- merge e alias di topic;
- review manuale di proposal;
- suggerimenti di merge graph-based;
- canonical entities;
- assegnazioni multiple.

Correzione critica recente: i rendiconti e i riparti non devono essere consolidati dentro topic di assemblea ordinaria/straordinaria. Ora la normalizzazione contabile crea/usa topic famiglia come `Rendiconti Condominiali - <condominio>` e rimuove assignment contabili erroneamente finiti in meeting family.

## Worker Specialistici

### Bollette

`specialist_utility_worker` estrae:

- emittente/fornitore;
- tipo servizio;
- intestatario;
- data emissione;
- scadenza;
- periodo fatturazione;
- importo;
- numero documento;
- POD/PDR/contratto quando presente;
- stato pagamento se inferibile;
- link e riferimenti.

Endpoint principali:

- `POST /knowledge/documents/{document_id}/ensure-specialists`
- `GET /knowledge/specialists/utility-bills`
- `GET /knowledge/specialist-results/{id}/export?format=json|csv`

### Rendiconti Contabili

`specialist_accounting_worker` estrae tabelle e controlli contabili. La parte importante è che, quando disponibile, deve usare le tabelle strutturate di Docling/dell'OCR (`structured_json.tables.table_cells`) e non solo markdown flattenizzato, altrimenti perde nomi dei condomini e può allucinare righe o palazzine.

Endpoint principali:

- `GET /knowledge/specialists/accounting-statements`
- `GET /knowledge/specialist-results/{id}/export?format=json|csv`

## Frontend

Percorsi principali:

- `/documents`: lista documenti, upload status, job status.
- `/documents/{id}` o selezione documento: dettaglio con tab `Info`, `PDF`, `OCR`, `Knowledge`, `Versions`, `Assets`.
- `/knowledge`: ricerca, topic browser, entity index, canonical entities, review proposal, graph consolidation, Utility Lens, Accounting Lens.
- `/upload`: caricamento PDF.
- `/manual`: manuale di sistema servito dal backend e commentabile con selezione testo.

Il PDF embedded deve usare visualizzazione inline; se il browser scarica il PDF, controllare header `Content-Disposition` e proxy nginx.

## File Da Leggere Per Orientarsi

- `README.md`: panoramica aggiornata.
- `docs/system_manual.md`: manuale prodotto/architettura, servito dal frontend.
- `docs/api.md`: reference HTTP.
- `PLAN.txt`: piano iniziale OCR e stato di completamento.
- `PLAN-segmentation.txt`: piano knowledge e stato di completamento.
- `docker-compose.yml`: topologia runtime.
- `packages/common/src/common/db/models.py`: modello dati principale.
- `packages/common/src/common/application/knowledge.py`: pipeline knowledge e consolidamento.
- `packages/common/src/common/application/specialists.py`: routing specialistico.
- `packages/common/src/common/processing/dots_native.py`: backend OCR dots.
- `services/api/src/api/main.py`: endpoint base, manuale, status.
- `services/api/src/api/routers/knowledge.py`: endpoint knowledge/specialist/consolidamento.
- `services/frontend/src/components/KnowledgeBase.tsx`: UI knowledge.
- `services/frontend/src/components/DocumentDetail.tsx`: UI documento.

## Problemi Aperti Noti

- Il backend LLM è single-model: non avviare simultaneamente batch OCR dots e knowledge Qwen aspettandosi parallelismo reale.
- È stato osservato un deadlock PostgreSQL su rerun knowledge/consolidation di documenti contabili complessi. Serve retry transactionale più robusto e isolamento migliore tra knowledge e consolidation.
- Il routing specialistico può ancora produrre falsi positivi su scansioni miste. Va raffinato usando segnali di `document_type`, entità e layout.
- La canonicalizzazione globale delle entità è utile ma ancora acerba: alias, omonimie e merge richiedono più governance.
- Alcune estensioni schema vengono ancora applicate via bootstrap SQL applicativo oltre che via Alembic. Da stabilizzare con migration versionate.
- La qualità OCR su scansioni difficili resta il maggiore determinante della qualità knowledge.

## Prossimi 5 Passi Suggeriti

1. Rendere robusto il rerun knowledge: retry su deadlock, locking esplicito per scan/document unit, e separazione temporale tra consolidamento automatico e rielaborazione documento.
2. Raffinare il router specialistico: regole miste LLM+euristiche, confidenza esposta in UI, possibilità di forzare manualmente uno specialista.
3. Portare entità canoniche e topic nello stesso grafo operativo: usare canonical entities per suggerire topic, merge e relazioni.
4. Migliorare la validazione dei rendiconti: controlli su somme di riga/colonna, importi negativi, quote millesimali e incongruenze.
5. Migliorare osservabilità: tempi per fase, token/sec backend, code Celery, failure rate per OCR backend, warning visibili in frontend.

## Comandi Utili

Avvio stack:

```bash
docker compose --env-file .env up --build
```

Build frontend:

```bash
npm --prefix services/frontend run build
```

Test Python leggeri:

```bash
python3 -m pytest
```

Controllo stato git:

```bash
git status --short
git log --oneline -n 20
```

## Regola Operativa Per Il Prossimo Agente

Non assumere che un documento sia monolitico. Non assumere che un topic sia esclusivo. Non assumere che un fallback silenzioso sia accettabile. Ogni risultato deve restare navigabile, revisionabile e riconducibile al PDF originale.
