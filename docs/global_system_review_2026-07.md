# Review globale e roadmap di Megadoc

Data della verifica: 10 luglio 2026  
Commit verificato: `358d835` (`main`, allineato a `origin/main`)

## Executive summary

Megadoc ha gia' l'ossatura corretta del prodotto desiderato. Conserva il PDF originale, separa OCR e interpretazione semantica, individua documenti logici dentro uno scan, mantiene evidenze di pagina, usa worker asincroni, dispone di review umana e ha specialisti reali per rendiconti e bollette. Non e' quindi un prototipo da rifondare.

La distanza dall'obiettivo non e' pero' uniforme:

| Capacita' | Stato stimato | Valutazione |
|---|---:|---|
| Conservazione, versioni e ingestione PDF | 80% | Fondazione valida; manca la prova di volume e di recovery sistematico |
| OCR di scan difficili | 65% | Pipeline e orientamento esistono; manca un benchmark misurato per qualita' pagina/tabella |
| Segmentazione in documenti logici | 65% | Implementata e revisionabile; qualita' non misurata su corpus stabile |
| Metadati, entita' e collegamenti | 55% | Modello ricco, ma vi sono rappresentazioni sovrapposte e canonicalizzazione ancora fragile |
| Bilanci e tabelle complesse | 70% | E' la parte specialistica piu' matura; servono contratti stabili, review e benchmark numerici |
| Bollette e fatture | 60% | Estrazione bollette e calendario esistono; fatture non sono ancora una capability autonoma verificata |
| Dialogo LLM con fonti | 45% | Tool, streaming, embedding e vision esistono; affidabilita' e latenza non sono ancora da prodotto |
| Operativita' su grandi volumi | 35% | Code e osservabilita' di base esistono; mancano SLO, backpressure, load test e recovery test |

In sintesi: il sistema e' circa a meta' strada verso un archivio affidabile su larga scala, ma oltre i due terzi per una buona workstation documentale assistita. La differenza e' soprattutto ingegneria della qualita', orchestrazione e semplificazione, non nuove feature visibili.

La priorita' non dovrebbe essere aggiungere altri specialisti. Prima occorre rendere misurabili il core documentale e il retrieval, ridurre i percorsi semantici concorrenti e trasformare l'agente da loop libero a ricerca guidata dall'evidenza.

## Evidenze raccolte

Lo stack era attivo e sano: API, frontend, PostgreSQL, Redis, MinIO, worker OCR, worker vision, knowledge worker e due specialist worker. L'endpoint di attivita' riportava stato `idle`, zero job attivi o stale.

Il database corrente contiene:

| Oggetto | Quantita' |
|---|---:|
| documenti | 43 |
| versioni | 43 |
| risultati OCR | 44 |
| scan unit | 44 |
| document unit | 73 |
| entita' locali | 421 |
| topic | 14 |
| assegnazioni topic | 79 |
| proposal | 52 |
| risultati specialistici | 12 |
| chunk di ricerca | 149 |
| dialoghi agente | 25 |
| eventi calendario | 1 |

Tutti i 44 job OCR, i 64 job knowledge e i 12 job specialistici risultano conclusi con successo. Tutti gli OCR hanno testo non vuoto. Le 73 document unit hanno titolo e summary; 53 risultano `human_reviewed`, 16 `auto_accepted` e 4 `needs_review`. Dei risultati specialistici, 4 sono rendiconti e 8 bollette; 2 richiedono review.

L'indice vettoriale e' popolato con embedding per tutti i suoi 149 elementi: 105 pagine OCR, 41 document unit e 3 topic.

Il dato piu' critico riguarda il dialogo: 14 run `answered` e 11 `incomplete`. I run conclusi impiegano in media circa 107 secondi; gli incompleti circa 109 secondi, con un massimo di 598 secondi. Tutti i run conclusi hanno almeno una citazione; quelli incompleti non ne hanno. Questo indica che il vincolo di evidenza funziona, ma il percorso per trovare l'evidenza e' ancora inefficiente e fragile.

