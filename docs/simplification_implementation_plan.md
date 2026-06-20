# Piano Implementativo Di Semplificazione

Questo documento trasforma l'analisi critica del sistema in una sequenza di interventi piccoli, verificabili e reversibili.

L'obiettivo non e' aggiungere un altro livello di complessita', ma ridurre la pressione oggi caricata sui `Topic`. I topic devono diventare raccolte/contesti stabili, mentre navigazione e interrogazione devono appoggiarsi a document unit titolate, entita' canoniche, contesti, fatti e output specialistici.

## Principi Operativi

- Procedere per slice verticali: schema, logica, test, verifica DB, UI/API minima.
- Non cancellare dati sorgente. Le correzioni lavorano su dati derivati.
- Ogni step deve essere idempotente o avere una procedura di backfill/rerun esplicita.
- Ogni trasformazione automatica deve salvare evidenza o confidence quando produce semantica nuova.
- Non affidare al titolo libero LLM identita' canoniche o merge irreversibili.

## Baseline Da Verificare Prima Di Ogni Slice

Prima di iniziare una slice, fotografare lo stato:

```bash
git status --short
docker compose ps
docker exec megadoc-postgres-1 psql -U megadoc -d megadoc -P pager=off -c "
SELECT 'documents' AS entity, count(*) FROM documents
UNION ALL SELECT 'scan_units', count(*) FROM scan_units
UNION ALL SELECT 'document_units', count(*) FROM document_units
UNION ALL SELECT 'topics', count(*) FROM topics
UNION ALL SELECT 'topic_assignments', count(*) FROM document_unit_topic_assignments
UNION ALL SELECT 'topic_proposals', count(*) FROM topic_proposals
UNION ALL SELECT 'llm_decisions', count(*) FROM llm_decisions
UNION ALL SELECT 'specialist_results', count(*) FROM specialist_results;
"
```

Verifiche ricorrenti:

```sql
SELECT count(*) AS empty_titles
FROM document_units
WHERE title IS NULL OR btrim(title) = '';

SELECT count(*) AS duplicate_same_topic_unit_role
FROM (
  SELECT document_unit_id, topic_id, assignment_role, count(*)
  FROM document_unit_topic_assignments
  GROUP BY document_unit_id, topic_id, assignment_role
  HAVING count(*) > 1
) d;

SELECT count(*) AS duplicate_same_topic_unit_any_role
FROM (
  SELECT document_unit_id, topic_id, count(*)
  FROM document_unit_topic_assignments
  GROUP BY document_unit_id, topic_id
  HAVING count(*) > 1
) d;

SELECT count(*) AS orphan_document_units
FROM document_units du
LEFT JOIN document_unit_topic_assignments a ON a.document_unit_id = du.id
WHERE a.id IS NULL;
```

## Step 1 - Guardrail Su Assegnazioni Topic

### Problema

`document_unit_topic_assignments` e' una tabella append-only dal punto di vista applicativo. Il DB non impedisce duplicati, e `_create_topic_assignments` crea sempre una nuova riga.

Anche se il database corrente puo' risultare pulito, la protezione non e' strutturale.

### Implementazione

File principali:

- `alembic/versions/...`
- `packages/common/src/common/db/models.py`
- `packages/common/src/common/db/schema.py`
- `services/knowledge_classifier/src/knowledge_classifier/services/pipeline.py`
- `services/api/src/api/routers/knowledge.py`
- test in `tests/knowledge/` o `tests/unit/`

Azioni:

1. Aggiungere migrazione Alembic che crea un unique index o constraint:

   ```sql
   UNIQUE (document_unit_id, topic_id, assignment_role)
   ```

   Prima della constraint, la migrazione deve deduplicare eventuali righe esistenti scegliendo la riga migliore:

   - preferire `confidence` piu' alta;
   - poi `created_at` piu' recente;
   - mantenere `rationale` non nullo quando disponibile.

2. Aggiornare `DocumentUnitTopicAssignment.__table_args__` con `UniqueConstraint`.

3. Aggiornare `ensure_knowledge_schema()` con `CREATE UNIQUE INDEX IF NOT EXISTS`.

4. Cambiare `_create_topic_assignments` in upsert applicativo:

   - risolvere il topic id;
   - normalizzare role;
   - cercare assegnazione esistente per `(document_unit_id, topic_id, role)`;
   - se esiste, aggiornare `confidence` e `rationale`;
   - se non esiste, creare.

