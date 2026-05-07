# Schema Estrazione E Associazioni Megadoc

Questo documento descrive cosa succede a un PDF caricato in Megadoc, quali informazioni vengono estratte e come vengono associate tra loro nello stato attuale del progetto.

## Schema Generale

```text
PDF caricato
  -> document
  -> document_version
  -> document_asset(original_pdf)
  -> ingestion_job
  -> ocr_result
       -> scan_unit
            -> knowledge_job
            -> document_unit 1..N
                 -> document_type
                 -> summary
                 -> entities
                 -> topic_assignments
                 -> topic_proposal eventuale
                 -> specialist_jobs eventuali
                 -> specialist_results eventuali
                 -> document_unit_links eventuali
            -> llm_decisions
```

## 1. Documento Logico

Quando carichi un PDF viene creato o riusato un `document`.

```text
document
- id
- external_id, se fornito
- original_filename
- mime_type
- sha256
- size_bytes
- source_type
- created_at
```

Questo e' il contenitore logico. Se usi `external_id`, piu' versioni dello stesso documento finiscono sotto lo stesso `document`.

Associazioni:

```text
document
  -> document_versions
  -> ingestion_jobs
  -> document_assets
  -> ocr_results
  -> scan_units
```

## 2. Versione Del Documento

Ogni contenuto binario diverso genera una `document_version`.

```text
document_version
- id
- document_id
- version_number
- storage_bucket
- storage_object_key
- created_at
```

Il PDF originale viene salvato in MinIO/storage come asset:

```text
document_asset
- document_id
- asset_type = original_pdf
- storage_bucket
- storage_object_key
- content_type = application/pdf
```

Il documento logico puo' cambiare filename/hash quando carichi una nuova versione, ma le versioni restano tracciate.

## 3. Job OCR

Se `auto_submit=true` o se lanci `/jobs/ingest`, viene creato un `ingestion_job`.

```text
ingestion_job
- id
- document_id
- job_type = ingest
- status = queued | running | succeeded | failed
- priority
- attempt_count
- error_message
- created_at
- started_at
- finished_at
```

Il job lavora sempre sull'ultima versione disponibile del documento.

## 4. OCR Result

Il worker OCR produce un `ocr_result`.

```text
ocr_result
- id
- document_id
- document_version_id
- engine_name
- engine_version
- pipeline_version
- status
- full_text
- markdown_text
- structured_json
- page_count
- confidence_summary
- created_at
```

In storage vengono anche creati asset derivati:

```text
document_asset
- markdown: result.md
- text: result.txt
- ocr_json: result.json
- preflight_json, se presente
- ocr_refinement_json, se presente
```

Dentro `structured_json` possono esserci:

```text
- payload strutturato OCR
- tabelle, se il backend le espone
- dati preflight
- dati orientation_preprocess
- dati ocr_refinement
```

Dentro `confidence_summary` possono esserci segnali come:

```text
- qualita'/preflight PDF
- orientamento
- refinement OCR
- confidence OCR/backend
```

## 5. Scan Unit

Dopo OCR riuscito, il sistema crea o riusa uno `scan_unit`.

```text
scan_unit
- id
- source_document_id
- source_document_version_id
- source_ocr_result_id
- page_count
- status
- segmentation_confidence
- classification_confidence
- assignment_confidence
- created_at
- updated_at
```

Questo e' il ponte tra OCR grezzo e knowledge processabile.

Associazioni:

```text
scan_unit
  -> document
  -> document_version
  -> ocr_result
  -> document_units
  -> knowledge_jobs
  -> llm_decisions
```

## 6. Segmentazione In Document Unit

Uno scan puo' contenere uno o piu' sottodocumenti. La pipeline produce `document_unit` prima di qualsiasi routing semantico specialistico.

```text
document_unit
- id
- scan_unit_id
- ordinal
- start_page
- end_page
- title
- document_type_id
- document_type_confidence
- segmentation_confidence
- extracted_summary
- review_status
- created_at
- updated_at
```

Ogni `document_unit` resta referenziato allo scan sorgente tramite pagine `start_page` / `end_page`. Il salvataggio di PDF figli per segmento e' ancora da progettare.

## 7. Routing Knowledge Per Segmento

Dopo la segmentazione, il sistema chiede all'LLM di decidere una famiglia di pipeline per ogni `document_unit`, leggendo solo il testo del segmento.