Il campione corrente e' troppo piccolo e troppo influenzato dallo sviluppo interattivo per sostenere claim di produzione. Dimostra integrazione funzionale, non accuratezza generalizzabile o capacita' di volume.

La suite completa non e' verde: `103 passed`, `12 failed`, `6 errors`. Le failure interessano quattro test di classificazione, due test del router e sei test dell'estrazione accounting. I sei errori sono tutti negli integration test API: lo startup esegue `ensure_knowledge_schema()` contro il database SQLite di test prima che esista la tabella `topics`. Questo rafforza due conclusioni della review: lo schema allo startup deve essere eliminato e la baseline test deve essere ripristinata prima di valutare nuove feature. Alcuni test potrebbero essere rimasti indietro rispetto alla scelta LLM-driven, ma finche' non vengono aggiornati o sostituiti consapevolmente non costituiscono una rete di regressione affidabile.

## Cosa funziona bene

### 1. Il dato sorgente e' separato dai derivati

`documents`, `document_versions`, asset, OCR, scan unit, document unit e risultati specialistici formano una catena auditabile. Questa e' la decisione architetturale piu' importante e va preservata.

### 2. La document unit e' il corretto centro semantico

Il sistema non assume che un PDF equivalga a un documento logico. Per gli archivi di scansioni e fascicoli compositi e' indispensabile. Pagina, document unit e PDF devono restare tre livelli distinti.

### 3. Gli specialisti sono proiezioni, non sostituti dell'OCR

Rendiconti e bollette producono risultati tipizzati ancorati alla document unit. Il calendario deriva dalle bollette; le viste tabellari derivano dal risultato accounting. Questo consente di rigenerare le interpretazioni senza perdere la fonte.

### 4. La review e' parte del modello

Proposal, stati di review, correzioni tabellari e anteprima della pagina sorgente sono presenti. Per documenti storici rumorosi e cifre contabili non e' accettabile un'automazione priva di percorso di correzione.

### 5. L'agente dispone gia' degli ingredienti giusti

Esistono ricerca lessicale, ricerca vettoriale con pgvector, lettura pagina, accesso a document unit e specialisti, calendario e analisi visuale. Le risposte valide sono vincolate a citazioni pagina/documento. Il problema e' l'orchestrazione, non l'assenza degli strumenti.

## Gap principali

### P0. Non esiste ancora una misura ripetibile della qualita'

I test automatici verificano helper e contratti, ma non esiste un corpus gold versionato con aspettative a livello di pagina, document unit, metadato, tabella e domanda. Senza questo, ogni raffinamento puo' migliorare il documento osservato e peggiorarne altri senza che il progetto lo rilevi.

Servono metriche separate:

- OCR: character/word error rate su campione trascritto, copertura pagina e ordine di lettura;
- orientamento: accuratezza della rotazione per pagina;
- segmentazione: precision/recall dei confini e numero di document unit;
- classificazione/router: accuracy e tasso `unknown`/review;
- entita': precision/recall e canonicalizzazione;
- tabelle: fedelta' di righe, colonne, importi, totali e provenienza;
- retrieval: recall@k della pagina che contiene la risposta;
- agente: answerability, correttezza, supporto delle citazioni, latenza e numero di tool call.

### P0. Il dialogo non e' ancora affidabile ne' rapido

Il 44% dei run registrati e' incompleto. Cento secondi medi sono eccessivi per domande archivistiche normali. Il loop corrente lascia al modello troppe decisioni ripetitive: formulazione query, scelta indice, selezione documento, ricerca interna, lettura pagina e finalizzazione.

Il percorso dovrebbe diventare:

```text
domanda
  -> analisi intento e filtri
  -> retrieval ibrido unico
  -> reranking e diversificazione
  -> lettura obbligatoria delle migliori evidenze
  -> eventuali tool specialistici/vision
  -> risposta con claim-citation validation
```

