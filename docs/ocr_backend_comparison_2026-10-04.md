# Confronto OCR GLM e Qwen

Prova locale del 2026-10-04. GLM-OCR gira in Docker su OpenVINO 2026.4 e Intel
UHD 770; Qwen `qwen3.8-27b` gira su vLLM porta 18020 e RTX 4090.

## Verifica del dispositivo

OpenVINO rileva `GPU` come Intel Graphics `[0xa780] (iGPU)`. L'endpoint
`http://localhost:18030/health` espone i dispositivi dei modelli compilati:

```json
{"execution_devices":{"language":["GPU.0"],"text_embeddings":["GPU.0"],"vision":["GPU.0"],"vision_merger":["GPU.0"]}}
```

La proprieta' deriva da `CompiledModel.get_property("EXECUTION_DEVICES")`, non
dalla sola opzione CLI. Il container usa `/dev/dxg` e i driver WSL, senza richieste
di GPU NVIDIA. CPU e PyTorch CPU restano coinvolti nel preprocessing.

## Metodo

Stessi byte PNG per entrambi i server, rendering PDF a scala 1.5, limite 700000
pixel e dimensioni multiple di 28. Temperatura zero, limite 4096 token e reasoning
Qwen disabilitato. Richieste seriali. Tempi end-to-end osservati su singole
chiamate, non medie statistiche; la compilazione OpenVINO era gia' completata.

Prompt comune iniziale:

```text
Text Recognition: Preserve tables as HTML and all other text as Markdown.
```

| Campione | GLM | Qwen | Esito |
|---|---:|---:|---|
| Pagina sintetica con importo e data | 14.30 s | 1.34 s | Valori corretti in entrambi |
| Tabella sintetica 3x3 | 13.46 s | 2.86 s | Titolo, intestazioni e celle corretti in entrambi |
| Scansione reale capovolta | 49.23 s | 15.18 s | Errori rilevanti in entrambi |
| Stessa scansione ruotata 180 gradi | 50.43 s | 25.43 s | GLM leggibile; Qwen genera tag immagine e URL inventati |

Il primo prompt consente troppa liberta' nel formato Qwen. Seconda prova su
identica immagine orientata correttamente, con prompt comune piu' restrittivo:

```text
Text Recognition: Transcribe every visible line exactly, without rewriting or
correcting the document. Return only plain Markdown text and Markdown tables.
Do not output HTML, image tags, URLs, bounding boxes, code fences, explanations,
or invented content. Preserve all numbers and names.
```

| GLM | Qwen | Esito |
|---:|---:|---|
| 51.29 s, 630 token | 7.74 s, 506 token | Entrambi producono trascrizioni leggibili; Qwen presenta meno errori visibili sul campione |

## Interpretazione

Qwen e' una valida alternativa OCR e su questi campioni e' sensibilmente piu'
veloce. Per un uso archivistico occorre pero' controllare la fedelta' letterale:
anche con l'istruzione di non correggere il documento e' stata osservata una
normalizzazione di una parola. GLM commette errori di trascrizione propri e non
e' automaticamente piu' fedele perche' specializzato.

Non sono stati calcolati CER/WER: manca una trascrizione gold verificata della
pagina reale. La tabella sintetica non certifica tabelle contabili dense. La prova
mostra inoltre che correggere l'orientamento prima dell'OCR e' determinante.

Configurazione finale: GLM dedicato come OCR, Qwen come LLM/vision. Nessun fallback
automatico tra i modelli. Il modello embedding resta una dipendenza separata.

Gli output e le immagini locali sono fuori da Git in `/tmp`, nei file
`megadoc-ocr-comparison.json`, `megadoc-ocr-comparison-rotated.json` e
`megadoc-ocr-comparison-strict.json`.
