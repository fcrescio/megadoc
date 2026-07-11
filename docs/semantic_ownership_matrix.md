# Semantic Ownership Matrix

Data: 2026-07-10

Questa matrice definisce quale tabella e' autorevole e quale tabella e' una proiezione ricostruibile. Serve a evitare la proliferazione di identita' parallele tra topic, context, graph node, entity e specialist output.

## Decisione

`canonical_entities` e' la source of truth per identita' globali di persone, organizzazioni, indirizzi e luoghi.

`knowledge_nodes` e' una proiezione navigabile/graph. Quando un nodo rappresenta una identita' reconciliata deve puntare a `canonical_entities.id` tramite `knowledge_nodes.canonical_entity_id`. I nodi senza canonical entity sono ammessi solo come proiezioni temporanee o inferite da specialisti, e devono restare ricostruibili.

`topics` non rappresenta identita' globale. E' una collection curatoriale o una famiglia archivistica usata per navigazione e review.

`document_unit_entities` conserva le estrazioni locali dal documento. Non e' identita' globale.

`document_unit_mentions` conserva la mention navigabile verso il graph, con evidence. E' derivata da estrazioni locali, canonical entity e specialisti.

## Classi Di Ownership

- `source_of_truth`: dato primario o decisione umana/applicativa autorevole.
- `projection`: dato ricostruibile da source of truth e pipeline.
- `index_cache`: indice o cache ricostruibile.
- `operational`: stato operativo di job, migrazioni o dialoghi.
- `legacy_review`: tabella storica o di supporto review da mantenere finche' esistono consumer.

## Tabelle Runtime

| Tabella | Ownership | Ruolo |
|---|---|---|
| `documents` | source_of_truth | Documento logico caricato, identita' del file nell'archivio. |
| `document_versions` | source_of_truth | Versioni immutabili del documento e puntamento storage. |
| `document_assets` | source_of_truth | Asset derivati e sorgenti persistiti in storage. |
| `ocr_results` | source_of_truth | Risultato OCR/versione pipeline; contiene `page_artifacts` canonici per pagina. |
| `scan_units` | projection | Unita' scan creata da OCR per orchestrare knowledge pipeline. |
| `document_units` | source_of_truth | Documento logico navigabile dentro uno scan; boundary e review sono autorevoli. |
| `document_types` | source_of_truth | Vocabolario controllato dei tipi documentali. |
| `document_unit_entities` | source_of_truth | Mention locale estratta dal testo della document unit, non identita' globale. |
| `canonical_entities` | source_of_truth | Identita' globale reconciliata. |
| `canonical_entity_variants` | source_of_truth | Alias/chiavi che collegano estrazioni locali a identita' globali. |
| `document_unit_mentions` | projection | Mention navigabile verso `knowledge_nodes`, con evidence e riferimento eventuale a canonical entity. |
| `knowledge_nodes` | projection | Nodo graph ricostruibile; punta a `canonical_entities` quando rappresenta una identita' globale. |
| `knowledge_node_aliases` | projection | Alias navigabili del nodo graph. |
| `knowledge_predicates` | source_of_truth | Registry controllato dei predicati del graph. |
| `knowledge_assertions` | projection | Affermazioni tipizzate ricostruibili da classificazione, entity e specialisti. |
| `knowledge_contexts` | projection | Contesti di navigazione ricostruiti da canonical entities stabili. |
| `knowledge_context_anchors` | projection | Collegamento context -> canonical entities. |
| `knowledge_context_memberships` | projection | Appartenenza document unit -> context. |
| `topics` | source_of_truth | Collection/famiglia curatoriale. Non deve essere usata come identita' globale. |
| `topic_aliases` | source_of_truth | Alias curati per collection/topic. |
| `document_unit_topic_assignments` | source_of_truth | Decisione di assegnazione document unit -> collection/topic. |
| `topic_proposals` | legacy_review | Proposte revisionabili per collection/topic; input per decisione umana. |
| `graph_consolidation_reviews` | legacy_review | Audit di vecchie azioni di consolidamento topic/graph. |
| `document_unit_links` | projection | Link tra document unit, ricostruibile o revisionabile a seconda del tipo link. |
| `specialist_jobs` | operational | Stato operativo degli specialisti. |
| `specialist_results` | source_of_truth | Output versionato degli specialisti, con confidence/review/evidence. |
| `accounting_accounts` | projection | Vista analitica contabile ricostruibile da `specialist_results`. |
| `accounting_account_aliases` | projection | Alias degli account contabili ricostruibili. |
| `accounting_facts` | projection | Facts contabili materializzati per query; non sostituiscono il payload specialistico. |
| `calendar_events` | projection | Eventi calendario derivati da bollette/fatture/specialisti. |
| `knowledge_search_chunks` | index_cache | Chunk indicizzati per retrieval lessicale/vettoriale. |
| `knowledge_agent_runs` | operational | Trace e output delle conversazioni agente. |
| `llm_decisions` | operational | Audit delle decisioni LLM della pipeline. |
| `knowledge_jobs` | operational | Stato operativo della knowledge pipeline. |
| `ingestion_jobs` | operational | Stato operativo dell'ingestione/OCR. |
| `manual_comments` | source_of_truth | Commenti manuali dell'utente sulla documentazione/prodotto. |
| `alembic_version` | operational | Versione schema DB. |

## Regole Di Evoluzione

1. Ogni nuova identita' globale deve passare da `canonical_entities`.
2. Ogni associazione documento-identita' deve avere evidence locale: pagina, surface text, ruolo e confidence.
3. Ogni nuova vista per l'LLM deve essere `projection` o `index_cache`, salvo motivazione esplicita.
4. `topics` puo' raggruppare documenti, ma non deve diventare un secondo registro di persone, immobili o organizzazioni.
5. `knowledge_nodes` puo' avere nodi senza `canonical_entity_id` solo per oggetti non ancora reconciliati o per entita' specialistiche non promosse.

## Contratti applicativi

- La creazione e la riconciliazione delle identita' passa da `common.application.entities`.
- La coppia `(entity_type, canonical_value)` identifica una sola canonical entity.
- La coppia `(entity_type, entity_key)` identifica una sola variante e quindi un solo owner canonico.
- Le menzioni locali restano in `document_unit_entities`; non diventano identita' globali finche' non sono riconciliate.
- Graph e context sono proiezioni derivate. `rebuild_semantic_projections()` le ricostruisce insieme e `semantic_projection_fingerprint()` ne verifica il contenuto ignorando UUID e timestamp generati.
- I topic sono collection curate (`family`, `issue`, `project`, `context`), mai identita' globali.

## Compatibilita' e deprecazioni

- `TopicKind.ENTITY` resta temporaneamente leggibile nelle API per dati/client legacy, ma non e' selezionabile dalla UI e viene normalizzato in scrittura.
- `knowledge_nodes` senza `canonical_entity_id` sono ammessi per valori specialistici o menzioni non riconciliate; non sono una seconda source of truth.
- Gli endpoint graph/context restano adapter di lettura sulle proiezioni correnti.

Verifica operativa:

```bash
python scripts/rebuild_semantic_projections.py --verify-idempotent
```

Il comando termina con errore se conteggi o contenuto semantico cambiano fra due rebuild consecutivi.
6. I rebuild di graph, contexts e indici devono essere idempotenti e misurabili.
