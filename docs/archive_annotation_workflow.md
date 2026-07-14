# Annotazione del corpus archivistico

Il tool locale consente di completare le annotazioni umane richieste dalla Fase 0 senza caricare i PDF nel database. Corpus, manifest, hash, baseline e annotazioni restano completamente fuori dal repository.

## Avvio

```bash
python3 scripts/archive_annotation_server.py
```

Aprire `http://127.0.0.1:8765`.

Il corpus viene letto da `~/Pisa`; manifest, suggerimenti e lavoro umano si trovano per default in:

```text
~/.local/share/megadoc/archive-gold/
  archive_corpus.tsv
  page_annotations.json
  archive_human_annotations.json
  baselines/
```

La directory puo' essere cambiata con `MEGADOC_ARCHIVE_GOLD_DIR`. Non aggiungere questi file al repository.

Per usare percorsi o porte differenti:

```bash
MEGADOC_ARCHIVE_GOLD_DIR=/percorso/dati-gold \
python3 scripts/archive_annotation_server.py \
  --corpus-root /percorso/corpus \
  --manifest /percorso/dati-gold/archive_corpus.tsv \
  --output /percorso/dati-gold/archive_human_annotations.json \
  --port 8765
```

## Flusso rapido

Per ogni documento:

1. Verificare il suggerimento di orientamento e selezionare `Orientamento suggerito verificato`.
2. Indicare tipo principale, qualita', titolo minimo ed entita' chiave.
3. Correggere le entita' suggerite scegliendo sempre tipo e valore.
4. Aggiungere le document unit in ordine. Una unit rappresenta un documento logico completo: includere copertina, bollettino, dettagli e allegati necessari a interpretarlo. Gli intervalli devono coprire ogni pagina esattamente una volta.
5. Se una singola document unit e' payable o accounting, compilare lo specialista dentro quella unit. Un PDF misto puo' avere specialisti diversi per unit.
6. Annotare anomalie di scansione o ordine nelle note.
7. Premere `Completa e avanti`. L'azione resta bloccata finche' i dati non sono validi.

Scorciatoie:

- freccia destra/sinistra: documento successivo/precedente, quando il focus non e' in un campo;
- `Ctrl+S` o `Cmd+S`: salvataggio immediato;
- campo pagina sopra il PDF: navigazione diretta.

Le coordinate annotate sono sempre quelle del PDF originale mostrato nel viewer. I runner traducono queste coordinate nell'ordine OCR normalizzato quando il preprocessore ha invertito le pagine.

Per i payable annotare almeno tipo, emittente, destinatario, importo, valuta, scadenza e riferimento. Per l'accounting indicare le pagine con tabelle e almeno un controllo strutturato con pagina, identita' di riga, colonna e valore atteso. I campi legacy restano visibili solo per facilitare la migrazione.

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

Il file JSON risultante va revisionato e conservato insieme al corpus privato, ma non committato. Le annotazioni sono verita' attesa umana; non devono essere compilate copiando automaticamente l'output della pipeline.
