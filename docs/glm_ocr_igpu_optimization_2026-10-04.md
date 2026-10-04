# GLM-OCR: profiling iGPU e copertura del layout

## Ambito

Esperimenti OCR isolati, senza vLLM, senza modificare l'archivio. Baseline:
SDK archivistico, 200 DPI, OpenVINO FP16 su UHD 770, soglia layout 0.3.
Il servizio di produzione resta FP16. Evidenze private fuori Git sotto
`~/megadoc-ocr-benchmarks/2026-10-04-profile-{fp16,int8}/` e
`~/megadoc-ocr-benchmarks/2026-10-04-layout-probe/`.

## Profiling implementato

Il microservizio restituisce i tempi per regione, dimensioni dei crop,
`layout_s`, regioni originali con confidence e blocchi intenzionalmente saltati.
Non e' un profiler GPU: sono tempi wall-clock alle interfacce sincrone Optimum.
`multimodal_s` include vision e preparazione degli embedding, `prefill_s` il
primo forward del language model, `decode_s` i forward successivi. Il residuo
include generazione Python, elaborazione token e formattazione.

| Documento | Layout | Multimodale | Prefill | Decode | Totale client |
| --- | --- | --- | --- | --- | --- |
| Preventivo FP16 | 0.71 s | 7.34 s | 3.17 s | 18.91 s | 30.78 s |
| Preventivo INT8 | 0.87 s | 7.96 s | 2.95 s | 12.69 s | 25.21 s |
| Quadro economico FP16 | 0.67 s | 38.66 s | 6.07 s | 54.53 s | 100.95 s |
| Quadro economico INT8 | Non isolato qui | 38.30 s | 4.33 s | 35.33 s | 79.94 s |

Il layout non domina questi casi. Nelle tabelle il costo vision e' significativo:
ottimizzare soltanto il decoder lascia circa 38 secondi di costo multimodale.

## Compressione INT8

Nuovo script `glm-ocr-service/scripts/compress_decoder.py`: comprime i soli pesi
del language model con NNCF INT8 asymmetric per-channel; copia gli altri componenti
senza cambiarli. Richiede un output nuovo, fuori dalla directory sorgente.
Pesi decoder: circa 1.1 GB FP16 contro 557 MB INT8. Variante privata in
`~/glm-ocr-service/models/glm-ocr-int8/`, non versionata.

La prova usa un container temporaneo su porta 18031, con stessi PDF normalizzati,
stesso processor, stesso layout e parametri di generazione. Un solo esperimento
inferenziale attivo per volta. Il servizio normale sulla 18030 resta disponibile
ma non e' stato interrogato durante le misure comparative.

Risultati: tempo ridotto del 18% sul preventivo e del 21% sul quadro economico.
Il testo completo della tabella economica e' identico alla baseline FP16.
Nel preventivo cambiano la spaziatura di una partita IVA e la trascrizione di
una firma manoscritta, gia' inaccurata in FP16. Non si certifica equivalenza
qualitativa, ne' un guadagno universale: una sola esecuzione per configurazione
e due documenti non bastano per promuovere la variante in produzione.

## Diagnosi delle omissioni

Nelle bollette mancavano un conto postale (pagina 1) e l'intestazione del
fornitore (pagina 3). Nessuna regione SDK copriva queste aree. Riconoscendo crop
espliciti, GLM FP16 recupera entrambi correttamente: evidenza di un limite del
layout in questi casi, non del riconoscitore su quei crop.

Diagnostico CPU `scripts/probe_layout.py` sulle due pagine upright:

- Soglia standard 0.3: 12 regioni per pagina; entrambe le aree assenti.
- Soglie globali 0.2 e 0.1: emergono tabelle quasi a pagina intera, confidence
  0.284 e 0.211, che cambiano drasticamente la segmentazione. Non adottate.
- Soglia 0.1 solo per classi testuali: rilevate le aree mancanti con confidence
  0.197 e 0.229, senza abbassare la soglia delle tabelle. Compare anche un'area
  marginale a bassa confidence: non assumere che tutte le nuove regioni siano utili.

Opzione sperimentale `--layout-text-threshold` separata dal default e tracciata
nella risposta; validazione range e test che table/image non cambino soglia.
Non e' un fallback e non forza l'OCR delle figure: modifica esplicitamente una
decisione del modello di layout, lasciando la classificazione LLM invariata.

Prova completa a soglia testuale 0.15, FP16, sulle quattro pagine upright:
93.77 secondi contro 91.14 della baseline. Tutti i 16 campi critici rimangono
presenti; fornitore e conto postale presenti su tutte e quattro le pagine
(24/24 controlli complessivi). La tabella della quarta pagina resta estratta.
La differenza di tempo non e' significativa con una sola esecuzione; non sono
stati certificati gli altri testi. Evidenze in
`~/megadoc-ocr-benchmarks/2026-10-04-text015-upright/`.
La soglia rimane opt-in per evitare regressioni non misurate sulle altre famiglie.

## Verifica e passi successivi

- Test del profiling: conteggio forward e ripristino dei metodi anche su errore.
- Test di contratto API e parsing SDK passati, inclusi auth e troncamenti.
- Microservizio ricostruito e health con tutti i componenti su GPU.0.
- Richiesta reale al servizio ricostruito verifica tempi e confidence nella risposta.
- Megadoc conserva le confidence originali, regioni saltate e tempo layout
  nei metadati della pagina; non li proietta in fatti autoritativi.
- 17 test Megadoc mirati passati; API e worker OCR remoto ricostruiti.
- Database OCR invariato: 49 risultati, fingerprint
  `6004465a8613c4677eb3f80b464705fc`.

Commit atomici del microservizio, pubblicati su `origin/main`: `3682a57`
(profiling), `a0cf454` (compressione separata), `26684dc` (diagnostico layout),
`9bbafe5` (soglie testuali opt-in), `5b446a8` (risultati sanitizzati).
Megadoc `5b3dca8` conserva le evidenze diagnostiche nell'output OCR.

Prima di promuovere INT8: ampliare il campione, annotare importi/date/celle,
confrontare errori e ripetere le misure warm. Poi valutare INT4 decoder e precisione
KV cache come variabili separate. Non abbassare la risoluzione insieme alla
quantizzazione: rende impossibile attribuire regressioni.

Prima di promuovere soglie testuali inferiori: verificare le quattro pagine
bollette e un campione di altre famiglie, misurando omissioni e regioni spurie.
Le evidenze non dimostrano ancora parita' generale con dots o con PyTorch nativo.
