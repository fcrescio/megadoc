# Fase 7 - Throughput, recovery e osservabilita'

Stato al 2026-07-17: base operativa implementata; load test distruttivo non eseguito automaticamente.

## Funzioni disponibili

- `GET /jobs/metrics?hours=24`: throughput, attesa e durata p50/p95, job attivi e classi di fallimento.
- `GET /jobs/background-activity`: ETA, posizione in coda, motivo dell'attesa e dead-letter operative.
- `POST /jobs/{pipeline}/{job_id}/replay`: replay idempotente di ingestion, knowledge full processing e specialisti falliti.
- UI lavori background: throughput, durata media, ETA, motivo d'attesa e pulsante `Riprova job`.
- Backoff esponenziale con jitter deterministico e limite di 15 minuti per knowledge, finalizzazione, search index e specialisti.
- `scripts/pipeline_consistency_probe.py`: verifica orfani e duplicati attivi dopo restart/replay.
- `scripts/batch_load_probe.py`: sampling stratificato e load test opt-in.

## Verifica non distruttiva

```bash
docker run --rm --user root -w /app -v "$PWD":/app --network megadoc-net \
  megadoc-api python scripts/pipeline_consistency_probe.py \
  --database-url postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc
```

Il probe corrente riporta zero orfani e zero job attivi duplicati.

Preparare il piano di carico senza caricare documenti:

```bash
docker run --rm --user root -w /app -v "$PWD":/app -v "$HOME/Pisa:/corpus:ro" \
  megadoc-api python scripts/batch_load_probe.py /corpus --limit 500
```

L'upload parte soltanto aggiungendo `--execute`. Va eseguito su un database dedicato o dopo backup esplicito: produce documenti e job reali.

## Criteri ancora da certificare

- kill/restart controllato durante OCR, knowledge e specialisti;
- almeno 500 PDF su database di prova;
- 99% dei job terminali o visibili nella dead-letter;
- drenaggio automatico dopo indisponibilita' e ripristino del backend ML;
- throughput e p95 registrati sull'hardware target.

Questi test modificano stato e tempi del sistema e non devono essere eseguiti implicitamente sul database archivistico corrente.