5. In `approve_topic_proposal`, prima di assegnare topic, usare una helper comune tipo:

   ```python
   upsert_document_unit_topic_assignment(doc_unit, topic, role, confidence, rationale)
   ```

   Evitare logica duplicata tra API e pipeline.

6. Decidere esplicitamente se lo stesso topic puo' avere ruoli diversi sullo stesso document unit.

   Raccomandazione iniziale: tecnicamente consentito, ma la UI e l'API devono avvisare. In una seconda fase si puo' imporre unicita' su `(document_unit_id, topic_id)`.

### Verifica

Unit test minimi:

- `_create_topic_assignments` chiamato due volte con stesso topic/role produce una sola riga.
- Approve di proposal verso un topic gia' assegnato aggiorna la riga esistente.
- Approve con ruolo diverso e' gestito secondo la policy scelta.

Query:

```sql
SELECT document_unit_id, topic_id, assignment_role, count(*)
FROM document_unit_topic_assignments
GROUP BY document_unit_id, topic_id, assignment_role
HAVING count(*) > 1;
```

Deve tornare zero righe.

Verifica API:

1. Scegliere una proposal pending in ambiente dev.
2. Approvare.
3. Ripetere scenario equivalente con topic gia' assegnato tramite test.
4. Confermare che `count(*)` non cresce oltre una assegnazione per chiave.

Definition of done:

- DB constraint presente.
- Test automatici verdi.
- Query duplicati = zero.
- Codice pipeline/API usa helper unico di upsert.

## Step 2 - Titoli Per Document Unit

### Problema

La quasi totalita' dei `document_units.title` e' nulla. La UI e le API devono quindi appoggiarsi a summary lunghi o topic, peggiorando navigazione e matching.

### Implementazione

File principali:

- `services/knowledge_classifier/src/knowledge_classifier/services/pipeline.py`
- possibile nuovo modulo `services/knowledge_classifier/src/knowledge_classifier/services/title_generation.py`
- `services/api/src/api/routers/knowledge.py`
- `tests/knowledge/test_pipeline_quality.py`
- eventuale script backfill in `scripts/`

Azioni:

1. Creare helper deterministico:

   ```python
   def derive_document_unit_title(
       document_type_code: str | None,
       summary: str | None,
       entities: list[ExtractedEntity | DBDocumentUnitEntity],
       specialist_results: list[SpecialistResult] | None = None,
       fallback_filename: str | None = None,
       page_range: tuple[int, int] | None = None,
   ) -> str:
       ...
   ```

2. Regole iniziali:

   - utility bill:
     `Bolletta <fornitore> - <intestatario/contesto> - <periodo o scadenza>`
   - accounting statement:
     `<tipo rendiconto> - <condominio/contesto> - <periodo>`
   - meeting:
     `Verbale assemblea - <condominio/contesto> - <data se presente>`
   - legal/regolamento:
     `<tipo documento> - <condominio/indirizzo>`
   - fallback:
     `<tipo documento leggibile> - pagine X-Y`

3. Popolare il titolo dopo entity extraction e dopo specialist extraction, non solo subito dopo segmentazione.

   Nel flusso attuale:

   - prima title debole dopo classification/entity extraction;
   - title migliorato in `finalize_scan_topics` quando sono disponibili specialist results.

4. Creare uno script backfill idempotente:

   ```bash
   scripts/backfill_document_unit_titles.py --dry-run
   scripts/backfill_document_unit_titles.py --apply
   ```

   Il dry-run deve stampare `document_unit_id`, titolo vecchio, titolo nuovo, ragione.

5. Non usare LLM per il titolo nella prima implementazione. Se si usera' LLM, deve essere solo fallback e con review status.

### Verifica

Test:

- fixture utility bill produce titolo stabile.
- fixture accounting statement produce titolo con periodo.
- fixture generica produce fallback non vuoto.
- titolo massimo 512 caratteri.
- niente newline nel titolo.

Query:

```sql
SELECT count(*) AS empty_titles
FROM document_units
WHERE title IS NULL OR btrim(title) = '';
```

Target dopo backfill: `0` o solo casi esplicitamente esclusi.

API/UI:

- endpoint document detail espone `title`.
- lista document unit mostra title breve.
- ricerca knowledge su title funziona.

Definition of done:

- Nuovi document unit ricevono title.
- Backfill produce title per dati esistenti.
- Summary resta descrittivo, non viene sovrascritto con title.

## Step 3 - Ridurre Il Ruolo Dei Topic

### Problema

`Topic` oggi rappresenta contemporaneamente categoria, entita', pratica, famiglia, contesto e risultato di matching. Questo produce proliferazione.

### Implementazione

File principali:

- `docs/extraction_schema.md`
- `services/knowledge_classifier/src/knowledge_classifier/services/topic_assignment.py`
- `services/knowledge_classifier/src/knowledge_classifier/services/topic_retrieval.py`
- `services/knowledge_classifier/src/knowledge_classifier/prompts/templates.py`
- `services/api/src/api/routers/knowledge.py`
- UI knowledge panels

Azioni:

1. Documentare una policy esplicita:

   ```text
   Topic canonico = raccolta stabile o pratica/materia.
   Non creare topic canonico per singola bolletta, singola fattura, singolo pagamento, singola data.
   ```

2. Introdurre una classificazione interna delle proposal:

   - `create_topic`: serve nuovo topic canonico.
   - `attach_to_context`: non serve topic, basta contesto/fatti.
   - `attach_to_existing_topic`: topic esistente.
   - `needs_review`: ambigua.

3. Aggiornare prompt topic assignment:

   - vietare topic puntuali;
   - chiedere `proposed_topic` solo per pratiche/relazioni stabili;
   - per bollette/fatture ripetitive, preferire assignment a contesto o vendor relationship se disponibile.

4. Aggiornare retrieval:

   - candidati topic filtrati per `topic_kind` compatibile;
   - penalizzare topic con `assignment_count <= 1` e titolo molto specifico/data-like;
   - preferire contesti e nodes per matching iniziale.

5. UI:

   - topic panel deve distinguere topic canonici da document family/context/entity.
   - le proposal devono mostrare se l'azione raccomandata e' creare topic o solo agganciare a contesto.

### Verifica

Metriche su nuovo batch di test:

```sql
SELECT count(*) FROM topics;
SELECT count(*) FROM documents;
SELECT count(*) FROM topic_proposals WHERE proposal_status = 'proposed';
```

Definire un fixture set di almeno:

- 3 bollette stesso fornitore/stesso soggetto;
- 2 fatture stesso fornitore;
- 2 documenti stesso condominio;
- 1 vera pratica/issue.

Risultato atteso:

- le bollette non creano 3 topic puntuali;
- la vera pratica crea o usa un topic stabile;
- proposal nuove hanno azione distinta da `create_topic` quando basta il contesto.

Definition of done:

- La policy e' documentata.
- La pipeline non crea topic per ogni documento ripetitivo nel fixture set.
- La UI rende chiara la differenza tra topic e contesto.

## Step 4 - Archive Identity

### Problema

Il matching oggi dipende troppo da titolo/summary. Serve una chiave canonica generale che rappresenti gli assi archivistici del document unit.

### Schema Proposto

Introdurre una struttura derivata chiamata `archive_identity`:

```json
{
  "document_family": "utility_bill",
  "context_key": "condominio:via_cesare_studiati_pisa",
  "primary_party_key": "organization:enel",
  "subject_key": "person:crescioli_francesco",
  "period_key": "2012-07",
  "matter_key": null,
  "confidence": 0.82,
  "evidence": {
    "document_type": "utility_bill",
    "entities": ["..."],
    "specialist_result_id": "..."
  }
}
```

### Implementazione

Opzione iniziale conservativa:

- aggiungere `archive_identity_json JSON NULL` a `document_units`;
- non normalizzare subito in molte tabelle;
- proiettare successivamente in contexts/nodes/facts.

File:

- nuova migrazione Alembic;
- `packages/common/src/common/db/models.py`;
- `packages/common/src/common/db/schema.py`;
- nuovo servizio `common.application.archive_identity` oppure `knowledge_classifier.services.archive_identity`;
- pipeline `finalize_scan_topics`.

Azioni:

1. Aggiungere colonna JSON.