Il modello puo' iterare, ma sopra un piano esplicito e con budget per fase. Non dovrebbe poter ripetere liberamente la stessa strategia di ricerca.

### P0. La scala operativa non e' stata dimostrata

La topologia Celery e' adatta a crescere, ma il runtime usa concorrenza prudente e condivide un server ML che carica modelli diversi. Su migliaia di PDF il collo di bottiglia sara' il cambio modello e non PostgreSQL.

Mancano:

- benchmark su almeno 500-1.000 PDF;
- priorita' e backpressure esplicite tra OCR, knowledge, embedding e specialisti;
- retry classificati per errore temporaneo/permanente;
- idempotency test e recovery dopo riavvio;
- dead-letter/review queue per job definitivamente falliti;
- stime di throughput, tempo residuo e costo per pagina;
- strategia di batching per embedding e chiamate omogenee al modello.

### P1. Il modello semantico ha troppi concetti sovrapposti

Il database contiene topic, entita' locali, entita' canoniche, context, graph node, mention, assertion, link e specialist result. Ciascuno ha una giustificazione, ma nel complesso vi sono piu' modi per rappresentare che un documento riguarda una persona, un immobile o una pratica.

La semplificazione raccomandata e':

- `document_unit`: unita' primaria navigabile;
- `entity`: identita' canonica globale con alias;
- `mention`: evidenza che una document unit menziona un'entity, con ruolo e pagina;
- `relation/assertion`: affermazione tipizzata e provata, solo quando serve davvero;
- `collection`: raggruppamento curatoriale esplicito; sostituisce l'uso generico dei topic;
- `specialist_result`: payload tipizzato e versionato;
- `search_chunk`: proiezione ricostruibile per retrieval.

`knowledge_contexts`, topic semantici e graph node non vanno eliminati subito. Vanno messi in compatibilita' e misurati: se rappresentano la stessa identita', devono convergere su un unico `entity_id`; se sono una vista, devono diventare una proiezione e non una seconda source of truth.

### P1. Schema e API sono troppo concentrati

`services/api/src/api/routers/knowledge.py` supera 5.600 righe e contiene 60 endpoint insieme a DTO interni, retrieval, agent loop, vision, accounting query, graph, proposal e cleanup. Anche altri moduli critici sono molto grandi: accounting extraction circa 1.800 righe, pipeline knowledge circa 1.460, consolidamento circa 1.460.

Questo aumenta il rischio di modifiche trasversali e rende difficile testare i servizi senza passare dal router. Il router deve diventare solo trasporto HTTP. I confini suggeriti sono:

- `knowledge/documents.py`
- `knowledge/review.py`
- `knowledge/search.py`
- `knowledge/agent.py`
- `knowledge/specialists.py`
- `knowledge/graph.py`
- servizi applicativi separati per retrieval, evidence e conversation orchestration.

La divisione va fatta senza cambiare gli endpoint pubblici e con characterization test prima dello spostamento.

### P1. Lo schema e' ancora modificato allo startup

`ensure_knowledge_schema()` contiene DDL per molte tabelle e indici gia' rappresentati da migration. Le migration arrivano a `20260704_0012`, ma lo startup conserva una seconda via di evoluzione schema. Questo rende meno deterministico un deploy e puo' nascondere una migration mancante.

Alembic deve essere l'unica autorita'. Lo startup dovrebbe soltanto verificare la revisione attesa e fallire con un messaggio chiaro se il DB e' indietro.

### P1. OCR e PDF nativi devono essere trattati in modo piu' esplicito

La pipeline supporta backend intercambiabili, orientamento e OCR multimodale, ma deve distinguere con un contratto stabile:

- pagina con text layer affidabile;
- pagina scan che richiede OCR;
- pagina ibrida;
- pagina che richiede vision/refinement;
- pagina illeggibile da inviare a review.

La selezione deve avvenire per pagina, registrando motivo, backend, trasformazioni, confidence e costo. Un PDF non-scan non dovrebbe essere rasterizzato e reinterpretato senza necessita'.

