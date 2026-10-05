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

### Confronto solo INT8 e diagnosi del run precedente

Dal 2026-10-05 `--variant int8` esclude FP16 dalle richieste e dalle statistiche.
Le misure restano confronti con dots, senza inventare coppie FP16/INT8. Ogni
variante ha anche la concordanza media per documento e bootstrap a livello di
documento. Conservare sempre il run precedente: non sovrascriverne i checkpoint.

Il run del 4 ottobre ha prodotto solo 31 pagine INT8 riuscite su 321. Il resto
mescola errori di estrazione e guasti del backend: non costituisce una misura
affidabile della qualita' sull'archivio. La diagnosi controllata sul servizio
OpenVINO ha riprodotto due allocazioni superiori al limite di 1 GiB della UHD 770:
maschera vision quadratica da 1.53 GB e logits del prompt da 1.17 GB. Dopo il
secondo errore il riuso del decoder provoca un segfault in due processi distinti.
Gli errori storici di reshape/broadcast non sono ancora riprodotti esattamente.

Le correzioni equivalenti (maschera zero broadcast per singola immagine e testa
vocabolario applicata solo all'ultimo token) non ridimensionano le scansioni.
Una regressione SDK completa su una tabella economica riesce due volte e produce
testo identico alla precedente estrazione INT8 riuscita. La riproduzione della
grande pagina con 32 token dimostra invece solo il superamento dei limiti di
allocazione, **non** un OCR completo. Diagnostica e limiti sono documentati nella
repo `glm-ocr-service`, `docs/igpu-allocation-diagnostic-2026-10-05.md`.

Usare un solo modello residente. L'override `compose.int8.yml` del microservizio
attiva INT8 e le due correzioni sulla porta normale 18030. Il manifest modelli
deve essere generato con `--compact-vision-mask --last-token-logits` e l'image ID
effettivamente distribuito. Nel runner aggiungere:

```bash
--variant int8 --int8-endpoint http://host.docker.internal:18030/v1
```

Un errore isolato di estrazione 502 continua solo se `/health` risponde sano.
Errori di rete, runtime non sano, autenticazione, configurazione diversa o risposte
invalide fermano il confronto dopo aver salvato la pagina: niente cascata di
centinaia di errori fittizi. Lo stato `interrupted` richiede diagnosi e riavvio
esplicito, non retry nascosti. L'archivio storico resta in sola lettura.

Il troncamento storico e' stato riprodotto anche col runtime corretto: 544 righe
HTML vuote identiche, nessuna chiusura della tabella e 8192 token dopo 446.70 s.
Il controllo OCR successivo riesce: e' un ciclo di generazione, non un backend
guasto. Payload e testo incompleto sono conservati nella diagnostica privata;
la causa del ciclo non e' ancora isolata. Non aumentare il budget e chiamarlo fix.

Nuovo run avviato in `~/megadoc-ocr-benchmarks/2026-10-05-corpus-int8/`, container
`megadoc-ocr-corpus-int8-benchmark`, backend unico su 18030. Contiene gli stessi
49 risultati dots / 48 documenti / 321 pagine. Il run precedente e il database
sono preservati. Per il monitoraggio:

```bash
docker logs --tail 30 megadoc-ocr-corpus-int8-benchmark
cat ~/megadoc-ocr-benchmarks/2026-10-05-corpus-int8/REPORT.md
cat ~/megadoc-ocr-benchmarks/2026-10-05-corpus-int8/current.json
```

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
