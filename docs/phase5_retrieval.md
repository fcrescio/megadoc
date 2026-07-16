# Fase 5 - Retrieval evidence-first

Stato al 2026-07-16: implementazione core completata; certificazione sul gold set in attesa delle domande umane.

## Implementato

- `RetrievalService` unico con risultati normalizzati, Reciprocal Rank Fusion e diversificazione per documento/pagina.
- Tool agente `retrieve_evidence`, usato come ricerca primaria globale o limitata a un documento.
- Evidenze indicizzate per topic, document unit, pagina OCR e ultimo risultato specialistico.
- Tabelle accounting indicizzate per pagina con spiegazione LLM; bollette indicizzate con fornitore, importo e scadenza.
- Canale lessicale Postgres full-text + trigram e canale vettoriale pgvector isolato per modello embedding.
- Chunk OCR sovrapposti e limitati a 400 caratteri per coprire tutta la pagina rispettando il limite fisico del modello embedding.
- Refresh idempotente per documento, freshness osservabile e worker Celery dedicato `search_index`.
- Refresh automatico dopo la finalizzazione knowledge e specialistica del documento.
- Tool agente `query_accounting_tables`, delegato al motore contabile deterministico esistente.
- Runner privato `scripts/evaluate_retrieval_gold.py` per recall@5, recall@10 e latenza p50/p95.

## Verifica eseguita

- 21 test focalizzati passati.
- Migrazione Alembic `20260716_0018` applicata; estensioni `vector` e `pg_trgm` presenti.
- Rebuild completo: 3.442 chunk persistiti sul corpus corrente; indice non stale.
- Query campione ibride: circa 0,21-0,23 secondi, 30 candidati lessicali e 30 semantici, nessun warning.
- Refresh asincrono reale consumato dalla coda `search_index` e completato in 1,08 secondi su un documento piccolo.
- Un refresh per documento sostituisce i chunk precedenti prima dell'insert, evitando residui dopo reprocessing.

## Criterio di chiusura

Eseguire, quando il file privato contiene almeno 30 domande annotate:

```bash
docker run --rm --user root -w /app \
  -v "$PWD":/app \
  -v "$HOME/.local/share/megadoc/archive-gold:/gold:ro" \
  --network megadoc-net \
  megadoc-api python scripts/evaluate_retrieval_gold.py \
  --annotations /gold/archive_human_annotations.json \
  --database-url postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc \
  --api-base-url http://api:8080
```

Target:

- recall@5 >= 90%;
- recall@10 >= 95%;
- latenza p95 < 2 secondi;
- nessun `case_id` irrisolto e nessun warning di canale.

Il gold corrente ha zero domande, quindi questi target non sono ancora misurabili. Un reranker cross-encoder o LLM va aggiunto solo se il runner dimostra che RRF non raggiunge il recall richiesto: introdurlo prima aumenterebbe latenza e complessita' senza un difetto misurato.
