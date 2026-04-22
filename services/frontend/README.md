# Megadoc Frontend

React-based frontend for the Megadoc document ingestion pipeline.

## Tech Stack

- React 18 with TypeScript
- Vite for build tooling
- TailwindCSS for styling
- React Query for data fetching
- React Markdown for OCR result display

## Local Development

```bash
# Install dependencies
npm install

# Start dev server (requires API running on localhost:8080)
npm run dev
```

The dev server runs on `http://localhost:3000`.

## Docker

Build and run with docker-compose:

```bash
docker compose up --build frontend
```

Access at `http://localhost:3000`.

## Features

- Browse uploaded documents
- View document details, versions, and assets
- View OCR results in markdown format
- Upload new PDF documents with optional external_id for versioning
- Monitor job status with real-time updates
- Download original PDFs and derived assets
