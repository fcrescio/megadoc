# Piano — Vista tabellare unificata dei bilanci con drill-down al PDF

## Obiettivo

Trasformare i dati contabili attuali (fatti per-categoria, righe separate) in
una o poche tabelle dense stile foglio Excel, dove:

- **Righe** = entità (unità immobiliari / conti)
- **Colonne** = categorie di spesa (GENERALI, SCALA N.6, …)
- **Celle** = importo + metadati di provenienza

Ogni cella deve essere cliccabile e aprire una vista laterale che mostra la
pagina PDF originale da cui il dato è stato estratto, con la tabella/cella
sorgente evidenziata.

---

## Architettura

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React/TypeScript)                        │
│  ┌──────────────────────────────────────────────┐   │
│  │  AccountingSpreadsheet.tsx                   │   │
│  │  - Tabella stile Excel (sticky header/col)   │   │
│  │  - Cella cliccabile → side panel             │   │
│  │  - Filtri per documento/periodo              │   │
│  └──────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────┐   │
│  │  PdfPageViewer.tsx                           │   │
│  │  - Side panel con iframe/pdf.js              │   │
│  │  - Evidenzia la tabella sorgente             │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
         │ API
         ▼
┌─────────────────────────────────────────────────────┐
│  API (FastAPI)                                      │
│  GET /knowledge/documents/{id}/accounting-table     │
│  GET /knowledge/documents/{id}/accounting-table/    │
│      cell-detail?table_id=X&row_id=Y&column=Z       │
│  GET /documents/{id}/pdf-page/{page}                │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  Backend (Python)                                   │
│  - Pivot query: accounting_facts → tabella 2D       │
│  - Risoluzione pagina da table_id → specialist_result│
│  - Servizio di serving pagine PDF                   │
└─────────────────────────────────────────────────────┘
```

---

## Step 1 — Backend: Pivot query (API + service)

### Cosa serve

Una nuova rotta `GET /knowledge/documents/{document_id}/accounting-table`
che restituisce una struttura pivotata:

```json
{
  "document_unit_id": "uuid",
  "document_unit_title": "Riparto spese - pagine 15-29",
  "period_from": "2022-07-01",
  "period_to": "2023-06-30",
  "rows": [
    {
      "account_id": "uuid",
      "unit_code": "1",
      "subject_label": "ANTONACCI Elda",
      "cells": {
        "GENERALI": {
          "amount": 375.65,
          "fact_id": "uuid",
          "evidence": {
            "table_id": "table_50",
            "row_id": "row_1",
            "column": "TOTALE",
            "page_number": 17
          }
        },
        "SCALA N.6": { "amount": 130.28, ... },
        ...
      }
    },
    ...
  ],
  "columns": ["GENERALI", "SCALA N.6", "ASCENSORE N.6", ...],
  "totals": {
    "GENERALI": 10157.68,
    "SCALA N.6": ...
  }
}
```

### Logica

1. Caricare `accounting_facts` + `accounting_accounts` per un dato `document_unit_id`
2. Raggruppare per `account_id` (righe) e `category_label` (colonne)
3. Per ogni cella, includere `amount`, `fact_id`, e `evidence` arricchito con `page_number`
4. La `page_number` si risolve cercando il `table_id` nell'array `tables` dello `specialist_result`
5. Calcolare totali per colonna

### File

- `services/api/src/api/routers/knowledge.py` — nuova rotta
- `packages/common/src/common/application/accounting.py` — nuovo servizio di query
- Eventuale nuovo schema Pydantic per la response

### Verifica

```bash
curl -s http://localhost:8080/knowledge/documents/5192a509-e4c9-4076-996c-fcb9c2186c81/accounting-table | python3 -m json.tool | head -50
```

Deve restituire una struttura con `rows[]` e `columns[]`. Ogni riga deve avere
almeno una cella non nulla. I totali per colonna devono corrispondere alla somma
degli importi in `accounting_facts`.

---

## Step 2 — Backend: Endpoint cell-detail

### Cosa serve

`GET /knowledge/documents/{document_id}/accounting-table/cell-detail?table_id=X&row_id=Y&column=Z`

Restituisce le informazioni necessarie per il drill-down:

```json
{
  "page_number": 17,
  "table_id": "table_50",
  "row_id": "row_1",
  "column": "TOTALE",
  "raw_value": "375.65",
  "category_label": "GENERALI",
  "unit_code": "1",
  "subject_label": "ANTONACCI Elda",
  "amount": 375.65,
  "table_snippet": "...HTML o contesto della tabella...",
  "pdf_page_url": "/api/documents/.../pdf-page/17"
}
```

### Logica

1. Cercare il `table_id` nell'array `tables` dello `specialist_result`
2. Estrarre `page_number` e il contesto circostante
3. Restituire i metadati

---

## Step 3 — Backend: Endpoint PDF page serving

### Cosa serve

`GET /documents/{document_id}/pdf-page/{page}`

Restituisce l'immagine/rendering della pagina PDF specificata.

### Logica

1. Caricare il documento originale da `document_assets` o dal filesystem
2. Estrarre/rendering la pagina richiesta (via pdf.js o simile)
3. Restituire come PNG/JPEG o come URL per iframe

### Alternative

- Usare pdf.js lato frontend: servire il PDF intero e navigare via parametro `#page=N`
- Servire singole pagine come immagini dal backend (più complesso ma più controllabile)