Famiglie possibili:

```text
general
normative
meeting
financial
utility_vendor
technical_admin
```

La decisione produce:

```text
pipeline_routing
- pipeline_id
- family
- confidence
- rationale
- signals
```

Questa decisione viene salvata in `llm_decisions` con `document_unit_id`. Segmenti diversi dello stesso PDF possono quindi essere post-processati da pipeline diverse.

Esempio:

```text
scan_unit: PDF da 20 pagine
  -> document_unit 1: pagine 1-3, lettera
  -> document_unit 2: pagine 4-12, rendiconto
  -> document_unit 3: pagine 13-20, riparto spese
```

Il PDF non viene assunto come unita' semantica unica.

## 8. Classificazione

Per ogni `document_unit`, il sistema estrae il testo del segmento e lo classifica.

Output logico:

```text
classification
- primary_type
  - type_code
  - confidence
  - salient_features
- alternatives
- rationale
```

Il risultato viene tradotto in:

```text
document_unit.document_type_id
document_unit.document_type_confidence
document_unit.extracted_summary
document_unit.review_status
```

Il tipo punta a `document_types`:

```text
document_type
- id
- code
- name
- description
- parent_code
- is_active
```

Esempi di tipi emersi dal codice/docs:

```text
bolletta
fattura
rendiconto_contabile
riparto_spese
verbale_assemblea
contratto
preventivo
lettera
altro
```

Se la confidence e' bassa, `review_status` diventa `needs_review`.

## 9. Entita' Estratte

Per ogni `document_unit`, viene eseguita entity extraction.

Tipi supportati dopo la semplificazione:

```text
organizzazione
persona
indirizzo
luogo
```

Questa estrazione generale serve alla ricerca e agli anchor del grafo, non a descrivere il dominio del documento. Per questo non estrae piu' importi, date, periodi, numeri documento, fornitori o condomini come tipi separati. Quei dati devono appartenere agli specialisti quando il documento viene riconosciuto come bolletta, rendiconto, verbale, contratto, ecc.

Ogni entita' diventa:

```text
document_unit_entity
- id
- document_unit_id
- entity_type
- entity_value
- normalized_value
- confidence
- page_from
- page_to
- created_at
```

Esempio:

```text
document_unit: bolletta acqua
  -> organizzazione = "Acque S.p.A."
  -> persona = "Mario Rossi"
  -> indirizzo = "Via Roma 10"
  -> luogo = "Scandicci"
```

Le entita' sono associate al `document_unit`, non direttamente al PDF intero.

## 10. Summary

Il summary del `document_unit` arriva da due punti:

```text
- rationale della classificazione
- summary dell'entity extraction, se piu' conciso
```

Viene salvato in:

```text
document_unit.extracted_summary
```

Il summary non e' una tabella separata: e' una proprieta' del sottodocumento.

## 11. Topic Esistenti

I topic sono fascicoli/argomenti navigabili.

```text
topic
- id
- slug
- title
- topic_class
- topic_kind
- description
- canonical
- is_active
- created_at
- updated_at
```

Classi topic:

```text
case_file
meeting
financial_period
vendor_relationship
building_issue
legal_matter
general_administration
other
```

Kind topic:

```text
entity      -> soggetto concreto
family      -> famiglia documentale
issue       -> problema/pratica
project     -> fascicolo/progetto
context     -> contesto persona/organizzazione
```

Esempi:

```text
topic_kind=entity:
- Lavastoviglie
- Acque S.p.A.
- Condominio Via Roma 10

topic_kind=family:
- Rendiconti Condominiali - Condominio X
- Verbali Assemblea - Condominio X
- Bollette Utenze

topic_kind=issue/project:
- Infiltrazione tetto scala B
- Pratica lavori facciata

topic_kind=context:
- Amministrazione condominiale
- Fornitore X
```

## 12. Recupero Topic Candidati

Dopo gli specialisti, prima di decidere l'associazione, il sistema cerca topic esistenti candidati usando:

```text
- titolo documento
- summary
- summary specialistici compattati, se presenti
- entita' estratte
- normalized_value delle entita'
- compatibilita' tra document_type e topic_class
- alias topic
```

Output:

```text
topic_candidate
- topic_id
- slug
- title
- score
- reasons
```

Esempi di reason:

```text
- Entity match
- Normalized entity match
- Title match
- Summary overlap
- Type compatible
```

## 13. Topic Assignment

