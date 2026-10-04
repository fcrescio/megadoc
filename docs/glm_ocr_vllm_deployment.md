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

GLM usa il prompt nativo `Text Recognition:` e restituisce Markdown. L'adattatore
Megadoc conserva il contenuto e separa le tabelle HTML con riferimento alla pagina.
Una risposta troncata dal limite token produce errore esplicito: non viene salvata
come OCR completo. Il timeout e' 600 secondi per richiesta.

Il modello Qwen di chat non sostituisce un modello embedding. La configurazione
embedding precedente rimane separata e richiede un backend disponibile per la
ricerca semantica.
