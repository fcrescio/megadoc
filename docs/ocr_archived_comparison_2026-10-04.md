# Confronto OCR su documenti archiviati

## Sintesi

Confronto completato su quattro PDF gia' archiviati, nove pagine complessive:
preventivo, quadro economico tabellare, ricevute di bollette e documento misto
verbale/estratto conto. Un secondo esperimento ripete le quattro pagine della
bolletta dopo orientamento verificato visivamente. Totale: 26 richieste OCR ai
nuovi backend, tutte completate senza timeout o troncamento.

Qwen e' il candidato piu' convincente per sostituire la lettura dots: sul campione
e' piu' veloce di GLM e generalmente piu' fedele sui documenti orientati bene.
**Nessuno dei due stack attuali e' pero' un sostituto completo del contratto
strutturale dots.** Il confronto ha identificato problemi concreti di adapter e
orientamento, oltre agli errori di lettura propri dei modelli.

Nessuna modifica all'archivio o alla configurazione dei backend. I risultati
storici sono stati salvati prima delle chiamate. Le righe OCR restano 49 e il
checksum aggregato di id, testo e JSON strutturato e' identico prima/dopo.

## Metodo

Procedura: `scripts/compare_archived_ocr.py`, descritta in
[compare_archived_ocr.md](compare_archived_ocr.md).

Il riferimento e' il risultato storico `dots_native`, modello
`ggml-org/dots.ocr-GGUF:Q8_0`, non una nuova chiamata a llama.cpp. GLM usa il
microservizio OpenVINO/iGPU; Qwen usa `qwen3.8-27b` su vLLM/RTX 4090.

Si recupera la precisa versione PDF associata alla riga OCR, non necessariamente
la versione piu' recente. Si riproducono le rotazioni e l'ordine pagine applicati
nel run storico; i nuovi adapter ricevono lo stesso PDF normalizzato a scala 1.5.
GLM limita internamente le immagini a 700000 pixel; Qwen usa il proprio
preprocessing. Prompt e formato di risposta sono quelli degli adapter reali:
Markdown/HTML GLM, JSON strutturato Qwen. Non e' un confronto a prompt uniforme
o a identico costo di tokenizzazione.

Chiamate seriali, temperatura zero, limite 4096 token. Si conservano risultato
completo, risposte per pagina, usage, finish reason, tempi e mapping pagine.
Il resume e' stato verificato sul primo documento senza nuove chiamate OCR.

Il test si ferma al confine OCR: non rilancia segmentazione, classificazione,
specialisti o indicizzazione. Evita di attribuire al modello OCR effetti di
altri stadi. I tempi dots non sono disponibili in forma comparabile e non sono
stati ricostruiti dai tempi dei job, che includerebbero altri costi.

## Risultati principali

Tempi end-to-end osservati una sola volta, non medie statistiche. Concordanza
calcolata sulla sequenza di parole, ignorando maiuscole e punteggiatura; non
misura accuratezza e non sostituisce un gold verificato.

| Caso | Pagine | GLM | Qwen | Concordanza GLM/dots | Concordanza Qwen/dots |
|---|---:|---:|---:|---:|---:|
| A: preventivo testuale | 1 | 32,2 s | 13,0 s | 100% | 100% |
| B: quadro economico | 1 | 48,2 s | 16,1 s | 96,5% | 100% |
| C: bollette con orientamenti misti storici | 4 | 66,3 s | 39,6 s | 58,7% | 59,9% |
| D: verbale ed estratto conto | 3 | 186,6 s | 76,6 s | 97,6% | 99,2% |

Totale principale: GLM 333,3 secondi, Qwen 145,3 secondi, circa 2,3 volte piu'
veloce sul campione. Non e' una misura di throughput concorrente, consumo
energetico o interferenza con i dialoghi che condividono la GPU NVIDIA.

### A: preventivo

Entrambi conservano tutte le parole del riferimento e tutte le 14 occorrenze
numeriche rilevate. Differiscono spaziatura, apostrofi e struttura dei blocchi.
Non sono state trovate tabelle in nessuno dei tre risultati.

### B: quadro economico

Tutti gli importi della tabella sono conservati da entrambi i nuovi modelli.
Qwen conserva anche l'intestazione dello studio e il numero pagina; GLM li
omette. GLM introduce un refuso in una descrizione e colloca due qualificazioni
delle lavorazioni nella colonna dei numeri anziche' della descrizione.
Qwen le mantiene nelle rispettive celle descrittive.

Dots e GLM espongono una tabella in `pages[].tables`. Qwen ne produce una nel
Markdown, ma **zero nel campo strutturato**: difetto dell'adapter, non incapacita'
del modello di leggere la tabella.

### C: bollette

Lo storico aveva escluso la rotazione per `insufficient_consensus`: due pagine
richiedono una correzione e le altre due quella opposta. Il confronto principale
riproduce questa condizione; non introduce una correzione a vantaggio dei nuovi
modelli.

Tutti i risultati contengono errori nei timbri o nelle intestazioni. Dots inventa
anche intestazioni estranee al documento. Non si possono interpretare le basse
concordanze come una perdita equivalente di informazioni vere.

Controllo visivo mirato sulle quattro scansioni, effettuato dall'agente, non una
trascrizione gold completa. Conteggio dei valori letterali principali: l'importo
stampato della bolletta, non una somma approssimativa letta nel timbro.