Il topic assignment e' una fase di finalizzazione separata dalla classificazione iniziale. La knowledge pipeline produce `document_unit`, `document_type` ed entity generali, poi crea/accoda eventuali specialist job. Un task di finalizzazione aspetta che gli specialist job del medesimo scan non siano piu' `queued`, `pending` o `processing`; solo allora assegna i topic.

Contesto passato al topic assignment:

```text
- document_type
- titolo, se presente
- summary generale
- entita' generiche leggere
- topic candidati recuperati
- risultati specialistici compattati, se presenti
```

La decisione finale puo' essere:

```text
assign_existing
assign_multiple
propose_new
needs_review
```

Se assegna topic esistenti, crea record:

```text
document_unit_topic_assignment
- id
- document_unit_id
- topic_id
- assignment_role
- confidence
- rationale
- created_at
```

Ruoli attuali:

```text
subject
document_family
case_or_issue
person_or_org_context
secondary
```

Questo e' il cuore del modello multi-asse.

Esempio pratico:

```text
document_unit: fattura tecnico lavastoviglie

topic assignments:
- subject -> Lavastoviglie
- document_family -> Interventi Tecnici
- case_or_issue -> Guasto Lavastoviglie
- person_or_org_context -> Tecnico/Fornitore X
```

Un documento non sta dentro un solo topic. E' collegato a piu' assi.

## 14. Topic Proposal

Se non esiste un topic adeguato, viene creato un topic provvisorio e una proposal.

Topic provvisorio:

```text
topic
- canonical = false
- is_active = false
```

Proposal:

```text
topic_proposal
- id
- proposed_slug
- proposed_title
- topic_class
- proposed_topic_kind
- description
- proposal_status = proposed | approved | rejected | merged_into_existing
- source_document_unit_id
- matched_existing_topic_id
- confidence
- rationale
- created_at
- reviewed_at
```

In pratica:

```text
document_unit
  -> topic_proposal
       -> provisional topic
```

Il documento viene comunque assegnato al topic provvisorio, ma marcato come da rivedere.

## 15. Consolidamento Scan-Level

Dopo topic assignment, la pipeline prova a consolidare duplicati dentro lo stesso scan.

Esempio:

```text
PDF composto da piu' sezioni del medesimo regolamento condominiale
  -> piu' document_unit
  -> piu' proposal simili
  -> consolidamento verso un topic unico
```

Usa anchor da:

```text
- indirizzo
- organizzazione
- persona
- luogo
```

I vecchi valori `condominio` e `fornitore` possono ancora essere letti come compatibilita' con dati gia' presenti, ma non vengono piu' richiesti all'estrazione LLM generale.

Per documenti finanziari preferisce anchor tipo:

```text
organizzazione
persona
indirizzo
luogo
```

Per regolamenti condominiali puo' forzare coerenza:

```text
- document_type = contratto
- stesso topic per le unita'
- review_status = needs_review
```

## 16. Consolidamento Knowledge Base

Esiste anche un consolidamento globale sui topic.

Fa cose come:

```text
- trovare topic simili
- creare alias
- retarget degli assignment
- retarget delle proposal
- disattivare topic duplicati
```

Produce anche suggerimenti graph-based separati per asse:

```text
subject
document_family
case_or_issue
```

Ogni suggerimento contiene:

```text
- source_topic
- target_topic
- score
- rationale
- shared_entity_keys
- shared_document_count
```

La review salva:

```text
graph_consolidation_review
- axis
- source_topic_id
- target_topic_id
- action
- note
- acted_by
- created_at
```

## 17. Canonical Entities

Oltre alle entita' locali, esiste un livello globale revisionabile.

```text
canonical_entity
- id
- entity_type
- canonical_value
- display_value
- review_status
- created_at
- updated_at
```

Varianti:

```text
canonical_entity_variant
- canonical_entity_id
- entity_type
- entity_key
- display_value
- review_status
```

Esempio:

```text
canonical_entity:
- Acque S.p.A.

variants:
- acque spa
- acque s.p.a.
- Acque
```

Attualmente questo livello serve soprattutto per browsing/review e per suggerimenti di consolidamento. Non e' ancora il centro del grafo, ma dovrebbe diventarlo.

## 18. Specialist Routing

Dopo segmentazione, routing per segmento, classificazione ed entity extraction generale, il sistema puo' creare job specialistici per ogni `document_unit`.