2. Implementare derivazione deterministica:

   - `document_family`: da document type + specialist type;
   - `context_key`: da entita' forti tipo condominio/indirizzo/immobile;
   - `primary_party_key`: vendor/issuer/amministratore/organizzazione principale;
   - `subject_key`: persona/intestatario/account subject;
   - `period_key`: periodo da specialist result o date OCR;
   - `matter_key`: solo per pratiche/issue ricorrenti.

3. Salvare sempre `confidence` e `evidence`.

4. Backfill con dry-run.

5. Usare `archive_identity` in topic retrieval:

   - prima match per assi;
   - poi titolo come fallback;
   - se assi forti confliggono, non matchare anche se titolo simile.

### Verifica

Test:

- utility bill Enel produce stessa `document_family` e `primary_party_key` su documenti diversi.
- bollette Enel di soggetti diversi differiscono per `subject_key`.
- documenti di condomini diversi non condividono `context_key`.
- rendiconto e riparto stesso condominio condividono `context_key` ma non necessariamente `document_family`.

Query:

```sql
SELECT
  archive_identity_json->>'document_family' AS family,
  archive_identity_json->>'primary_party_key' AS party,
  count(*)
FROM document_units
WHERE archive_identity_json IS NOT NULL
GROUP BY 1, 2
ORDER BY count DESC;
```

Target:

- almeno i documenti con specialist result hanno identity popolata;
- i documenti generici hanno identity parziale con confidence piu' bassa;
- nessun JSON senza `confidence`/`evidence`.

Definition of done:

- `archive_identity_json` presente e popolato per nuovi document unit.
- Backfill disponibile.
- Topic retrieval usa identity prima del titolo.

## Step 5 - Proposal Strutturate

### Problema

`TopicProposal.rationale` e' testo libero. Questo rende difficile capire se la proposta deriva da entita', titolo, contesto, famiglia o incertezza.

### Implementazione

Schema minimo:

- aggiungere `review_payload_json JSON NULL` a `topic_proposals`;
- oppure nome piu' specifico `proposal_factors_json`.

Payload:

```json
{
  "recommended_action": "attach_to_existing_topic",
  "matched_axes": ["document_family", "primary_party", "context"],
  "conflicting_axes": [],
  "missing_axes": ["period"],
  "candidate_topics_considered": [
    {
      "topic_id": "...",
      "score": 0.76,
      "matched_axes": ["context"],
      "conflicting_axes": ["primary_party"]
    }
  ],
  "confidence_factors": [
    "same normalized vendor",
    "same condominium context"
  ]
}
```

File:

- models/schema/migration;
- `TopicAssignmentDecision` schema in `knowledge_classifier/schemas.py`;
- prompt template;
- API serializer;
- `ProposalList` UI.

Azioni:

1. Estendere schema LLM senza rompere compatibilita': campi opzionali.

2. Popolare payload anche deterministicamente quando LLM non lo restituisce.

3. UI:

   - mostra chips per `matched_axes`;
   - mostra conflitti in rosso;
   - mostra azione raccomandata;
   - filtri: `create_topic`, `merge`, `attach_to_context`, `needs_review`.

4. API approve:

   - validare che l'azione scelta sia compatibile con payload, oppure chiedere override esplicito.

### Verifica

Test:

- parsing LLM con payload completo.
- fallback quando payload assente.
- serializer API include payload.
- UI build passa.

Query:

```sql
SELECT
  review_payload_json->>'recommended_action' AS action,
  count(*)
FROM topic_proposals
GROUP BY 1
ORDER BY count DESC;
```

Target:

- nuove proposal hanno `review_payload_json`.
- nessuna nuova proposal ha solo rationale testuale senza payload.

Definition of done:

- Proposal leggibili e filtrabili per causa.
- Rationale resta come spiegazione, ma non e' l'unica fonte decisionale.

## Step 6 - Backlog E Merge Tooling

### Problema

Lo stato esistente contiene topic frammentati, typo e topic puntuali gia' approvati.

### Implementazione

File:

- nuovo script `scripts/topic_cleanup_report.py`;
- possibile endpoint review in `services/api/src/api/routers/knowledge.py`;
- UI review panel.

Report dry-run:

```bash
scripts/topic_cleanup_report.py --json tmp/topic_cleanup.json
```

Categorie:

- topic con 0/1 assignment;
- topic con titolo normalizzato identico o quasi identico;
- topic con stesso `archive_identity` dominante;
- typo probabili contro entita' canoniche;
- topic con `topic_kind` incompatibile con document family dominante.

