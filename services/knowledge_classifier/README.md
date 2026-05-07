# Knowledge Classifier Service

Modulo knowledge di Megadoc. Implementa la fase `scan -> document units -> document type -> topic assignment` e le sue estensioni correnti.

## Panoramica

Questo servizio prende in input il risultato OCR di un PDF e:

1. **Segmenta** lo scan in documenti logici distinti
2. **Classifica** ogni documento in un tipo noto
3. **Estrae** entità chiave (condomini, date, importi, etc.)
4. **Assegna** il documento a topic esistenti o propone nuovi topic
5. **Consolida** topic e relazioni con intervento umano
6. **Instrada** document unit compatibili verso worker specialistici

## Concetti Chiave

### Scan Unit
Rappresenta un PDF scansionato (un OCR result). Può contenere uno o più documenti logici.

### Document Unit
Un documento logico estratto da uno scan. Ha:
- Pagine di inizio e fine
- Tipo di documento classificato
- Entità estratte
- Topic assegnati

### Document Type
Tipo archivistico del documento (es: `verbale_assemblea`, `fattura`, `bolletta`).

### Topic
Argomento/fascicolo a cui il documento appartiene (es: `condominio_via_roma_bilancio_2024`).

### Entity
Elementi nominati estratti dal documento (persone, organizzazioni, date, importi).

### Canonical Entity
Entità globale revisionabile che raggruppa varianti locali estratte da documenti diversi.

### Topic Assignment Role
Ruolo semantico dell'assegnazione topic. Un documento può appartenere a più topic con ruoli diversi:

- `subject`
- `document_family`
- `case_or_issue`
- `person_or_org_context`
- `secondary`

## Avvio

```bash
# Avvia tutti i servizi
docker compose up --build

# Avvia solo il knowledge worker
docker compose up knowledge_worker
```

## API Endpoints Principali

### Creare Scan Unit da OCR

```bash
POST /knowledge/scan-units/from-ocr/{ocr_result_id}
Content-Type: application/json

{
  "ocr_result_id": "uuid-del-ocr-result"
}
```

### Listare Scan Units

```bash
GET /knowledge/scan-units
```

### Ottenere Document Units

```bash
GET /knowledge/scan-units/{scan_unit_id}/document-units
```

### Listare Topic

```bash
GET /knowledge/topics
```

### Search Knowledge

```bash
GET /knowledge/search?q=<testo>
```

### Creare Topic

```bash
POST /knowledge/topics
Content-Type: application/json

{
  "slug": "nuovo-topic",
  "title": "Nuovo Topic",
  "topic_class": "case_file",
  "description": "Descrizione"
}
```

### Approvare/Rigettare Topic Proposals

```bash
POST /knowledge/topic-proposals/{proposal_id}/approve
POST /knowledge/topic-proposals/{proposal_id}/reject
```

### Review Document Unit

```bash
POST /knowledge/document-units/{document_unit_id}/review
Content-Type: application/json

{
  "review_status": "human_reviewed",
  "title": "Titolo corretto"
}
```

### Assignment Manuale Topic

```bash
POST /knowledge/document-units/{document_unit_id}/topic-assignments
DELETE /knowledge/document-units/{document_unit_id}/topic-assignments/{assignment_id}
```

### Consolidamento Graph-Based

```bash
GET /knowledge/consolidation/suggestions
POST /knowledge/consolidation/review
```

### Entità

```bash
GET /knowledge/entities
GET /knowledge/entities/detail
GET /knowledge/canonical-entities
POST /knowledge/canonical-entities/merge
```

### Specialisti

```bash
POST /knowledge/documents/{document_id}/ensure-specialists
GET /knowledge/specialists/utility-bills
GET /knowledge/specialists/accounting-statements
GET /knowledge/specialist-results/{result_id}/export?format=json|csv
```

## Configurazione