Routing specialistico basato su:

```text
- document_type
- title
- summary
- testo del segmento
- marker lessicali
```

Specialisti attuali:

```text
utility_bill
accounting_statement
```

Job:

```text
specialist_job
- id
- document_unit_id
- specialist_type
- status
- input_version
- attempt_count
- error_message
- created_at
- started_at
- finished_at
```

`input_version` lega il risultato a:

```text
ocr_result_id:start_page-end_page
```

Quando gli specialisti hanno finito, `finalize_scan_topics_task` esegue topic retrieval, topic assignment e consolidamento usando anche i risultati specialistici disponibili.

## 19. Risultato Specialista Bollette

Per `utility_bill`, il risultato salva:

```text
specialist_result
- document_unit_id
- specialist_type = utility_bill
- schema_version = utility_bill_v1
- confidence
- review_status
- result_json
```

Dentro `result_json`:

```text
document_kind = utility_bill
input_version
issuer
service_type
account_holder
issue_date
due_date
billing_period_from
billing_period_to
total_amount
currency
document_number
contract_code
pod_pdr_or_supply_code
supply_reference
payment_status
detail_link_candidates
evidence
```

Puo' anche creare link verso altri `document_unit` correlati:

```text
document_unit_link
- source_document_unit_id
- target_document_unit_id
- link_type
- confidence
- rationale
```

Esempio:

```text
bolletta riepilogo
  -> link a dettaglio consumi
  -> link a documento collegato stesso fornitore/periodo
```

## 20. Risultato Specialista Rendiconti

Per `accounting_statement`, il risultato salva:

```text
document_kind = accounting_statement
input_version
statement_type
accounting_period_from
accounting_period_to
currency
tables
validation_checks
```

`statement_type` puo' essere:

```text
bilancio_preventivo
riparto_spese
rendiconto
estratto_contabile
unknown
```

Ogni tabella contiene:

```text
table_id
table_type
headers
raw_headers, se da struttura Docling
rows
totals
source
```

`table_type` puo' essere:

```text
payment_schedule
expense_allocation
summary
balance
unknown
```

Ogni riga:

```text
row_id
cells
normalized_amounts
```

Validation checks:

```text
summary_total_matches_balance
allocation_rows_sum_to_total
installment_sum_matches_total_due
statement_total_matches_payment_schedule
no_numeric_validation_available
```

Questi check possono avere:

```text
status = pass | fail | unknown
details
```

## 21. Audit Delle Decisioni

Le decisioni LLM o pseudo-LLM vengono salvate in:

```text
llm_decision
- scan_unit_id
- document_unit_id
- decision_type
- model_name
- prompt_version
- input_payload_json
- output_payload_json
- created_at
```

Decision types osservati:

```text
pipeline_routing
segmentation
classification
topic_assignment
```

`segmentation` e' una decisione scan-level; `pipeline_routing`, `classification` e `topic_assignment` sono decisioni per `document_unit`.

Questo permette di risalire a perche' il sistema ha deciso cosi'.

## Schema Relazionale Sintetico

```text
document
  1 -> N document_version
  1 -> N ingestion_job
  1 -> N ocr_result
  1 -> N document_asset
  1 -> N scan_unit

document_version
  1 -> N ocr_result
  1 -> N scan_unit

ocr_result
  1 -> N scan_unit

scan_unit
  1 -> N document_unit
  1 -> N knowledge_job
  1 -> N llm_decision

document_unit
  N -> 1 document_type
  1 -> N document_unit_entity
  1 -> N document_unit_topic_assignment
  1 -> 0/1 topic_proposal
  1 -> N specialist_job
  1 -> N specialist_result
  1 -> N outgoing document_unit_link
  1 -> N incoming document_unit_link
  1 -> N llm_decision

topic
  1 -> N topic_alias
  1 -> N document_unit_topic_assignment
  1 -> N topic_proposal matched_existing_topic

canonical_entity
  1 -> N canonical_entity_variant
```

## Sintesi

Ogni PDF viene preservato come prova grezza; l'OCR produce testo e struttura; lo scan viene diviso in sottodocumenti; ogni sottodocumento riceve tipo, summary, entita', topic multipli con ruoli distinti, eventuali proposal, eventuali estrazioni specialistiche e link ad altri sottodocumenti. Tutto resta ancorato a pagine, confidence, review status e audit delle decisioni.
