# Knowledge Classifier Service

Modulo per la classificazione automatica di documenti scansionati.

## Panoramica

Questo servizio prende in input il risultato OCR di un PDF e:

1. **Segmenta** lo scan in documenti logici distinti
2. **Classifica** ogni documento in un tipo noto
3. **Estrae** entità chiave (condomini, date, importi, etc.)
4. **Assegna** il documento a topic esistenti o propone nuovi topic

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

## Avvio

```bash
# Avvia tutti i servizi
docker compose up --build

# Avvia solo il knowledge worker
docker compose up knowledge_worker
```

## API Endpoints

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

## Configurazione

| Variabile | Descrizione | Default |
|-----------|-------------|---------|
| `KN_LLM_ENDPOINT` | Endpoint LLM API | `http://10.89.0.3:8080/v1` |
| `KN_LLM_MODEL` | Nome modello LLM | `qwen3.5-27B` |
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
[1] Segmentazione → Document Units
    ↓
[2] Classificazione → Document Type
    ↓
[3] Estrazione Entità → Entities
    ↓
[4] Topic Retrieval → Candidate Topics
    ↓
[5] Topic Assignment → Assignments o Proposals
```

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

## Limiti Noti v1

1. La segmentazione si basa su pattern lessicali semplici
2. Non usa embeddings o vector search
3. L'estrazione entità è basica (regex + LLM)
4. I topic proposals richiedono approvazione manuale

## Assunzioni sul Formato OCR

Il servizio assume che l'OCR result contenga:
- `full_text`: Testo completo
- `markdown_text`: Testo in formato markdown
- `structured_json`: JSON strutturato con dati per pagina
- `page_count`: Numero totale di pagine

Se `structured_json` non ha dati per pagina, il servizio fa fallback su `markdown_text` dividendo equamente le linee.
