# Report — Build loop debugging

## Obiettivo
Ricostruire e deployare il frontend con profiling React (branch `fix/useeffect-deps`, commit `2ffccf6`) per permettere una nuova sessione di profiling.

## Problema
Il build non produce output diverso nonostante `VITE_GIT_HASH` venga passato correttamente come build arg. Il bundle servito contiene `unknown` invece di `2ffccf6`.

## Dettagli

1. **`docker build --build-arg VITE_GIT_HASH=2ffccf6`** — l'env var arriva al container (verificato con `echo` in Dockerfile di debug), ma il bundle prodotto ha sempre gli stessi hash e contiene `unknown`.

2. **Con Dockerfile inline (heredoc) funziona** — un Dockerfile identico ma con `RUN echo` extra produce bundle diversi con l'hash corretto. Il problema non è nel codice ma in qualche cache di build.

3. **`--no-cache` non basta** — docker buildx mostra layer `CACHED` (WORKDIR e ARG/ENV) nonostante `--no-cache`. Lo step `npm run build` viene eseguito fresh ma produce output identico.

4. **Possibile causa**: vite ha una cache interna (`.vite/`) in `node_modules` che persiste tra build. `npm install` la preserva, quindi anche con `--no-cache` docker, vite riusa output cached.

## Cosa servirebbe per sbloccarsi

- Pulire la cache di build docker: `docker buildx prune -a`
- O eliminare l'immagine e rifare da capo
- O verificare se vite ha una cache in `node_modules/.vite/` e invalidarla
