# Manuale di Sistema Megadoc

## Scopo

Megadoc è un sistema self-hosted di document intelligence progettato per trasformare corpus PDF eterogenei in una base di conoscenza navigabile, revisionabile e progressivamente consolidabile.

Il sistema nasce per lavorare su documenti reali, non su benchmark puliti:

- scansioni rumorose
- PDF malformati o borderline
- pagine ruotate o capovolte
- documenti contabili e amministrativi con layout instabili
- fascicoli composti da più sottodocumenti
- corpora storici o accumulati senza struttura iniziale

L'obiettivo non è "fare OCR". L'OCR è solo il primo strato affidabile. Lo scopo finale è costruire una memoria documentale navigabile fatta di:

- documenti e versioni
- testo OCR e derivati strutturati
- unità logiche di documento
- classificazioni
- entità estratte
- topic multipli e relazioni
- consolidamento progressivo
- intervento umano come parte nativa del sistema

## Struttura Architetturale

### Caratteristiche principali

1. Il sistema è stratificato.
   Ingestione, OCR, segmentazione, classificazione, estrazione entità, assegnazione topic, consolidamento e review sono stadi distinti.

2. Il dato sorgente è preservato.
   PDF originale, versioni, OCR e knowledge restano separati. Gli strati semantici possono quindi evolvere senza alterare la prova documentale.

3. Il modello di conoscenza è multi-asse.
   Un documento può essere segmentato in più unità e ogni unità può avere più assegnazioni topic con ruoli distinti.

4. La navigazione è unificata.
   Documento, PDF, OCR, knowledge, topic, entità e search sono esposti nello stesso frontend.

5. Il sistema è orientato al human-in-the-loop.
   Proposal, topic manuali, multi-assign, canonical entities e commenti al manuale fanno parte del modello operativo, non di un percorso eccezionale.

### Vincoli e rischi aperti

1. L'evoluzione schema è ancora in parte applicativa.
   Diverse tabelle e colonne vengono create o adattate allo startup con bootstrap SQL. Nel medio termine converrà spostare più logica su migration versionate.

2. Il consolidamento semantico è ancora parziale.
   Il modello supporta relazioni più ricche di quelle sfruttate oggi dal consolidamento automatico. Il passo successivo è una logica più esplicitamente orientata a grafo.

3. La canonicalizzazione delle entità è ancora iniziale.
   L'estrazione locale è buona, ma la fusione globale di varianti, alias e omonimie deve ancora maturare.

4. Il runtime LLM è seriale per vincolo infrastrutturale.
   Il server di inferenza carica un modello per volta; per questo la pipeline deve orchestrare in sequenza OCR e knowledge.

5. La governance della review è ancora leggera.
   Esistono le superfici di review, ma mancano ancora ownership, stati di risoluzione articolati e audit più dettagliato.

## Principi Guida

### 1. Preservare sempre l'evidenza grezza

Il PDF originale non deve essere sostituito da interpretazioni a valle.

Questo implica:

- OCR raw preservato
- refinement separato
- knowledge separata
- revisione umana sempre ancorata alla fonte

Il sistema deve poter sbagliare senza perdere il materiale di partenza.

### 2. Preferire arricchimento a strati

Megadoc decompone il problema in fasi:

1. ingestione
2. storage e versioning
3. OCR e preflight
4. segmentazione
5. classificazione
6. estrazione entità
7. assegnazione topic o proposal
8. consolidamento
9. review umana

Questo rende le failure analizzabili e correggibili.

### 3. Rappresentare l'ambiguità, non nasconderla

Molti documenti sono rumorosi, compositi o semanticamente ambigui.

Per questo il sistema usa concetti come:

- `needs_review`
- topic proposal
- multi-assign
- canonical entity con varianti
- fallback OCR

La falsa certezza è peggiore dell'incertezza esplicita.

### 4. L'umano non è l'eccezione

L'utente non è solo qualcuno che corregge errori. È un co-autore della struttura della knowledge base.

Deve poter:

- approvare o rifiutare proposal
- unire topic
- creare topic manuali
- aggiungere topic secondari
- canonizzare entità
- commentare il manuale

### 5. Progettare per documenti difficili

La pipeline deve reggere:

- scansioni pesanti
- layout strani
- bollette e scontrini
- regolamenti lunghi
- documenti ruotati
- PDF malformati

Per questo esistono preflight, detector di orientamento, fallback OCR e pipeline specializzabili.

## Architettura Logica

Megadoc è composto da questi servizi principali:

- `api`: backend FastAPI
- `frontend`: interfaccia web
- `worker`: worker OCR / ingestion
- `knowledge_worker`: worker semantico
- `postgres`: sistema di record relazionale
- `redis`: broker Celery e coda dei job
- `minio`: object storage

Componenti ausiliari:

- container di bootstrap bucket storage
- container/build di migrazione o inizializzazione

## Runtime Topology

### API

L'API è responsabile di:

- upload PDF
- creazione job
- elenco documenti e versioni
- download o visualizzazione inline dei PDF
- esposizione OCR
- esposizione knowledge
- topic, proposal, entities, canonical entities
- ricerca
- manuale vivo e commenti

