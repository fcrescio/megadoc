# Framework specialisti

Gli specialisti trasformano una document unit gia' classificata in un payload di dominio verificabile. La classificazione documentale resta responsabilita' del knowledge classifier LLM; il framework non promuove documenti tramite keyword.

## Flusso

1. Il detector converte il tipo documentale LLM in uno o piu' `SpecialistCandidate`, con confidence e rationale.
2. Viene creato un job per ogni capability candidata. Nessun candidato significa nessun job specialistico; il documento resta comunque OCRizzato, indicizzato e ricercabile.
3. Il worker risolve la capability nel `SpecialistRegistry`.
4. Ogni handler esegue lo stesso contratto: `extract`, `validate`, `present`, `project`.
5. Il payload originale viene conservato e arricchito con `_specialist`, senza alterare lo schema di dominio esistente.
6. Un fallimento specialistico aggiorna solo il relativo job. Document unit, OCR e indicizzazione generica restano disponibili.

## Envelope

`result_json._specialist` contiene:

- `capability` e `schema_version`;
- confidence dell'estrazione;
- stato e messaggi di validazione;
- evidence con pagina e, quando applicabile, tabella, riga, colonna e valore raw;
- presentazione generica con titolo, sintesi e campi principali.

Accounting e utility mantengono i rispettivi payload interni. L'envelope e' il contratto comune consumato dalla UI e dai futuri strumenti generici.

## Payable

Lo specialista `utility_bill` proietta il payload compatibile in `payables`, che e' la rappresentazione autorevole di bollette, fatture, avvisi, solleciti e quietanze. Il payable conserva issuer, recipient, subject, date, importo, valuta, riferimento, stato, evidence e possibile duplicato.

Il calendario e' una proiezione operativa: riceve soltanto payable con scadenza valida e non duplicati. Un payable senza data non viene eliminato, ma resta `needs_review` ed e' visibile nella sezione di revisione del calendario.

La deduplicazione usa una fingerprint deterministica composta da emittente, destinatario, importo, valuta, riferimento e periodo. Il duplicato conserva la propria fonte e punta al payable originario tramite `duplicate_of_id`.

## Aggiungere uno specialista

1. Implementare un handler conforme a `SpecialistHandler` nel worker.
2. Registrarlo in `build_specialist_registry()`.
3. Dichiarare i tipi documentali supportati nel manifest `SPECIALIST_DOCUMENT_TYPES`.
4. Aggiungere contract test parametrizzati per envelope, validation ed evidence.
5. Aggiungere una vista dedicata solo se la card generica non consente una navigazione efficace.

Il task Celery, la persistenza dei risultati, lo stato dei job e la UI generica non devono essere modificati.

## Invarianti

- Il detector usa il tipo documentale assegnato dall'LLM, non il testo tramite keyword.
- Sono ammessi zero, uno o piu' specialisti per document unit.
- I valori raw non vengono sovrascritti dall'envelope.
- Ogni campo presentato deve avere almeno evidenza di pagina; le celle contabili includono table/row/column.
- La validazione determina `needs_review` anche quando la confidence numerica e' alta.
- Le proiezioni sono idempotenti e possono essere rigenerate dal risultato specialistico.
