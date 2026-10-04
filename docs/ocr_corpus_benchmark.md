# Confronto OCR sull'intero archivio dots

## Ambito

`scripts/benchmark_ocr_corpus.py` confronta ogni risultato `dots_native` presente
nel database con GLM SDK FP16 e con la variante INT8 del solo decoder.
Il database e lo storage originale sono usati soltanto in lettura. Non passa per
Celery, classificazione, specialisti o vLLM. Non sovrascrive l'OCR archiviato.

Il campione congelato il 2026-10-04 contiene 49 risultati, 48 documenti distinti
e 321 pagine. Non ci sono discrepanze fra conteggi PDF e pagine dello storico.
Un documento ha due run dots: vengono inclusi entrambi, ma raggruppati sotto lo
stesso documento per gli intervalli statistici.

## Comparabilita'

- Stesso PNG a 200 DPI inviato a entrambe le varianti, richieste sequenziali.
- Ordine FP16/INT8 alternato fra le coppie per ridurre il bias di ordine.
- Prima pagina di ogni risultato prima delle seconde: copertura iniziale ampia.
- Stesse configurazioni: SDK archivistico, soglia globale 0.3, nessuna soglia
  testuale sperimentale, max 8192 token per regione. Timeout pagina 1800 secondi.
- Riprodotti ordine e rotazioni accettate nello storico, incluse rotazioni per
  pagina del renderer dots. Nessuna correzione upright manuale in questo run.
- Confronto fra stack: risoluzione, layout e formato GLM non sono quelli di dots.
  Non isola l'effetto del solo riconoscitore.
- Modelli e processor identificati mediante SHA256; i componenti diversi dal
  decoder devono coincidere. Image Docker e hash del codice registrati.
- Ogni risposta viene controllata rispetto alle impostazioni congelate: un cambio
  dei parametri del servizio viene registrato come errore, non mescolato ai risultati.
- Container dedicati su porte 18032 (FP16) e 18031 (INT8), separati dal servizio
  di produzione sulla 18030. Possono comunque contendere la iGPU con altri carichi:
  i tempi non sono un benchmark hardware certificato.

## Cosa misurano le statistiche

Dots NON e' una trascrizione gold. Le misure sono concordanza, non accuratezza:

- Concordanza della sequenza di parole e F1 delle occorrenze di parole.
- Occorrenze numeriche condivise, frazione di numeri dots recuperati e frazione
  di numeri GLM presenti anche in dots; nessuna interpretazione finanziaria automatica.
- Testo e multiset numerico identici fra FP16 e INT8 dopo normalizzazione del testo.
- Numero tabelle, righe e celle fisiche; i colspan non vengono espansi in celle
  artificiali. Il diverso layout puo' cambiare questi conteggi senza essere errato.
- Tempi, fallimenti, pagine senza baseline corrispondente e troncamenti.
- Stratificazione fra pagine con e senza tabelle nello storico.
- Differenze FP16/INT8 rispetto a dots su coppie riuscite, media per documento
  e bootstrap al 95% su documenti, non su pagine. Il campione e' l'archivio locale:
  gli intervalli non dimostrano generalizzazione ad altri archivi.

Markdown e HTML vengono normalizzati; riferimenti a immagini esclusi. La
spaziatura e i separatori numerici restano un limite: una data attaccata a una
parola o una cifra con separatori diversi puo' ridurre la concordanza senza
essere un errore di lettura. Non concludere che il motore piu' simile a dots
sia necessariamente migliore. Per attribuire i disaccordi occorre leggere la fonte.

## Evidenze locali e monitoraggio

Materiale privato sotto `~/megadoc-ocr-benchmarks/2026-10-04-corpus-fp16-int8/`,
mai in Git:

- `manifest.json`: tutti gli id storici, checksum, conteggi e impostazioni.
- `model-manifest.json`: checksum dei modelli e image runtime.
- `current.json`: pagina e variante attualmente in elaborazione.
- `summary.json` e `REPORT.md`: stato, statistiche parziali/finali.
- `<ocr-result-id>/dots.json`, `original.pdf`, `normalized.pdf`, `page_mapping.json`.
- `<ocr-result-id>/page-NNNN-{fp16,int8}.json`: risposta, layout, tempi ed errori.
- `<ocr-result-id>/pair-NNNN.json`: confronto della coppia e profili tabelle.

I checkpoint includono anche gli errori: una ripartenza non ripete automaticamente
le richieste gia' concluse. Le pagine successive continuano dopo un errore isolato.
Una coppia incompleta riusa la variante gia' salvata. `finished_with_failures`
significa tutte le pagine tentate, non successo completo. `interrupted` indica
un problema del runner che richiede ispezione dei log.

```bash
docker logs --tail 30 megadoc-ocr-corpus-benchmark
cat ~/megadoc-ocr-benchmarks/2026-10-04-corpus-fp16-int8/REPORT.md
cat ~/megadoc-ocr-benchmarks/2026-10-04-corpus-fp16-int8/current.json
```

Il benchmark e' un job Docker indipendente, non compare come ingestion job nella
UI. Le statistiche parziali possono essere sbilanciate: soprattutto il primo
giro comprende soltanto le prime pagine. Non presentarle come risultato finale.

## Lancio E Ripresa

Prima creare il manifest modelli con `glm-ocr-service/scripts/model_fingerprint.py`
e avviare le due varianti dedicate. `--prepare-only` congela l'archivio senza OCR.
Il runner richiede che codice e configurazione coincidano col manifest; dopo
modifiche comportamentali creare una directory di esperimento nuova.

```bash
docker compose run -d --no-deps --name megadoc-ocr-corpus-benchmark \
  --user "$(id -u):$(id -g)" \
  -v "$PWD":/app:ro \
  -v "$HOME/megadoc-ocr-benchmarks/2026-10-04-corpus-fp16-int8":/evidence \
  api python -u scripts/benchmark_ocr_corpus.py \
  --output /evidence --model-manifest /evidence/model-manifest.json
```

Se il container si interrompe, controllare stato dei backend e log. `docker start
megadoc-ocr-corpus-benchmark` riprende dai checkpoint; non cancellare i risultati
parziali per ripartire. I container backend `glm-ocr-corpus-fp16` e
`glm-ocr-corpus-int8` hanno restart policy `unless-stopped`. Il runner termina
normalmente e non si riavvia automaticamente a confronto completato.

A fine prova conservare le evidenze e rimuovere soltanto i container dedicati,
senza fermare il servizio di produzione. Se il runner viene interrotto mentre
una richiesta e' in corso, attendere che l'inferenza dedicata finisca prima della
ripresa: il timeout HTTP non cancella il lavoro GPU sul server.