L'API è stateless sul piano applicativo; la persistenza vive in PostgreSQL e MinIO.

### OCR Worker

Il worker OCR consuma `ingestion_jobs` e si occupa di:

- preflight PDF
- scelta backend OCR
- normalizzazione orientamento quando abilitata
- esecuzione OCR
- salvataggio output e asset derivati
- enqueue automatico della knowledge dopo successo OCR

La separazione tra worker OCR e worker knowledge è corretta: evita di legare il throughput OCR alla disponibilità del modello semantico.

### Knowledge Worker

Il worker knowledge consuma `scan_unit` e produce:

- segmentazione in `document_unit`
- classificazione
- summary
- entità
- assegnazioni topic
- topic proposal
- consolidamento scan-level

Attualmente la sua concorrenza è deliberatamente prudente per non contendere il modello locale.

### Frontend

Il frontend è il punto di contatto operativo per:

- lista documenti
- stato job
- visualizzazione PDF embedded
- consultazione OCR
- consultazione knowledge
- search
- topic browser
- entity browser
- canonical entity review
- proposal review
- lettura e commento del manuale

Il principio di prodotto è corretto: OCR, knowledge e review non devono vivere in superfici separate.

## Modello Dati

### Strato documentale

- `documents`: identità logica del documento
- `document_versions`: lineage binario
- `document_assets`: derivati e asset memorizzati
- `ingestion_jobs`: job OCR
- `ocr_results`: output OCR persistiti

### Strato knowledge

- `scan_units`: promozione di un OCR in unità semanticamente processabile
- `document_units`: sottodocumenti logici dentro uno scan
- `document_unit_entities`: entità estratte per unità
- `document_unit_topic_assignments`: relazione molti-a-molti con ruoli
- `topics`: topic canonici
- `topic_aliases`: alias testuali dei topic
- `topic_proposals`: suggerimenti non ancora consolidati o già assorbiti
- `knowledge_jobs`: job asincroni della pipeline knowledge
- `llm_decisions`: audit trail delle decisioni modello

### Strato entità canoniche

- `canonical_entities`
- `canonical_entity_variants`

### Strato collaborazione manuale

- `manual_comments`

## Ciclo di Vita di un Documento

### 1. Upload

L'upload salva il file, calcola hash, gestisce deduplica e versioning.

Possibili esiti:

- documento già noto
- nuova versione
- nuovo documento logico

### 2. Creazione job OCR

Se abilitato, il sistema crea un `ingestion_job`.
I job stantii vengono riconciliati automaticamente per evitare zombie `queued` o `running`.

### 3. OCR

L'OCR produce:

- `full_text`
- `markdown_text`
- `structured_json`
- `confidence_summary`
- eventuali metadati di preflight/refinement

### 4. Auto-enqueue knowledge

Dopo successo OCR, il sistema crea o riusa uno `scan_unit` e mette in coda la knowledge.
Questo chiude il vecchio gap in cui OCR e knowledge erano scollegati.

### 5. Estrazione semantica

La pipeline knowledge:

1. instrada il documento verso una famiglia di pipeline
2. segmenta
3. classifica
4. estrae entità
5. assegna topic o produce proposal
6. applica post-processing

### 6. Review e consolidamento

L'utente può poi:

- navigare per topic
- cercare nel corpus
- rivedere proposals
- creare topic manuali
- aggiungere assignment multipli
- consolidare entità

## Architettura OCR

### Preflight

Il preflight misura segnali tecnici che il solo `page_count` non cattura:

- PDF valido o malformato
- peso per pagina
- probabilità `image_only`
- segnali di heavy scan
- rotazioni dichiarate

### Orientamento

L'orientamento è un problema separato dall'OCR.
La pipeline può usare detector dedicati prima dell'OCR per normalizzare l'input.

### Backend OCR

Il sistema è progettato per backend intercambiabili, tra cui:

- Docling + RapidOCR
- `dots_native` con prompt nativi `dots.ocr`
- backend sperimentali multimodali LLM

La direzione corretta è mantenere un contratto comune di output, non un solo motore OCR.

### Fallback

Il backend `dots_native` è stato irrobustito con:

- retry HTTP
- render alternativi
- rotazioni diverse
- seconda scala di render
- riconoscimento pagina vuota

Questa logica è importante: una pipeline OCR reale deve degradare con grazia.

## Routing Knowledge

Il sistema usa un router semantico iniziale verso famiglie larghe:

- `general`
- `normative`
- `meeting`
- `financial`
- `utility_vendor`
- `technical_admin`

Questo è meglio di un unico worker iper-specializzato, perché:

- consente prompt diversi
- consente post-processing diversi
- riduce interferenze tra famiglie documentali

La `general_pipeline` resta il fallback di sicurezza.

## Topic e Relazioni

Il modello corretto non è "un documento appartiene a un solo topic".

Oggi un `document_unit` può avere più assignment con ruoli diversi, tra cui:

