# Annotazione del corpus archivistico

Il tool locale consente di completare le annotazioni umane richieste dalla Fase 0 senza caricare i PDF nel database e senza copiarli nel repository.

## Avvio

```bash
python3 scripts/archive_annotation_server.py
```

Aprire `http://127.0.0.1:8765`.

Il corpus viene letto da `~/Pisa`; il lavoro viene salvato automaticamente e atomicamente in:

```text
tests/gold/archive_human_annotations.json
```

Per usare percorsi o porte differenti:

```bash
python3 scripts/archive_annotation_server.py \
  --corpus-root /percorso/corpus \
  --output /percorso/annotazioni.json \
  --port 8765
```

## Flusso rapido

Per ogni documento:

1. Verificare il suggerimento di orientamento e selezionare `Orientamento suggerito verificato`.
2. Indicare tipo principale, qualita', titolo minimo ed entita' chiave.
3. Aggiungere le document unit in ordine. Gli intervalli devono coprire ogni pagina esattamente una volta.
4. Se il documento e' payable o accounting, compilare i campi specialistici mostrati.
5. Annotare anomalie di scansione o ordine nelle note.
6. Premere `Completa e avanti`.

Scorciatoie:

- freccia destra/sinistra: documento successivo/precedente, quando il focus non e' in un campo;
- `Ctrl+S` o `Cmd+S`: salvataggio immediato;
- campo pagina sopra il PDF: navigazione diretta.

Nel tab `Domande`, aggiungere almeno 30 domande archivistiche. Una domanda rispondibile richiede risposta attesa ed evidenza nel formato:

```text
case_id:pagina
case_id:pagina-iniziale-pagina-finale
```

Le domande senza risposta devono avere `Rispondibile` disabilitato.

## Criterio di chiusura

Eseguire:

```bash
python3 scripts/validate_archive_annotations.py
```

Il comando termina con successo soltanto quando:

- tutti i 27 documenti sono revisionati;
- orientamento, tipo e titolo sono confermati;
- le document unit coprono tutte le pagine senza lacune o sovrapposizioni;
- sono annotati almeno 10 payable e 10 documenti accounting;
- i campi specialistici obbligatori sono presenti;
- sono presenti almeno 30 domande con risposta/evidenza coerente.

Il file JSON risultante va revisionato e committato come parte del corpus gold. Le annotazioni sono verita' attesa umana; non devono essere compilate copiando automaticamente l'output della pipeline.