### P1. Gli specialisti necessitano di un contratto comune

Oggi accounting e utility bill funzionano, ma il prossimo caso particolare rischia di duplicare routing, job, result JSON, proiezione, endpoint e UI.

Ogni specialista dovrebbe dichiarare:

- `specialist_type` e versione schema;
- tipi documentali/capability accettati;
- input richiesti (testo, tabelle, immagini, metadati);
- output JSON Schema/Pydantic;
- confidence complessiva e per campo;
- evidence uniforme (`document_id`, `document_unit_id`, pagina, tabella/cella, raw value);
- regole di review;
- proiezioni opzionali (calendario, facts, search chunks);
- fixture gold e metriche specifiche.

Il router semantico deve poter restituire zero, uno o piu' specialisti. `unknown` e' un esito valido: i documenti generici restano comunque ricercabili tramite OCR, summary, entity e embedding.

### P2. Ricerca e indice vanno resi incrementali e osservabili

L'indice vettoriale e' presente, ma occorrono garanzie su aggiornamento e copertura. Ogni nuova versione o reprocessing deve invalidare e ricostruire soltanto i chunk interessati. Bisogna salvare modello, dimensione, versione del chunker e hash del testo.

Il retrieval dovrebbe fondere:

- filtri strutturati (date, tipo, entity, collection, importi);
- PostgreSQL full-text/trigram per nomi, codici e stringhe OCR;
- pgvector per similarita' semantica;
- risultati specialistici per dati tipizzati;
- reranker leggero o LLM solo sui candidati finali.

### P2. Sicurezza e governance non sono ancora da archivio multiutente

L'obiettivo dichiarato e' self-hosted, ma per un archivio reale servono almeno autenticazione, autorizzazioni per collection/documento, audit delle correzioni e politiche di retention/backup. Non e' prioritario per migliorare l'estrazione, ma diventa bloccante prima dell'uso con dati sensibili da parte di piu' utenti.

## Architettura target semplificata

La semplificazione non consiste nel trasformare tutto in testo per l'LLM. Consiste nel ridurre le source of truth e rendere ogni altro strato ricostruibile.

```text
SOURCE OF TRUTH
PDF/versione immutabile
  -> Page artifact (testo nativo/OCR, immagine, trasformazioni, qualita')
  -> Document unit (pagine, tipo, titolo, summary, review)
  -> Entity + Mention (identita' globale ed evidenza locale)
  -> Specialist result (payload tipizzato, versionato, evidence)

PROIEZIONI RICOSTRUIBILI
  -> collection/topic view
  -> graph/assertion view
  -> calendar event
  -> accounting analytical view
  -> lexical/vector search chunks

CONSUMATORI
  -> archivio UI
  -> review UI
  -> agente LLM con tool ed evidenze
```

Regola pratica: un nuovo tipo documentale generico non richiede schema o UI dedicati. Riceve OCR, segmentazione, tipo, summary, entity/mention e indicizzazione. Uno specialista si aggiunge solo quando esiste una domanda ricorrente che richiede struttura, validazione o azioni dedicate.

## Roadmap dettagliata

### Fase 0 - Ripristino test, baseline e corpus gold (1-2 settimane)

Obiettivo: rendere ogni modifica confrontabile.

Implementazione:

1. Triage dei 12 failure e 6 error correnti: correggere il codice quando il contratto e' ancora valido, aggiornare esplicitamente i test solo quando il comportamento desiderato e' cambiato.
2. Separare l'inizializzazione dello schema dalla lifespan API nei test e verificare schema/migration in modo deterministico.
3. Creare un manifest di 50-100 PDF rappresentativi, senza duplicare i PDF privati nel repository. Il manifest usa ID/hash e riferimenti a fixture in storage controllato.
4. Annotare un sottoinsieme di pagine per orientamento, testo, ordine e qualita'.
5. Annotare document unit attese, tipo, titolo minimo, entity chiave e pagine.
6. Per almeno 10 bilanci annotare tabelle, righe/celle e totali; per almeno 10 bollette annotare fornitore, oggetto, importo e scadenza.
7. Definire 30-50 domande archivistiche con pagina/evidenza attesa, incluse domande senza risposta.
8. Aggiungere un runner che riprocessa, esporta JSONL e produce un report comparativo.

