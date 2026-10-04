# GLM-OCR: allineamento SDK e verifica iGPU

## Obiettivo e configurazione

Sostituire il riconoscimento dell'intera pagina con il percorso pubblico del
[SDK ufficiale](https://github.com/zai-org/GLM-OCR), fissato alla revisione
`cef4d0ea120d1741f5cefe8985eee45f6c8eff1d` (versione 0.1.5).
La configurazione e' confrontabile per pipeline, non per hardware o throughput
con i benchmark pubblicati nella [model card](https://huggingface.co/zai-org/GLM-OCR).

- PP-DocLayoutV3 su CPU rileva e ordina le regioni.
- GLM-OCR OpenVINO FP16 su Intel UHD 770 riconosce ciascuna regione.
- Prompt SDK distinti: testo, tabella, formula; niente prompt generico di recupero.
- Render Megadoc a 200 DPI, limite 8192 token per regione, nessun cap aggiuntivo
  a 700000 pixel. Restano i limiti del processor del modello.
- Un solo riconoscimento alla volta: evita contesa sulla iGPU.
- Profilo archivistico esplicito: conserva intestazioni, pie' di pagina e note.
  Il comportamento standard del SDK, disponibile senza questo profilo, ne scarta
  alcune categorie e non e' appropriato come default per il nostro archivio.
- Errori regionali e troncamenti interrompono la richiesta: nessun fallback
  verso Qwen o altro motore, nessun risultato parziale dichiarato completo.
- `/health` conferma `GPU.0` per language, text embeddings, vision e merger.
  Il layout CPU non usa la NVIDIA. Il servizio non dipende da vLLM.

## Modifiche e rollback

Repository `glm-ocr-service`, commit atomici pubblicati su `origin/main`:

| Commit | Contenuto |
| --- | --- |
| `7ab7721` | Pipeline SDK con riconoscimento OpenVINO locale |
| `a1d9081` | Endpoint autenticato `/v1/parse`, Docker, contratti e documentazione |
| `9a7634b` | Profilo archivistico per preservare il testo marginale |
| `f6c5698` | Distinzione fra immagini saltate dal SDK ed errori di riconoscimento |

Megadoc:

| Commit | Contenuto |
| --- | --- |
| `5a3d739` | Adapter SDK con regioni, tabelle e coordinate |
| `b2b875c` | Motivo preciso degli errori regionali nei fallimenti di ingestione |
| `a07ff51` | Benchmark selettivo per backend e rendering SDK registrato |

Il servizio esterno, API Megadoc e worker OCR remoto sono stati ricostruiti.
Nessun documento dell'archivio e' stato sovrascritto o accodato per ingestione.

## Prove riproducibili senza vLLM

Il comando `scripts/compare_archived_ocr.py --backend glm` usa soltanto GLM;
il riferimento dots e' una copia del risultato gia' archiviato, non una chiamata
al vecchio server. PDF, snapshot e risposte sono fuori Git, sotto
`~/megadoc-ocr-benchmarks/2026-10-04-sdk-archive/`.

| Tipo | Pagine | GLM iniziale | SDK archivistico | Esito osservato |
| --- | --- | --- | --- | --- |
| Preventivo | 1 | 32.2 s | 31.2 s | Intestazione conservata, 14/14 occorrenze numeriche dello storico presenti |
| Quadro economico | 1 | 48.2 s | 100.7 s | Tabella HTML, 15 importi presenti, descrizioni con qualificazioni; restano difetti di spaziatura |
| Verbale ed estratto conto | 3 | 186.6 s | 248.7 s | Due tabelle strutturate; totale presenze e chiusura conto inclusi nelle tabelle |
| Bollette, orientamento corretto | 4 | Non confrontabile con la prova originale ruotata | 91.1 s | 16/16 campi critici presenti nella rispettiva pagina |

La prova bollette e' in
`~/megadoc-ocr-benchmarks/2026-10-04-sdk-archive-upright/`, con rotazioni
esplicite `270,270,90,90` e solo `--backend glm`. Controllati su ciascuna pagina:
importo, scadenza, numero fattura e codice utente. Non equivale a completezza
del documento: nella terza pagina manca l'intestazione del fornitore e nella
prima manca il numero del conto postale. Alcune regioni sono classificate come
immagine e quindi non riconosciute; serve un controllo specifico di copertura
del layout, non un fallback indiscriminato dell'intera pagina.

Confronto fra stack di produzione: il vecchio wrapper usava una risoluzione e
un prompt diversi. Questi tempi non isolano l'effetto del solo motore.
La concordanza automatica con dots NON e' accuratezza: ad esempio date scritte
senza spazi in HTML alterano il conteggio regex dei numeri. Restano errori OCR
e trascrizioni spurie nelle firme manoscritte. Non e' una certificazione gold.

La tabella economica impiega 96.3 s nella sola regione tabellare (872 token
generati) su 100.5 s server totali. Nell'estratto conto la regione tabellare
impiega 86.4 s (1037 token) su 96.7 s della pagina. Il tempo residuo comprende
altre regioni, layout, preparazione e formattazione: non e' una misura diretta
del solo layout CPU. Il collo di bottiglia osservato e' il riconoscimento iGPU,
non vLLM o una richiesta verso la NVIDIA.

Una prova intermedia ha fallito per un controllo errato sui blocchi immagine
intenzionalmente saltati dal SDK. Corretto in `f6c5698` e coperto da test;
quel fallimento non va conteggiato come errore OCR del modello.

## Verifica e limiti

- Test di contratto del microservizio e test del parsing SDK passati.
- 16 test Megadoc mirati passati: adapter, benchmark, dispatch e runtime settings.
- Health runtime con dispositivi effettivamente compilati, non solo richiesti.
- Snapshot del database OCR invariato: 49 risultati, fingerprint
  `6004465a8613c4677eb3f80b464705fc`.
- Nessuna accelerazione dimostrata: migliorata la struttura, due casi piu' lenti.
- Non e' stato fatto un confronto degli stessi crop con PyTorch di riferimento;
  non possiamo ancora attribuire gli errori residui a OpenVINO.
- L'orientamento delle bollette resta una verifica separata: la prova upright
  usa rotazioni esplicite, non dimostra correttezza della preflight automatica.
- Il profilo archivistico puo' trascrivere segni marginali come testo spurio:
  preservazione e qualita' del riconoscimento sono proprieta' distinte.

Per ulteriori prove mantenere questi parametri come baseline; cambiare una sola
variabile alla volta e conservare crop, token e tempi per regione. Non aumentare
la concorrenza prima di aver misurato memoria e latenza sulla iGPU.
