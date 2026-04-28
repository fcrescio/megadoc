# Manuale di Sistema Megadoc

## Scopo

Megadoc e` un sistema self-hosted di document intelligence progettato per trasformare corpus PDF eterogenei in una base di conoscenza navigabile, revisionabile e progressivamente consolidabile.

Il sistema nasce per lavorare su documenti reali, non su benchmark puliti:

- scansioni rumorose
- PDF malformati o borderline
- pagine ruotate o capovolte
- documenti contabili e amministrativi con layout instabili
- fascicoli composti da piu` sottodocumenti
- corpora storici o accumulati senza struttura iniziale

L'obiettivo non e` "fare OCR". L'OCR e` solo il primo strato affidabile. Lo scopo finale e` costruire una memoria documentale navigabile fatta di:

- documenti e versioni
- testo OCR e derivati strutturati
- unita` logiche di documento
- classificazioni
- entita` estratte
- topic multipli e relazioni
- consolidamento progressivo
- intervento umano come parte nativa del sistema

## Review Architetturale

### Cosa funziona bene

1. L'architettura e` stratificata bene.
   Il sistema non chiede a un solo modello di risolvere ingest, OCR, semantica, clustering e review in un unico passaggio. Questo riduce i fallimenti opachi e permette miglioramenti locali.

2. Il dato sorgente viene preservato.
   PDF originale, versioni, OCR e derivati restano separati dalla knowledge. Questo e` corretto: gli strati semantici possono cambiare senza distruggere la prova documentale.

3. Il progetto ha preso la direzione giusta verso il human-in-the-loop.
   Topic proposals, multi-assign, canonical entities, review queue e commenti sul manuale sono tutti segnali di un sistema che non pretende un'automazione perfetta.

4. La knowledge e` navigabile da piu` assi.
   Documento, OCR, topic, entita`, canonical entities e ora search convivono nello stesso frontend. Questo e` un vantaggio forte rispetto a pipeline che producono solo JSON o solo embedding.

5. La pipeline OCR e` ormai realmente modulare.
   Il sistema puo` usare backend diversi, includere preflight, normalizzazione orientamento, fallback e refinement.

### Debolezze strutturali attuali

1. L'evoluzione schema e` ancora in parte applicativa.
   Oggi diverse tabelle e colonne vengono create o adattate allo startup con bootstrap SQL. E` pragmatico, ma nel medio termine rende piu` fragile il governo del dato rispetto a vere migration versionate.

2. Il modello knowledge e` piu` ricco del consolidamento attuale.
   Ora il sistema supporta topic multipli con ruoli diversi, ma buona parte della logica di consolidamento nasce ancora dal mondo precedente "un documento -> un topic principale". Serve evolvere il consolidamento in ottica grafo.

3. L'indice entita` e` utile ma ancora giovane.
   L'estrazione per documento funziona, ma la canonicalizzazione globale e` ancora un primo layer. Mancano ancora policy forti su merge, split, provenance e riuso nel routing semantico.

4. La coordinazione tra worker e modelli e` volutamente conservativa.
   La scelta di serializzare alcune richieste al modello evita collisioni, ma riduce throughput. E` accettabile in questa fase, ma andra` governata meglio se il corpus cresce.

5. Il frontend e` ormai ricco, ma la governance della review e` ancora implicita.
   Ci sono gia` ottime superfici di navigazione, ma mancano ancora workflow espliciti di priorita`, ownership, auditing e risoluzione dei conflitti tra review diverse.

### Giudizio complessivo

L'architettura e` buona e ha preso una direzione corretta: non e` un demo OCR, ma un sistema di costruzione progressiva di knowledge base. Il rischio principale non e` tecnico di base; e` di modellazione e governance. Il prossimo salto di qualita` non dipende solo da modelli migliori, ma da:

- migliore struttura delle relazioni
- migliore consolidamento
- maggiore intervento umano guidato
- regole piu` chiare su canonicalizzazione e review

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
6. estrazione entita`
7. assegnazione topic o proposal
8. consolidamento
9. review umana

Questo rende le failure analizzabili e correggibili.

### 3. Rappresentare l'ambiguita`, non nasconderla

Molti documenti sono rumorosi, compositi o semanticamente ambigui.

Per questo il sistema usa concetti come:

- `needs_review`
- topic proposal
- multi-assign
- canonical entity con varianti
- fallback OCR

La falsa certezza e` peggiore dell'incertezza esplicita.

### 4. L'umano non e` l'eccezione

L'utente non e` solo qualcuno che corregge errori. E` un co-autore della struttura della knowledge base.

Deve poter:

- approvare o rifiutare proposal
- unire topic
- creare topic manuali
- aggiungere topic secondari
- canonizzare entita`
- commentare il manuale

### 5. Progettare per documenti brutti

La pipeline deve reggere:

- scansioni pesanti
- layout strani
- bollette e scontrini
- regolamenti lunghi
- documenti ruotati
- PDF malformati

Per questo esistono preflight, detector di orientamento, fallback OCR e pipeline specializzabili.

## Architettura Logica

Megadoc e` composto da questi servizi principali:

- `api`: backend FastAPI
- `frontend`: interfaccia web
- `worker`: worker OCR / ingestion
- `knowledge_worker`: worker semantico
- `postgres`: sistema di record relazionale
- `redis`: broker per i job
- `minio`: object storage

Componenti ausiliari:

- container di bootstrap bucket storage
- container/build di migrazione o inizializzazione

## Runtime Topology

### API

L'API e` responsabile di:

- upload PDF
- creazione job
- elenco documenti e versioni
- download o visualizzazione inline dei PDF
- esposizione OCR
- esposizione knowledge
- topic, proposal, entities, canonical entities
- ricerca
- manuale vivo e commenti

L'API e` stateless sul piano applicativo; la persistenza vive in PostgreSQL e MinIO.

### OCR Worker

Il worker OCR consuma `ingestion_jobs` e si occupa di:

- preflight PDF
- scelta backend OCR
- normalizzazione orientamento quando abilitata
- esecuzione OCR
- salvataggio output e asset derivati
- enqueue automatico della knowledge dopo successo OCR

La separazione tra worker OCR e worker knowledge e` corretta: evita di legare il throughput OCR alla disponibilita` del modello semantico.

### Knowledge Worker

Il worker knowledge consuma `scan_unit` e produce:

- segmentazione in `document_unit`
- classificazione
- summary
- entita`
- assegnazioni topic
- topic proposal
- consolidamento scan-level

Attualmente la sua concorrenza e` deliberatamente prudente per non contendere il modello locale.

### Frontend

Il frontend e` il punto di contatto operativo per:

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

Il principio di prodotto e` corretto: OCR, knowledge e review non devono vivere in superfici separate.

## Modello Dati

### Strato documentale

- `documents`: identita` logica del documento
- `document_versions`: lineage binario
- `document_assets`: derivati e asset memorizzati
- `ingestion_jobs`: job OCR
- `ocr_results`: output OCR persistiti

### Strato knowledge

- `scan_units`: promozione di un OCR in unita` semanticamente processabile
- `document_units`: sottodocumenti logici dentro uno scan
- `document_unit_entities`: entita` estratte per unita`
- `document_unit_topic_assignments`: relazione molti-a-molti con ruoli
- `topics`: topic canonici
- `topic_aliases`: alias testuali dei topic
- `topic_proposals`: suggerimenti non ancora consolidati o gia` assorbiti
- `knowledge_jobs`: job asincroni della pipeline knowledge
- `llm_decisions`: audit trail delle decisioni modello

### Strato entita` canoniche

- `canonical_entities`
- `canonical_entity_variants`

### Strato collaborazione manuale

- `manual_comments`

## Ciclo di Vita di un Documento

### 1. Upload

L'upload salva il file, calcola hash, gestisce deduplica e versioning.

Possibili esiti:

- documento gia` noto
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
4. estrae entita`
5. assegna topic o produce proposal
6. applica post-processing

### 6. Review e consolidamento

L'utente puo` poi:

- navigare per topic
- cercare nel corpus
- rivedere proposals
- creare topic manuali
- aggiungere assignment multipli
- consolidare entita`

## Architettura OCR

### Preflight

Il preflight misura segnali tecnici che il solo `page_count` non cattura:

- PDF valido o malformato
- peso per pagina
- probabilita` `image_only`
- segnali di heavy scan
- rotazioni dichiarate

### Orientamento

L'orientamento e` un problema separato dall'OCR.
La pipeline puo` usare detector dedicati prima dell'OCR per normalizzare l'input.

### Backend OCR

Il sistema e` progettato per backend intercambiabili, tra cui:

- Docling + RapidOCR
- `dots_native` con prompt nativi `dots.ocr`
- backend sperimentali multimodali LLM

La direzione corretta e` mantenere un contratto comune di output, non un solo motore OCR.

### Fallback

Il backend `dots_native` e` stato irrobustito con:

- retry HTTP
- render alternativi
- rotazioni diverse
- seconda scala di render
- riconoscimento pagina vuota