Verifica:

- esecuzione ripetibile da database vuoto;
- suite corrente interamente verde, senza escludere silenziosamente i test falliti;
- report con metriche per ogni stadio e delta rispetto al commit baseline;
- nessuna regressione puo' essere approvata basandosi solo su ispezione UI.

Exit criteria:

- corpus rappresentativo approvato;
- `pytest` verde nel container di progetto;
- baseline pubblicata nel repository senza dati sensibili;
- CI esegue la parte deterministica, benchmark LLM eseguibile on demand.

### Fase 1 - Contratto pagina e OCR adattivo (2-3 settimane)

Obiettivo: rendere affidabile e auditabile l'ingestione di scan e PDF nativi.

Implementazione:

1. Introdurre un `PageArtifact` canonico con testo, markdown/blocks, dimensioni, rotation applicata, origine del testo, backend/versione, confidence e quality flags.
2. Classificare ogni pagina come native, scan, hybrid, low-quality o failed.
3. Usare text extraction nativa quando supera soglie misurate; OCR solo sulle pagine necessarie.
4. Applicare orientamento prima dell'OCR e conservare trasformazione e immagine originale.
5. Fare escalation controllata: estrazione nativa -> dots OCR -> retry parametrico -> vision -> review.
6. Rendere retry e timeout sensibili al cold start del modello e classificare gli errori.

Verifica:

- 100% delle pagine ha provenance del testo;
- accuratezza orientamento >= 99% sul gold set;
- nessuna rasterizzazione inutile dei PDF nativi gold;
- pagine fallite visibili come review item, mai silenziosamente vuote;
- rerun idempotente e confrontabile.

### Fase 2 - Core semantico unico (2-4 settimane)

Obiettivo: ridurre topic/context/graph duplicati e stabilizzare l'identita'.

Implementazione:

1. Documentare una matrice di ownership per tutti i 37 tipi di tabella correnti: source of truth, projection, cache o legacy.
2. Scegliere `canonical_entity` oppure `knowledge_node` come unica identita' globale e migrare l'altro a vista/proiezione.
3. Unificare entity variant, alias e mention con vincoli di unicita' e provenance.
4. Ridefinire i topic come collection curate; impedire che titoli LLM liberi creino automaticamente identita' globali.
5. Rendere context e graph proiezioni ricostruibili dall'identita' e dalle assertion.
6. Migrare dati in slice compatibili e mantenere temporaneamente adapter API.

Verifica:

- una persona/immobile canonico ha un solo ID globale;
- ogni associazione documentale ha evidence e ruolo;
- rebuild delle proiezioni produce conteggi e hash stabili;
- query UI e agent continuano a funzionare con characterization test;
- riduzione documentata di tabelle/concetti autorevoli, senza perdita di informazione.

### Fase 3 - Framework specialisti (2 settimane)

Obiettivo: rendere economico e sicuro aggiungere nuovi casi particolari.

Implementazione:

1. Creare registry e protocollo comune per detector, extractor, validator, projector e presenter.
2. Definire envelope comune di risultato ed evidence.
3. Portare accounting e utility bill sul protocollo senza cambiare inizialmente i payload interni.
4. Separare detection documentale dall'estrazione: il router produce capability candidate con confidence e rationale.
5. Consentire multi-specialist e nessuno specialista.
6. Aggiungere una UI generica per stato, confidence, evidence ed export; componenti dedicate solo per domini che lo meritano.

Verifica:

