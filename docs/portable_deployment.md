# Deploy Portabile

Il compose base non dipende da IP statici, rete ML preesistente o runtime NVIDIA.
Postgres, Redis e MinIO rimangono nei volumi Docker; llama.cpp resta esterno allo
stack e deve esporre un'API OpenAI-compatible.

## macOS con Docker Desktop

Prerequisiti:

- Docker Desktop con Compose v2;
- almeno 12 GB assegnati alla VM Docker per lo stack applicativo, oltre alla memoria
  usata da llama.cpp nativo;
- llama.cpp in ascolto su un'interfaccia raggiungibile da Docker Desktop.

Avvio:

```bash
cp .env.example .env
printf '\nMEGADOC_API_PORT=8081\n' >> .env
docker compose up --build
```

Nella pagina `/settings` usa `http://host.docker.internal:8080/v1` per raggiungere
llama.cpp sull'host. Il probe verifica `/health` e `/v1/models` dal container API,
quindi misura la raggiungibilità effettiva usata dall'applicazione.

`MEGADOC_API_PORT=8081` evita il conflitto con llama.cpp sulla porta host 8080. La
porta interna dell'API resta 8080 e il frontend continua a funzionare senza altre
modifiche. L'accesso API diretto sarà in questo caso `http://localhost:8081`.

I bind mount non sono usati per i dati persistenti, evitando differenze di permessi
e prestazioni fra filesystem Linux e macOS. Per importare directory locali è
preferibile l'upload HTTP o la CLI in container.

## Linux con NVIDIA e rete ML condivisa

La configurazione specifica esistente è isolata in un override:

```bash
docker compose -f docker-compose.yml -f docker-compose.linux-nvidia.yml up --build
```

L'override richiede:

- NVIDIA Container Toolkit;
- rete Docker esterna `ml-infra_ml-infra-net` con subnet compatibile con gli IP
  `10.89.0.51-56`;
- eventuali endpoint espliciti in `.env` se llama.cpp non è raggiungibile tramite
  `host.docker.internal`.

## Impostazioni e precedenza

Le variabili ambiente costituiscono i default. La pagina Settings salva in Postgres
gli override per endpoint e modelli; questi valori hanno precedenza e vengono letti
all'avvio di ogni nuovo job. Le credenziali non sono memorizzate nel database.

Cambiare modello non riprocessa automaticamente documenti o indice embedding già
esistenti. Dopo un cambio di modello embedding occorre ricostruire l'indice; dopo un
cambio OCR o knowledge occorre rilanciare esplicitamente lo stadio interessato.

## Verifica

```bash
docker compose config -q
docker compose ps
curl "http://localhost:${MEGADOC_API_PORT:-8080}/ready"
curl "http://localhost:${MEGADOC_API_PORT:-8080}/settings/runtime"
```

Apri `/settings`, esegui `Verifica backend`, quindi salva. Il probe deve riportare
server raggiungibile e modello disponibile. Un modello assente produce stato
`degraded`, mentre un endpoint irraggiungibile produce `error`.