| Campo verificato | Dots storico | GLM, orientamento storico | Qwen, orientamento storico | GLM, orientamento corretto | Qwen, orientamento corretto |
|---|---:|---:|---:|---:|---:|
| Importo principale | 4/4 | 3/4 | 4/4 | 4/4 | 4/4 |
| Scadenza | 4/4 | 3/4 | 4/4 | 4/4 | 4/4 |
| Numero fattura | 4/4 | 4/4 | 3/4 | 4/4 | 4/4 |
| Codice utente | 3/4 | 4/4 | 1/4 | 4/4 | 4/4 |

Nel test supplementare le rotazioni aggiuntive per pagina originale sono
`270,270,90,90`, confermate dalle immagini. Tempi: GLM 71,6 s, Qwen 36,2 s.
Entrambi recuperano tutti i 16 campi principali verificati; restano errori in
indirizzi, loghi, intestazioni e timbri. GLM interpreta alcuni timbri come tabelle:
il loro conteggio non equivale a una maggiore utilita' documentale.

### D: verbale con estratto conto allegato

Qwen conserva meglio testo e struttura; GLM introduce diversi refusi e rende
la tabella delle presenze come lista, omettendone il totale autonomo, comunque
presente nel testo successivo.

Il confronto con la scansione rivela un errore **nel riferimento dots**: le date
delle prime sette righe dell'estratto conto erano state associate alle righe
sbagliate. Qwen le associa correttamente; GLM fa altrettanto su quelle righe,
ma introduce errori nei nomi di alcuni mesi successivi. Non sono regressioni le
due occorrenze numeriche che Qwen non condivide con lo storico in questo caso.

La riga di chiusura, separata graficamente nel PDF, resta fuori dalla tabella
Markdown principale in entrambi i nuovi risultati. I suoi valori sono nel testo,
ma la conversione strutturale non la recupera come riga di quella tabella.
E' un esempio concreto del perche' la conservazione dei numeri non basta.

| Tabelle recuperate | Dots strutturate | GLM strutturate | Qwen nel Markdown | Qwen strutturate |
|---|---:|---:|---:|---:|
| Quadro economico | 1 | 1 | 1 | 0 |
| Verbale/estratto conto | 2 | 1 | 2 | 0 |

## Problemi della pipeline verificati separatamente

### 1. Verso delle rotazioni Paddle

Il controllo nel worker attuale, sul PDF della bolletta, riproduce le etichette
`90,90,270,270`. `OrientationPreprocessService` le usa direttamente in
`Page.set_rotation`, mentre per mettere dritte queste scansioni servono gli
angoli inversi `270,270,90,90`.

Eseguendo il preprocessing attuale e riclassificando il risultato, Paddle
restituisce **180 su tutte e quattro le pagine**, con confidenza circa 0,92.
La gestione delle rotazioni miste e' gia' presente nel codice corrente, ma il
verso degli angoli e' sbagliato. I casi a 180 gradi non possono rivelare questo
errore, poiche' 180 e il suo inverso coincidono.

Questo controllo non cambia lo storico o i dati in Postgres. La prova
supplementare usa rotazioni esplicite, non pretende che le abbia prodotte il
preprocessing corrente.

### 2. Contratto delle tabelle Qwen

`LLMVisionOCRService._page_to_structured` emette sempre `tables: []`, anche quando
`markdown_text` e i blocchi contengono tabelle. Il consumer contabile
`_iter_structured_tables` legge i campi strutturati. Il risultato e' una perdita
di struttura lungo il confine tra OCR e consumer, non nel modello.

### 3. Geometria e righe separate

Dots espone layout e bounding box; i nuovi adapter non forniscono evidenza
geometrica equivalente. Un parser Markdown puo' recuperare celle, ma non inventare
coordinate attendibili o decidere senza controllo come associare righe isolate.
GLM emette inoltre un singolo blocco di paragrafo per tutta la pagina.

## Passi consigliati

1. Correggere la conversione etichetta Paddle -> angolo di correzione. Verificare
   immagini note a 0/90/180/270 e il PDF misto; dopo preprocessing tutte le pagine
   devono essere orientate correttamente senza alterare l'ordine.
2. Uniformare il contratto strutturale delle tabelle per GLM/Qwen. Testare colonne,
   celle vuote, qualificazioni multilinea e righe di chiusura, non solo presenza
   dei numeri o conteggio delle tabelle.
3. Ripetere i quattro casi dopo quei fix, poi verificare una vera tabella di riparto
   densa con gold contabile. Non estendere la conclusione del quadro economico a
   tutti i bilanci condominiali.
4. Solo dopo, scegliere esplicitamente il backend OCR. Qwen appare preferibile per
   qualita' e latenza; GLM resta interessante per l'esecuzione indipendente sulla
   iGPU, da valutare anche durante dialoghi concorrenti. Nessun fallback automatico.

Questa attivita' implementa e verifica il benchmark, non i fix sopra elencati.
La configurazione GLM predefinita non e' stata cambiata.

## Evidenza locale e verifica del tool

Documenti, snapshot, output e annotazioni restano fuori Git:

```text
~/megadoc-ocr-benchmarks/2026-10-04/
~/megadoc-ocr-benchmarks/2026-10-04-upright/
```

La prima directory contiene anche `bill-visual-checks.json`, con i valori letti
dalle immagini. Gli UUID dei casi si trovano nelle directory private e nei
`comparison.json`; il rapporto versionato conserva solo risultati aggregati.

Sette test focalizzati passati: confronto numerico, ordine pagine e rotazioni,
override espliciti, parser GLM e gestione troncamenti. I servizi di produzione
non richiedono rebuild: le modifiche di questo esperimento riguardano un tool
standalone, test e documentazione, eseguiti nell'immagine API con repository montato.
