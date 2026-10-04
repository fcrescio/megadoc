# GLM-OCR e vLLM

Configurazione locale verificata il 2026-10-04:

- vLLM esterno: porta 18020, modello `qwen3.8-27b`, usato per knowledge,
  specialisti e analisi vision dell'agente.
- GLM-OCR esterno: repository `~/glm-ocr-service`, compose separato, porta 18030,
  modello `glm-ocr` con OpenVINO su Intel iGPU.
- I container Megadoc raggiungono entrambi tramite `host.docker.internal`.

Avviare GLM-OCR:

```bash
cd ~/glm-ocr-service
docker compose up -d --build
```

Il compose GLM locale per WSL2 passa `/dev/dxg` e monta sia `/usr/lib/wsl/lib`
sia `/usr/lib/wsl/drivers`. Quest'ultimo mount e' necessario per il driver Intel.
I pesi OpenVINO restano nel volume `models/glm-ocr-ov`; nessun modello entra in Git.

Configurare `.env` Megadoc:

```dotenv
OCR_BACKEND=glm_ocr
OCR_REMOTE_BACKEND=glm_ocr
OCR_GLM_ENDPOINT=http://host.docker.internal:18030/v1
OCR_GLM_MODEL=glm-ocr
OCR_GLM_TIMEOUT=600
KN_LLM_ENDPOINT=http://host.docker.internal:18020/v1
KN_WORKER_LLM_ENDPOINT=http://host.docker.internal:18020/v1
KN_LLM_MODEL=qwen3.8-27b
```

Endpoint e nomi modello sono modificabili anche in `/settings`: gli override nel
database prevalgono sull'ambiente. Il backend OCR attivo si sceglie in `.env`.
`OCR_REMOTE_BACKEND` mantiene il worker remoto allineato alla scelta globale.

GLM usa `Text Recognition:` con istruzione esplicita di conservare tabelle HTML
e testo Markdown. L'adattatore
Megadoc conserva il contenuto e separa le tabelle HTML e Markdown con riferimento alla pagina.
Una risposta troncata dal limite token produce errore esplicito: non viene salvata
come OCR completo. Il timeout e' 600 secondi per richiesta.

Il modello Qwen di chat non sostituisce un modello embedding. La configurazione
embedding precedente rimane separata e richiede un backend disponibile per la
ricerca semantica.

## Verifica eseguita

- OpenVINO nel container: `GPU` = Intel Graphics `[0xa780]`, CPU i7-13700K.
- Health GLM: `device=GPU`, caricamento in 11.37 secondi.
- Pagina sintetica: 15.89 secondi, importo `123,45 EUR` e data `31/12/2026`
  riconosciuti correttamente.
- Prima pagina di una scansione reale dell'archivio: 48.26 secondi, 1915
  caratteri, 624 token generati, circa 13 token/s. Sono presenti errori OCR nel
  testo degradato: non costituisce certificazione della qualita' del corpus.
- Qwen vision: chiamata immagine riuscita, stesso importo e stessa scadenza.
- API `/system/status`: OCR e LLM `ok`; worker remoto usa `GLMOCRService` e
  il knowledge worker legge il modello `qwen3.8-27b` dagli override DB.
- 16 test Python mirati e build frontend passati.

Limite strutturale misurato: con `Text Recognition:` una tabella sintetica
3x3 viene trascritta in righe di testo, senza HTML. Con `Table Recognition:` la
stessa immagine restituisce una tabella HTML corretta, ma omette il titolo esterno.
Con istruzioni esplicite di conservazione delle tabelle, la prova restituisce
titolo e tutte le celle in Markdown; l'adattatore converte la tabella in HTML
strutturato. Questa e' la configurazione attiva. La qualita' delle tabelle dense
reali richiede ancora valutazione: non si puo' assumere equivalenza con il layout
di dots. Nessun documento esistente
e' stato riprocessato o sovrascritto durante queste prove.
