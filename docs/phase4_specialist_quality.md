# Fase 4: qualita' specialisti

La verifica degli specialisti usa le annotazioni private in `~/.local/share/megadoc/archive-gold`. Il corpus e i risultati contenenti valori estratti non vanno committati.

## Runner

Il runner invoca gli handler direttamente sui range pagina umani. In questo modo misura lo specialista separatamente da segmentazione, classificazione e routing. Quando l'OCR ha invertito l'ordine delle pagine, converte le coordinate del PDF originale in coordinate OCR e conserva entrambe nel report.

```bash
docker run --rm --user root --network megadoc-net \
  -e DATABASE_URL='postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc' \
  -v "$PWD:/app" \
  -v "$HOME/.local/share/megadoc/archive-gold:/gold:ro" \
  -w /app megadoc-api \
  python scripts/evaluate_specialist_gold.py \
  --annotations /gold/archive_human_annotations.json \
  --accounting-llm
```

Il report misura:

- accuratezza dei campi payable obbligatori e degli opzionali effettivamente annotati;
- accuratezza dei campioni accounting a livello di cella;
- presenza della lineage per ogni valore corretto;
- numero di casi non caricati, che impedisce il superamento del gate.

Omettere `--accounting-llm` per un baseline deterministico rapido. Il gate completo usa il flag, che riutilizza endpoint, modello e timeout del worker accounting.

Le soglie iniziali sono `95%` per i payable, `98%` per le celle accounting e `100%` per la lineage. Un fallimento deve restare visibile: non correggere il gold copiando l'output automatico e non allargare pattern numerici non ancorati per far passare un documento.

## Interpretazione

Un errore di pagina richiede prima di controllare `orientation_preprocess.page_order_reversed`. Un campo payable errato va distinto da una document unit incompleta. Un controllo accounting fallito puo' indicare estrazione tabellare errata, OCR errato o annotazione ambigua; il report restituisce pagina, tabella, riga e colonna quando trova la cella.

Le correzioni devono preservare i valori raw. Riconciliazioni LLM e correzioni umane restano layer separati e verificabili.