- accounting e utility bill passano gli stessi contract test;
- un dummy specialist viene aggiunto senza modificare API/router/job core;
- ogni campo estratto e' collegabile alla pagina e, per tabelle, a tabella/riga/cella;
- failure specialistica non impedisce la ricerca del documento generico.

### Fase 4 - Qualita' specialisti esistenti (3-5 settimane)

Obiettivo: rendere bilanci, bollette e prime fatture affidabili.

Accounting:

1. Conservare tabelle sorgente fedeli e spiegazione LLM separata.
2. Usare l'agente di riconciliazione per proporre struttura e aggregazioni, non per sovrascrivere valori raw.
3. Validare totali, subtotali, quadrature e periodi con controlli deterministici.
4. Esporre lineage di ogni aggregato fino alle celle originarie.
5. Salvare correction layer umano separato dal raw extraction.

Utility/fatture:

1. Generalizzare il modello payable: issuer, recipient, subject, issue date, due date, amount, currency, payment reference e status.
2. Distinguere bolletta, fattura, avviso e quietanza.
3. Proiettare nel calendario solo eventi con data; gli altri restano review item.
4. Deduplicare avviso/sollecito/quietanza tramite entity, importo, periodo e riferimento.

Verifica:

- esattezza importi/celle >= 98% sul campione leggibile;
- 100% degli aggregati ha lineage;
- zero correzioni silenziose dei numeri raw;
- precision/recall campi payable misurate e target >= 95% sui campi obbligatori;
- eventi calendario idempotenti e senza duplicati sul gold set.

### Fase 5 - Retrieval unificato evidence-first (2-3 settimane)

Obiettivo: trovare rapidamente le pagine giuste prima di avviare il ragionamento lungo.

Implementazione:

1. Estrarre dal router API un `RetrievalService` con una sola interfaccia.
2. Indicizzare pagina, document unit e specialist evidence con versioni/hash.
3. Combinare full-text/trigram, vector search e filtri strutturati con reciprocal-rank fusion.
4. Aggiungere reranking dei primi candidati e diversificazione per documento/pagina.
5. Rendere incrementale l'indexing e osservare copertura, freshness e tempi.
6. Creare tool specialistici ad alto livello, ad esempio `find_payables` e `query_accounting_tables`, invece di costringere l'LLM a ricostruire SQL o dataframe a piccoli passi.

Verifica:

- recall@5 della pagina gold >= 90%, recall@10 >= 95%;
- retrieval p95 < 2 secondi sul corpus target;
- nuovo upload ricercabile entro uno SLO definito;
- indice ricostruibile e nessun chunk stale dopo reprocessing.

### Fase 6 - Agente conversazionale controllato (2-4 settimane)

Obiettivo: risposte affidabili, citate e abbastanza rapide per uso quotidiano.

Implementazione:

1. Separare planner, retrieval, evidence reader e answer composer.
2. Inserire automaticamente nel contesto il testo delle migliori pagine; l'LLM non deve spendere tool call solo per leggere il candidato ovvio.
3. Consentire iterazione solo quando manca evidenza o serve un tool specialistico/vision.
4. Imporre budget per fase, deduplicazione semantica delle query e stop condition.
5. Validare ogni claim fattuale contro citation/evidence; distinguere risposta, inferenza e assenza di dati.
6. Conservare stato conversazionale come summary strutturato piu' riferimenti, non come trascrizione illimitata.
7. Eseguire vision solo su pagina selezionata e quando testo/struttura non bastano.

Verifica:

- >= 90% domande answerable corrette sul gold set;
- >= 98% claim fattuali supportati dalle citazioni;
- >= 95% domande unanswerable riconosciute senza inventare;
- p50 < 15 secondi e p95 < 45 secondi senza vision su hardware target;
- massimo medio <= 4 round LLM e nessuna tool call duplicata;
- test multi-turn per pronomi, follow-up e cambio documento.

### Fase 7 - Throughput, recovery e osservabilita' (2-3 settimane)

Obiettivo: ingestione affidabile di grandi batch.

Implementazione:

