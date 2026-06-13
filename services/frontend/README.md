# Megadoc Frontend

Frontend React/Vite per Megadoc. È l'interfaccia operativa principale del sistema: documenti, PDF embedded, OCR, knowledge base, search, review, entità, specialisti e manuale commentabile.

## Tech Stack

- React 18 con TypeScript
- Vite
- TailwindCSS
- React Query
- React Markdown + remark-gfm

## Avvio Locale

```bash
npm install
npm run dev
```

Il dev server gira su `http://localhost:3000` e si aspetta l'API su `http://localhost:8080`.

## Docker

```bash
docker compose up --build frontend
```

Accesso: `http://localhost:3030`.

## Rotte

- `/documents`: lista documenti e job OCR.
- `/upload`: upload PDF.
- `/knowledge`: knowledge base navigabile.
- `/manual`: manuale online commentabile.

La navigazione documento usa lo stato URL per aprire il dettaglio e tab specifiche.

## Funzioni Implementate

- Upload PDF con `external_id` opzionale.
- Lista documenti e job con polling.
- Badge stato backend LLM/OCR nel layout principale.
- Dettaglio documento con tab:
  - `Info`
  - `PDF`
  - `OCR`
  - `Knowledge`
  - `Versions`
  - `Assets`
- Visualizzazione PDF embedded, non download forzato.
- Visualizzazione markdown OCR.
- Avvio manuale knowledge e specialisti per documento.
- Search su corpus e topic.
- Topic browser con filtri.
- Review topic proposals.
- Graph consolidation review.
- Entity index e canonical entities.
- Utility Lens per bollette.
- Accounting Lens per rendiconti.
- Manuale servito dal backend, selezionabile e commentabile.

## File Principali

- `src/App.tsx`: routing leggero e layout.
- `src/api/client.ts`: client HTTP.
- `src/hooks/useDocuments.ts`: React Query hooks.
- `src/components/DocumentList.tsx`: lista documenti/job.
- `src/components/DocumentDetail.tsx`: dettaglio documento e tab.
- `src/components/KnowledgeBase.tsx`: search, topic, entità, proposal, specialisti.
- `src/components/ManualView.tsx`: manuale commentabile.
- `src/types.ts`: contratti TypeScript.

## Build

```bash
npm run build
```

## Performance Probes

From the repository root, measure API latency:

```bash
scripts/api_perf_probe.sh http://localhost:8080
```

Measure browser navigation and resource timings through the running frontend:

```bash
scripts/ui_perf_probe.sh http://127.0.0.1:3030/knowledge
```

The UI probe runs Playwright inside Docker, so agents can collect repeatable browser-side timing data without manual interaction.

## Note Operative

- Le chiamate frontend passano da `/api/*`, proxate da nginx verso `api:8080`.
- Se Edge o altri browser scaricano il PDF invece di mostrarlo, controllare gli header dell'endpoint documentale e la configurazione nginx.
- Il badge backend dipende da `GET /api/system/status`; un falso offline indica quasi sempre mismatch tra endpoint visto dal container API e endpoint visto dai worker host-network.
