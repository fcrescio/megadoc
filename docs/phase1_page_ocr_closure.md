# Chiusura Fase 1 - Contratto pagina e OCR adattivo

La Fase 1 e' chiusa strutturalmente. Il gold privato resta esterno al repository e viene usato solo dal runner on demand.

## Contratto implementato

- `PageArtifactModel` rappresenta ogni pagina con testo, markdown, struttura, dimensioni, origine, classe, backend, versione, rotazione, confidence e quality flags.
- `OCRService` materializza `structured_json.page_artifacts` prima di persistere un nuovo risultato.
- `scripts/backfill_page_artifacts.py` rende conformi i risultati OCR storici senza rieseguire OCR.
- Le classi canoniche sono `native`, `scan`, `hybrid`, `low_quality`, `failed` e `unknown`.
- Una pagina senza testo e' `failed` e conserva `empty_text`; una pagina incerta resta visibile tramite quality flags e review.
- Preflight e orientamento vengono conservati nel risultato OCR e negli artifact per pagina.
- Docling conserva il percorso ibrido testo nativo/OCR; Dots e vision sono backend OCR espliciti.
- Dots applica retry su errori trasporto e HTTP temporanei con timeout e backoff configurabili; il refinement vision seleziona solo pagine degradate.

## Certificazione

Il runner confronta il database con `page_annotations.json` privato:

```bash
docker run --rm --user root --network megadoc-net -w /app \
  -v "$PWD":/app \
  -v "$HOME/.local/share/megadoc/archive-gold":/gold:ro \
  -e DATABASE_URL=postgresql+psycopg://megadoc:megadoc@megadoc-postgres-1:5432/megadoc \
  megadoc-api python scripts/evaluate_page_artifacts.py \
  --annotations /gold/page_annotations.json
```

Usare `--require-all` per la campagna completa: in questa modalita' il runner fallisce se un documento annotato non e' caricato nel database.

Baseline di chiusura del 12 luglio 2026 sul sottoinsieme caricato:

- 4 documenti image-only, 48 pagine;
- 48/48 page artifact materializzati;
- 48/48 pagine con provenance nota;
- 16/16 campioni di orientamento corretti;
- zero pagine fallite silenziosamente;
- ramo PDF nativo non presente nel sottoinsieme reale, coperto da test deterministici del contratto.

## Criteri di mantenimento

- Ogni nuovo OCR deve avere tanti page artifact quante sono le pagine dichiarate.
- `unknown` non e' provenance sufficiente per una baseline certificata.
- Le pagine `failed` devono essere esplicitamente visibili e revisionabili.
- L'accuratezza orientamento minima resta 99% sui campioni non ambigui.
- Il corpus privato puo' crescere senza modificare il runner o versionare documenti e annotazioni sensibili.
- L'aggiunta di PDF nativi al gold rendera' non vacuo il controllo `native_documents_without_ocr`; non richiede ulteriori modifiche strutturali.