Azioni:

1. Implementare report read-only.

2. Aggiungere API per merge esplicito:

   ```text
   POST /api/knowledge/topics/{source_id}/merge
   target_topic_id
   acted_by
   note
   ```

   Deve:

   - spostare assignments;
   - spostare aliases;
   - aggiornare proposals;
   - marcare source inactive;
   - registrare audit in `graph_consolidation_reviews` o tabella dedicata.

3. UI batch:

   - mostra gruppi candidati;
   - azioni: merge, rename, change kind, reject suggestion.

### Verifica

Test:

- merge sposta assignments senza duplicati.
- source topic diventa inactive.
- aliases preservati.
- audit scritto.
- rollback manuale possibile via dati audit.

Query:

```sql
SELECT count(*) FROM topics WHERE is_active = false;

SELECT count(*)
FROM (
  SELECT document_unit_id, topic_id, assignment_role, count(*)
  FROM document_unit_topic_assignments
  GROUP BY document_unit_id, topic_id, assignment_role
  HAVING count(*) > 1
) d;
```

Metriche di successo:

- riduzione topic attivi/documenti.
- riduzione topic con un solo assignment.
- nessun aumento orfani.

Definition of done:

- Report dry-run ripetibile.
- Merge auditabile.
- Nessuna modifica automatica senza conferma umana.

## Step 7 - OCR Retry E Fallback

### Problema

Un errore OCR su singola pagina fallisce l'intero documento. I failure noti sono pagina-specifici.

### Implementazione

File:

- `packages/common/src/common/processing/dots_native.py`
- `packages/common/src/common/processing/backends.py`
- `services/worker/src/worker/tasks.py`
- schema OCR se serve salvare page errors strutturati.

Azioni:

1. Rendere l'OCR page-aware:

   - se una pagina fallisce, salvare errore pagina;
   - retry della pagina con backoff;
   - non perdere testo delle altre pagine.

2. Introdurre policy fallback:

   - fallback solo verso backend piu' conservativo o equivalente;
   - salvare `fallback_used`, `failed_pages`, `retry_count` in `confidence_summary` o `structured_json`.

3. Se una pagina resta fallita:

   - opzione A: job failed esplicito;
   - opzione B: OCR parziale con `status=partial` e scan/document unit `needs_review`.

   Raccomandazione: introdurre `partial` solo se UI/API lo espongono chiaramente.

### Verifica

Test unitari:

- backend simulato fallisce pagina 2 una volta, retry riesce.
- backend simulato fallisce sempre pagina 2, risultato `partial` o failure secondo policy.
- `confidence_summary` contiene failed/retried pages.

Test end-to-end:

- rieseguire i quattro documenti falliti.
- verificare che il job non fallisca per retry recuperabile.

Query:

```sql
SELECT status, count(*) FROM ingestion_jobs GROUP BY status;

SELECT error_message, count(*)
FROM ingestion_jobs
WHERE status = 'failed'
GROUP BY error_message
ORDER BY count DESC;
```

Definition of done:

- Errori pagina-specifici non sono invisibili.
- Retry/fallback e' tracciato.
- La UI/API non presentano OCR parziale come pienamente affidabile.

## Ordine Consigliato

1. Guardrail assegnazioni topic.
2. Titoli document unit.
3. Archive identity minima.
4. Topic meno centrali e topic assignment basato su identity.
5. Proposal strutturate.
6. Backlog/merge tooling.
7. OCR retry/fallback.

Questo ordine e' intenzionale: prima si impedisce nuova duplicazione, poi si migliora la navigazione umana, poi si introduce una base stabile per ridurre i topic.

## Criterio Finale Di Successo

Su un fixture set di regressione con bollette, rendiconti, verbali, regolamenti e comunicazioni generiche, il sistema deve soddisfare:

- ogni document unit ha titolo breve, summary, tipo documento e stato review;
- nessun duplicato in `document_unit_topic_assignments`;
- nessuna nuova bolletta/fattura singola crea topic canonico puntuale se esiste gia' contesto/famiglia/fornitore;
- le proposal hanno payload strutturato e sono filtrabili per azione;
- le risposte LLM possono citare facts/evidence con document unit, pagina e specialist result;
- la UI consente navigazione archivistica senza dipendere da JSON grezzo.