**Raccomandazione**: servire il PDF intero via un endpoint dedicato e usare pdf.js
lato frontend con `#page=N` per la navigazione. È più semplice e sfrutta il
rendering nativo del browser.

---

## Step 4 — Frontend: AccountingSpreadsheet component

### Cosa serve

Un nuovo componente React che:

1. **Carica** i dati dall'endpoint `/accounting-table`
2. **Renderizza** una tabella con:
   - Header di colonna sticky (nomi categoria)
   - Prima colonna sticky (unità + nominativo)
   - Righe scrollabili orizzontalmente e verticalmente
   - Celle numeriche allineate a destra
   - Totali per colonna in fondo
3. **Gestione click cella**: onClick → apre `PdfPageViewer` laterale
4. **Filtri**: per documento unit (se multipli), per periodo

### Stile

- Sembrare un foglio Excel/Google Sheets
- Griglia sottile, header con sfondo scuro, righe alternate
- Cella cliccabile mostra cursore pointer e hover highlight
- Cella selezionata mostra bordo evidente

### Posizione nell'UI

- Nuovo tab "Bilancio" nella pagina di dettaglio documento
- Oppure nuova sezione nel pannello "Conoscenza" quando si seleziona un
  documento con dati contabili

### File

- `services/frontend/src/components/AccountingSpreadsheet.tsx`
- `services/frontend/src/hooks/useAccountingTable.ts`
- `services/frontend/src/components/KnowledgeBasePanels.tsx` — integrazione tab

---

## Step 5 — Frontend: PdfPageViewer component

### Cosa serve

Un pannello laterale (slide-in) che mostra:

1. La pagina PDF corrispondente alla cella cliccata
2. Un'evidenziazione approssimativa della tabella sorgente (opzionale, stretch goal)
3. Metadati: documento, pagina, tabella, riga, colonna, valore originale

### Implementazione

- Usare `react-pdf` o `pdfjs-dist` per il rendering
- Caricare il PDF dall'endpoint `/documents/{id}/pdf`
- Navigare alla pagina specificata via `pageNumber` prop
- Opzionale: overlay con rettangolo sulla tabella (richiede coordinate nel JSON)

---

## Step 6 — Integrazione e test

### Verifica end-to-end

1. Aprire documento 5192a509 nella UI
2. Navigare al tab "Bilancio"
3. Verificare che la tabella mostri 36 righe × ~10 colonne
4. Cliccare su una cella → side panel si apre con la pagina PDF corretta
5. Verificare che la pagina PDF corrisponda alla tabella sorgente

### Test backend

- Unit test per la pivot query
- Unit test per la risoluzione pagina da table_id
- Test API con curl

---

## Ordine di implementazione

1. **Step 1** — Pivot query backend (API + service)
2. **Step 4** — AccountingSpreadsheet frontend (con dati mock inizialmente)
3. **Step 2** — Cell-detail endpoint backend
4. **Step 5** — PdfPageViewer frontend
5. **Step 3** — PDF page serving backend
6. **Step 6** — Integrazione e test end-to-end

---

## Rischi e note

- **Performance**: la pivot query deve essere efficiente. Con 36 unità × 10
  categorie = 360 celle, è gestibile. Con 1000+ unità potrebbe servire
  paginazione lato server.
- **Evidence senza page_number**: l'evidence_json attuale non contiene
  `page_number`. Va risolto cercando il `table_id` nell'array `tables` dello
  `specialist_result`. In alternativa, arricchire l'evidence con `page_number`
  al momento della creazione dei fatti (modifica alla pipeline).
- **PDF serving**: servire il PDF intero è più semplice che generare immagini.
  pdf.js gestisce `#page=N` nativamente.
- **Mobile**: la vista tabellare è intrinsecamente desktop. Su mobile mostrare
  una lista o tabella orizzontalmente scrollabile.