- `subject`
- `document_family`
- `case_or_issue`
- `person_or_org_context`
- `secondary`

Questo consente di modellare casi come:

- garanzia lavastoviglie:
  - `document_family = garanzie`
  - `subject = lavastoviglie`
- scontrino acquisto lavastoviglie:
  - `document_family = acquisti`
  - `subject = lavastoviglie`
- fattura tecnico lavastoviglie:
  - `document_family = interventi_tecnici`
  - `subject = lavastoviglie`
  - eventuale `case_or_issue = guasto_lavastoviglie`

Questa è una delle scelte architetturali più importanti del progetto.

## Consolidamento Topic

Il consolidamento attuale fa già diverse cose utili:

- bootstrap topic canonici
- merge di duplicati evidenti
- alias
- retarget degli assignment
- chiusura delle proposal assorbite

Ma non basta abbassare soglie per scendere a "poche decine" di topic.

La vera direzione è:

- consolidamento assistito dall'umano
- strutture multi-topic
- consolidamento guidato da entità forti
- review dei casi ambigui ad alto valore

Il consolidamento non deve distruggere granularità utile. Deve separare:

- topic soggetto
- famiglie documentali
- pratiche/casi
- contesti organizzativi

## Entità

Le entità vengono prima estratte localmente per `document_unit`.
Poi il sistema offre:

- indice aggregato globale
- dettaglio entity con document hits
- canonical entities revisionabili

Questo è corretto, ma ancora incompleto.

La direzione futura è usare le canonical entities non solo per browsing, ma anche per:

- migliorare search
- influenzare consolidamento topic
- stabilizzare routing e classificazione

## Search

La search attuale è un asse strategico del sistema.
Cerca su:

- topic
- alias
- document unit
- summary
- filename
- OCR text

Questo compensa un limite inevitabile della knowledge base: non tutto verrà canonizzato subito.
La search deve permettere di trovare anche ciò che il consolidamento non ha ancora strutturato.

## Frontend

Il frontend attuale offre:

- `Documents`: lista documenti e stato job
- dettaglio documento con tab:
  - `Info`
  - `PDF`
  - `OCR`
  - `Knowledge`
  - `Versions`
  - `Assets`
- `Knowledge`: search console, topic browser, entity browser, review
- `Manual`: manuale vivo commentabile

Il visualizzatore PDF embedded è importante: la review deve poter tornare alla fonte senza uscire dal contesto.

## Manuale Vivo

Questo stesso documento è pensato come parte del prodotto, non come file statico dimenticato.

Funzioni attuali:

- è servito dal frontend
- legge markdown dal backend
- consente selezione di un passaggio
- salva commenti con citazione e offset
- mostra stream dei commenti

Questo permette una manutenzione incrementale guidata dall'uso reale.

## Limiti Attuali del Manuale Vivo

La funzionalità attuale è utile, ma va letta per quello che è:

- non è ancora un sistema completo di annotation governance
- l'ancoraggio usa testo selezionato e offset, non ancora un motore robusto di re-anchoring su versioni future del testo
- non c'è ancora threading dei commenti
- non c'è ancora workflow di risoluzione o approvazione dei commenti

Va bene come primo livello operativo.

## Direzioni Future Raccomandate

### 1. Portare la review da "possibile" a "governata"

Servono:

- review queue priorizzata
- ownership
- audit degli interventi
- stato commenti / stato proposal / stato merge

### 2. Passare dal consolidamento per topic al consolidamento per grafo

Non basta unire stringhe simili.
Serve usare con più forza:

- entità
- soggetti
- periodi
- contesti
- relazioni tra documenti

### 3. Formalizzare le migration

Lo startup bootstrap è stato utile per iterare velocemente, ma il progetto merita migrazioni versionate più esplicite.

### 4. Migliorare osservabilità

Servono metriche più chiare su:

- tempi OCR
- tempi knowledge
- failure rate per backend
- documenti con alto rumore OCR
- topic troppo generici
- entità ad alta collisione

### 5. Integrare meglio canonical entities e topic

Oggi i due mondi esistono entrambi.
Il prossimo salto è fare in modo che si rafforzino a vicenda.

## Filosofia di Progetto

Megadoc non deve essere pensato come:

- un OCR con qualche etichetta
- un RAG di documenti
- un archivio PDF con ricerca full-text

Megadoc è più correttamente:

- un sistema di ingestione documentale
- con memoria stratificata
- con semantica progressiva
- con consolidamento umano nel loop
- e con navigazione orientata alla costruzione di conoscenza

La filosofia corretta è questa:

1. non perdere il grezzo
2. arricchire per strati
3. non fingere certezza
4. far intervenire l'umano nei punti ad alto valore
5. costruire una base di conoscenze che resti spiegabile, navigabile e correggibile

## Come Leggere Questo Manuale

Usa questo manuale per:

- capire come è fatto il sistema
- discutere le scelte architetturali
- evidenziare punti fragili
- proporre miglioramenti
- lasciare commenti puntuali su passaggi specifici

Il manuale non è definitivo. Deve evolvere con il sistema.