| Variabile | Descrizione | Default |
|-----------|-------------|---------|
| `KN_LLM_ENDPOINT` | Endpoint LLM API visto dall'API/container standard | `http://10.89.0.3:8080/v1` |
| `KN_WORKER_LLM_ENDPOINT` | Endpoint LLM visto dal worker in host network | `http://10.89.0.3:8080/v1` |
| `KN_LLM_MODEL` | Nome modello LLM | `qwen3.6-A3B` |
| `KN_LLM_API_KEY` | API key LLM | - |
| `KN_LLM_TIMEOUT` | Timeout richieste | `120` |
| `KN_LLM_TEMPERATURE` | Temperature LLM | `0.1` |
| `KN_LLM_MAX_TOKENS` | Token massimi generati per singola richiesta LLM | `4096` |
| `KN_CONFIDENCE_THRESHOLD_SEGMENTATION` | Threshold segmentazione | `0.7` |
| `KN_CONFIDENCE_THRESHOLD_CLASSIFICATION` | Threshold classificazione | `0.7` |
| `KN_CONFIDENCE_THRESHOLD_TOPIC` | Threshold topic | `0.6` |

### Modalità Mock (Testing)

Per usare il provider LLM mock:

```bash
export KN_LLM_ENDPOINT=mock://local
```

## Seed Dati

```bash
docker compose exec api python /app/scripts/seed_knowledge.py
```

## Pipeline di Elaborazione

```
OCR Result
    ↓
[1] Ensure Scan Unit
    ↓
[2] Router semantico
    ↓
[3] Segmentazione → Document Units
    ↓
[4] Classificazione → Document Type
    ↓
[5] Estrazione Entità → Entities
    ↓
[6] Topic Retrieval → Candidate Topics
    ↓
[7] Topic Assignment → Assignments o Proposals
    ↓
[8] Post-processing e specialist routing
```

Famiglie router correnti:

- `general`
- `normative`
- `meeting`
- `financial`
- `utility_vendor`
- `technical_admin`

## Stati

### Scan Unit
- `pending` - In attesa di elaborazione
- `processing` - In elaborazione
- `segmented` - Segmentazione completata
- `classified` - Classificazione completata
- `assigned` - Topic assegnati
- `needs_review` - Richiede revisione manuale
- `failed` - Errore in elaborazione

### Document Unit
- `pending` - In attesa
- `segmented` - Segmentato
- `classified` - Classificato
- `assigned` - Topic assegnato
- `needs_review` - Richiede revisione
- `failed` - Errore

## Stato Attuale E Limiti

1. La pipeline usa LLM locale OpenAI-compatible o mock deterministico.
2. Non usa ancora embeddings o vector search.
3. I topic proposals richiedono review umana quando il sistema non deve decidere automaticamente.
4. Il consolidamento è graph-based ma ancora da rafforzare con canonical entities.
5. È stato osservato un deadlock PostgreSQL su rerun/consolidation di documenti contabili complessi.
6. Il server LLM locale carica un solo modello alla volta: OCR e knowledge devono essere orchestrati in sequenza.
7. I risultati devono rispettare la lingua del documento, quindi documenti italiani devono produrre summary e knowledge in italiano.

## Assunzioni sul Formato OCR

Il servizio assume che l'OCR result contenga:
- `full_text`: Testo completo
- `markdown_text`: Testo in formato markdown
- `structured_json`: JSON strutturato con dati per pagina
- `page_count`: Numero totale di pagine

Se `structured_json` non ha dati per pagina, il servizio fa fallback su `markdown_text` dividendo equamente le linee.

## Note Sul Consolidamento Contabile

I rendiconti e i riparti non vanno fusi dentro topic di assemblea ordinaria o straordinaria solo perché appaiono nello stesso fascicolo. Il comportamento corretto è:

- meeting/verbali sotto topic meeting;
- rendiconti/riparti sotto topic famiglia contabile;
- eventuale relazione con assemblea come contesto secondario o pratica collegata.

La correzione recente crea/usa topic come `Rendiconti Condominiali - <condominio>` e rimuove assignment contabili erroneamente finiti in family meeting.