1. Creare load test da 500-1.000 PDF e simulazioni di restart durante ogni stadio.
2. Misurare coda, tempo per pagina, GPU utilization, model load time e failure class.
3. Raggruppare lavori per modello/capability per ridurre model thrashing.
4. Aggiungere retry policy con jitter e timeout cold/warm separati.
5. Aggiungere dead-letter/review queue e comandi di replay idempotenti.
6. Esporre ETA, throughput e motivo dell'attesa nella UI, oltre al semplice active/idle.

Verifica:

- nessun documento perso o duplicato dopo kill/restart;
- 99% job termina o entra esplicitamente in review/dead-letter;
- throughput e p95 documentati sul server target;
- code drenano senza intervento manuale dopo recovery del backend ML;
- storage, DB e indici restano consistenti dopo replay.

### Fase 8 - Hardening e operativita' archivistica (3-5 settimane)

Obiettivo: passare da ambiente personale di sviluppo a sistema gestibile.

Implementazione:

1. Spostare tutto il DDL da `ensure_knowledge_schema()` ad Alembic e aggiungere schema check read-only allo startup.
2. Spezzare il router knowledge in moduli e spostare la logica in application services.
3. Aggiungere autenticazione, autorizzazione per collection/documento e audit delle azioni umane.
4. Definire backup/restore verificato per PostgreSQL e MinIO.
5. Aggiungere retention, export e portabilita' dei dati.
6. Documentare SLO, runbook e compatibilita' delle versioni dei modelli.

Verifica:

- installazione su DB vuoto solo via migration;
- restore testato su ambiente separato;
- endpoint sensibili coperti da authorization test;
- nessun modulo HTTP contiene logica di dominio sostanziale;
- runbook riproduce recovery senza conoscenza implicita dello sviluppatore.

## Sequenza raccomandata e milestone

| Milestone | Fasi | Risultato |
|---|---|---|
| M1 - Misurabile | 0-1 | OCR e segmentazione hanno benchmark e provenance per pagina |
| M2 - Semplice | 2-3 | Un core semantico e un protocollo specialistico, meno concetti concorrenti |
| M3 - Affidabile sui documenti difficili | 4 | Bilanci e payable verificati con lineage e review |
| M4 - Consultabile | 5-6 | Retrieval rapido e dialogo citato con metriche di qualita' |
| M5 - Scalabile e gestibile | 7-8 | Batch grandi, recovery, migration, sicurezza e backup |

La prima release realmente utile puo' fermarsi a M4 su installazione singolo utente. M5 e' necessaria prima di parlare di produzione multiutente o archivi molto grandi.

## Cosa non fare adesso

- Non aggiungere un nuovo schema globale per ogni tipo documentale.
- Non trasformare tutti i metadati in `accounting_facts` o assertion generiche.
- Non delegare all'LLM controlli aritmetici, deduplica esatta o vincoli di integrita'.
- Non usare summary come prova: la risposta deve leggere pagina, cella o risultato specialistico con evidence.
- Non eliminare strutture sovrapposte prima di aver definito ownership, adapter e migrazione.
- Non ottimizzare il numero di worker prima di misurare model switching e throughput per pagina.
- Non valutare una modifica soltanto sul PDF che l'ha motivata.

## Prossimo passo concreto

La slice con il miglior rapporto rischio/beneficio e' la Fase 0: corpus gold e runner di valutazione. Subito dopo conviene implementare insieme il contratto `PageArtifact` e il retrieval evidence-first. Queste tre fondamenta permettono di semplificare il modello semantico e l'agente con dati, invece che per impressione.

Il primo commit dovrebbe contenere soltanto:

1. schema del manifest corpus;
2. schema delle annotazioni attese;
3. runner read-only che valuta l'attuale database;
4. report baseline JSON e Markdown;
5. nessuna modifica alla pipeline.

Questo crea il punto di confronto necessario per affrontare tutte le fasi successive in slice piccole, verificabili e reversibili.
