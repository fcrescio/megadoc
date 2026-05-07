# Review TODO

TODO emersi dalla review architetturale del progetto.

## Knowledge Segmentation

- [ ] Rivedere la pipeline knowledge eliminando o ridimensionando il routing globale prima della segmentazione.

  Il routing scan-level attuale decide una famiglia di pipeline sull'intero OCR prima di sapere se il PDF contiene piu' documenti logici. Questo e' fragile per scansioni composte, per esempio pacchetti di bollette dove prospetti consumi, bollettini, fatture e allegati si alternano nello stesso PDF.

  Direzione preferita:

  ```text
  PDF sorgente
    -> OCR
    -> segmentazione documentale
    -> documenti figli / segmenti
    -> classificazione indipendente di ogni segmento
    -> routing specialistico per segmento
    -> link tra segmenti correlati
  ```

  La segmentazione va trattata come passaggio fondamentale ancora a livello documentale, prima della semantica specialistica. Idealmente dovrebbe produrre documenti figli o segmenti persistiti con PDF individuali, referenziati al documento sorgente ma trattati con la stessa dignita' operativa di un documento sorgente monolitico.

  Aspetti da progettare:

  - modello dati per documenti figli o segment assets;
  - salvataggio PDF per ciascun segmento;
  - relazione padre/figlio con pagine sorgente;
  - rerun indipendente OCR/knowledge sui figli, se utile;
  - classificazione per segmento;
  - topic assignment per segmento;
  - specialist routing per segmento;
  - link tra segmenti appartenenti allo stesso fascicolo/fattura/ciclo;
  - UI per navigare documento sorgente e figli.

## Entity Extraction

- [ ] Ridimensionare le entity generali a concetti realmente trasversali.

  L'entity extraction generale e' nata prima della separazione in routing e worker specialistici. Ora rischia di duplicare o confondere il lavoro degli specialisti, soprattutto su campi domain-specific come importi, periodi, numeri documento, condomini o fornitori.

  Direzione preferita:

  - mantenere entity generali solo per segnali utili alla ricerca immediata e al collegamento tra documenti non ancora specializzati;
  - spostare campi specifici negli specialisti competenti;
  - evitare entity generiche ad alta cardinalita'/rumore come `importo` nei documenti tabellari;
  - valutare un set ristretto: persone, indirizzi/luoghi, organizzazioni/aziende, forse date solo se usate in modo controllato.

## Topic Pipeline

- [ ] Spostare topic extraction/assignment dopo gli specialisti.

  I topic sono importanti da mantenere, ma oggi risentono della struttura storica in cui gli specialisti non esistevano ancora. La proposta di topic dovrebbe usare la massima comprensione disponibile del segmento: OCR, classificazione, entity generali leggere e output specialistico.

  Sequenza preferita:

  ```text
  OCR
    -> segmentazione
    -> classificazione document_unit
    -> entity extraction generale leggera
    -> specialist routing
    -> specialist extraction
    -> topic suggestion / topic assignment
    -> merge/consolidamento rigido
    -> review umana
  ```

- [ ] Separare nettamente topic proposal e topic canonici.

  L'LLM puo' essere piu' libero nella creazione di proposal: label, anchor, relazioni, rationale e confidence. La promozione a topic canonico deve invece essere piu' rigida, deterministica e conservativa.

  Regola generale:

  ```text
  proposal = libera, creativa, provvisoria
  topic canonico = stabile, ancorato, revisionabile
  ```

- [ ] Ridurre la ridondanza dei topic evitando topic puntuali o temporali.

  I topic dovrebbero rappresentare concetti con continuita':

  - soggetti: persone, aziende, condomini, immobili;
  - relazioni ricorrenti: utenze, contratti, rapporti fornitore;
  - pratiche/problemi: infiltrazioni, lavori, cause, guasti;
  - famiglie archivistiche stabili: verbali, rendiconti, contratti.

  Non dovrebbero rappresentare ogni fatto puntuale:

  - singola bolletta;
  - singolo importo;
  - singola data;
  - singolo numero fattura;
  - singolo pagamento.

  Questi dati vanno negli output specialistici o nei metadata del documento/segmento.

- [ ] Rendere il merge dei topic piu' rigido tramite anchor forti.

  Non mergiare se confliggono anchor forti:

  - indirizzi diversi;
  - organizzazioni diverse;
  - codici cliente/contratto/utenza diversi;
  - topic kind incompatibili;
  - document family incompatibili;
  - periodo/data come unico elemento comune.

  Suggerire o applicare merge solo con segnali solidi:

  - stessa organizzazione canonica;
  - stesso indirizzo/condominio/immobile;
  - stesso codice utenza/contratto/pratica;
  - alta sovrapposizione di documenti ed entity;
  - relationship type compatibile.

- [ ] Valutare topic come grafo, non solo come assignment piatti.

  I `document_unit_topic_assignments` restano utili, ma i topic canonici dovrebbero poter avere relazioni tipizzate tra loro.

  Esempi:

  ```text
  Utenza acqua - Condominio X
    supplied_by -> Acque S.p.A.
    belongs_to -> Condominio X
    has_documents -> bollette/segmenti

  Infiltrazione tetto scala B
    involves_property -> Condominio X
    involves_vendor -> Edilizia Rossi
    has_documents -> preventivo, fattura, email, verbale
  ```

  L'obiettivo e' mantenere topic solidi che connettano i documenti in un grafo di conoscenza, non una lista ridondante di etichette.

## Fallback Policy

- [ ] Fare una review completa dei fallback presenti nel codice.

  I fallback sono utili quando evitano un fallimento esplicito senza peggiorare la qualita' del risultato, ma diventano pericolosi se producono dati apparentemente validi e semanticamente deboli.

  Criterio da applicare:

  - eliminare i fallback che passano a euristiche o sistemi di qualita' inferiore;
  - mantenere fallback solo se portano a un sistema piu' lento, piu' costoso o piu' conservativo, ma non peggiore;
  - preferire failure esplicite a output di bassa qualita' marcati come riusciti;
  - quando un fallback resta, salvare nel risultato quale fallback e' stato usato;
  - esporre fallback e degradazioni in job status/UI/debug, senza renderli invisibili.

  Aree da rivedere:

  - OCR backend e retry/render alternativi;
  - LLM structured-output fallback;
  - classificazione knowledge;
  - entity extraction;
  - topic assignment euristico;
  - specialist extraction;
  - readiness/status probing.