Questa logica e` importante: una pipeline OCR reale deve degradare con grazia.

## Routing Knowledge

Il sistema usa un router semantico iniziale verso famiglie larghe:

- `general`
- `normative`
- `meeting`
- `financial`
- `utility_vendor`
- `technical_admin`

Questo e` meglio di un unico worker iper-specializzato, perche':

- consente prompt diversi
- consente post-processing diversi
- riduce interferenze tra famiglie documentali

La `general_pipeline` resta il fallback di sicurezza.

## Topic e Relazioni

Il modello corretto non e` "un documento appartiene a un solo topic".

Oggi un `document_unit` puo` avere piu` assignment con ruoli diversi, tra cui:

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

Questa e` una delle scelte architetturali piu` importanti del progetto.

## Consolidamento Topic

Il consolidamento attuale fa gia` diverse cose utili:

- bootstrap topic canonici
- merge di duplicati evidenti
- alias
- retarget degli assignment
- chiusura delle proposal assorbite

Ma non basta abbassare soglie per scendere a "poche decine" di topic.

La vera direzione e`:

- consolidamento assistito dall'umano
- strutture multi-topic
- consolidamento guidato da entita` forti
- review dei casi ambigui ad alto valore

Il consolidamento non deve distruggere granularita` utile. Deve separare:

- topic soggetto
- famiglie documentali
- pratiche/casi
- contesti organizzativi

## Entita`

Le entita` vengono prima estratte localmente per `document_unit`.
Poi il sistema offre:

- indice aggregato globale
- dettaglio entity con document hits
- canonical entities revisionabili

Questo e` corretto, ma ancora incompleto.

La direzione futura e` usare le canonical entities non solo per browsing, ma anche per:

- migliorare search
- influenzare consolidamento topic
- stabilizzare routing e classificazione

## Search

La search attuale e` un asse strategico del sistema.
Cerca su:

- topic
- alias
- document unit
- summary
- filename
- OCR text

Questo compensa un limite inevitabile della knowledge base: non tutto verra` canonizzato subito.
La search deve permettere di trovare anche cio` che il consolidamento non ha ancora strutturato.

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

Il visualizzatore PDF embedded e` importante: la review deve poter tornare alla fonte senza uscire dal contesto.

## Manuale Vivo

Questo stesso documento e` pensato come parte del prodotto, non come file statico dimenticato.

Funzioni attuali:

- e` servito dal frontend
- legge markdown dal backend
- consente selezione di un passaggio
- salva commenti con citazione e offset
- mostra stream dei commenti

Questo permette una manutenzione incrementale guidata dall'uso reale.

## Limiti Attuali del Manuale Vivo

La funzionalita` attuale e` utile, ma va letta per quello che e`:

- non e` ancora un sistema completo di annotation governance
- l'ancoraggio usa testo selezionato e offset, non ancora un motore robusto di re-anchoring su versioni future del testo
- non c'e` ancora threading dei commenti
- non c'e` ancora workflow di risoluzione o approvazione dei commenti

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
Serve usare con piu` forza:

- entita`
- soggetti
- periodi
- contesti
- relazioni tra documenti

### 3. Formalizzare le migration

Lo startup bootstrap e` stato utile per iterare velocemente, ma il progetto merita migrazioni versionate piu` esplicite.

### 4. Migliorare osservabilita`

Servono metriche piu` chiare su:

- tempi OCR
- tempi knowledge
- failure rate per backend
- documenti con alto rumore OCR
- topic troppo generici
- entita` ad alta collisione

### 5. Integrare meglio canonical entities e topic

Oggi i due mondi esistono entrambi.
Il prossimo salto e` fare in modo che si rafforzino a vicenda.

## Filosofia di Progetto

Megadoc non deve essere pensato come:

- un OCR con qualche etichetta
- un RAG di documenti
- un archivio PDF con ricerca full-text

Megadoc e` piu` correttamente:

- un sistema di ingestione documentale
- con memoria stratificata
- con semantica progressiva
- con consolidamento umano nel loop
- e con navigazione orientata alla costruzione di conoscenza

La filosofia corretta e` questa:

1. non perdere il grezzo
2. arricchire per strati
3. non fingere certezza
4. far intervenire l'umano nei punti ad alto valore
5. costruire una base di conoscenze che resti spiegabile, navigabile e correggibile

## Come Leggere Questo Manuale

Usa questo manuale per:

- capire come e` fatto il sistema
- discutere le scelte architetturali
- evidenziare punti fragili
- proporre miglioramenti
- lasciare commenti puntuali su passaggi specifici

Il manuale non e` definitivo. Deve evolvere con il sistema.
