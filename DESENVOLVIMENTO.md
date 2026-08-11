# Guia de Desenvolvimento — BuscaCEP

Documento de referência para quem trabalha neste repositório. Cobre
desenvolvimento local, testes, deploy e operação em GKE.

---

## Visão geral

**BuscaCEP** é uma API de consulta de endereços por CEP, construída
sobre o serviço público [ViaCEP](https://viacep.com.br). Cada consulta
bem-sucedida gera um evento assíncrono no Google Pub/Sub — consumido
por um worker separado — criando uma superfície de falha controlada
para testes de self-healing com o agente AIOps do projeto de infra.

```
Usuário
  │  GET /api/cep/{cep}
  ▼
API (FastAPI)
  ├─ GET https://viacep.com.br/ws/{cep}/json/
  │    retorna endereço ou {"erro": true}
  └─ publicar evento → Pub/Sub (topic: cep-consultado)
                              │
                              ▼
                         Worker (consome cep-consultado-sub)
                              └─ loga CEP, localidade, UF
```

O repositório de infra (`IA-Infra-GCP-Project-01`) provisiona todos os
recursos GCP compartilhados — cluster GKE, Pub/Sub, IAM. Esta app
consome esses recursos via variáveis de ambiente e Workload Identity.

---

## Estrutura de diretórios

```
.
├── app/
│   ├── main.py          # FastAPI: rotas, métricas Prometheus, health checks
│   ├── viacep.py        # cliente HTTP do ViaCEP (URL configurável via env var)
│   └── publisher.py     # publica evento no Pub/Sub (fire-and-forget)
├── worker/
│   └── main.py          # consumidor Pub/Sub + health server HTTP em thread
├── tests/
│   ├── test_api.py                     # testes unitários (sem rede)
│   └── test_integracao_wiremock.py     # testes de integração via WireMock
├── wiremock/                           # mapeamentos WireMock para CEPs de teste
│   └── mappings/
├── docker/
│   └── pubsub-emulator/                # Dockerfile do emulador Pub/Sub local
├── k8s/
│   ├── deployment-api.yaml     # Deployment da API
│   ├── deployment-worker.yaml  # Deployment do worker
│   ├── service.yaml            # LoadBalancer (porta 80 → 8000)
│   ├── hpa.yaml                # HPA: CPU 70%, min 1, max 3 réplicas
│   ├── serviceaccount.yaml     # KSA com anotação de Workload Identity
│   └── podmonitoring.yaml      # CRD GMP: scrape /metrics a cada 30s
├── static/
│   └── index.html              # frontend mínimo de consulta de CEP
├── docker-compose.yml          # stack local completo: api + worker + emulador
├── Dockerfile                  # imagem única usada por API e worker
├── requirements.txt            # dependências de produção
├── requirements-dev.txt        # dependências adicionais para desenvolvimento
└── .github/workflows/
    └── deploy.yml              # pipeline: testes → build → deploy GKE
```

---

## Desenvolvimento local

### Pré-requisitos

- Python 3.12+
- Docker e Docker Compose

### Opção A — Stack completo (API + Worker + Pub/Sub)

O `docker-compose.yml` sobe o emulador local do Pub/Sub, o worker e a
API em rede isolada. É o ambiente mais próximo do GCP:

```bash
docker compose up --build
```

A API fica disponível em `http://localhost:8000`.

Para simular falha na fila: pare o worker e faça consultas na API. As
mensagens acumulam na subscription; o agente AIOps detecta o backlog via
`oldest_unacked_message_age`.

```bash
docker compose stop worker
```

Para restaurar:

```bash
docker compose start worker
```

### Opção B — Só a API (sem Pub/Sub)

Se `PUBSUB_PROJECT_ID` não estiver configurado, o publisher é no-op —
a API funciona normalmente e apenas não emite eventos:

```bash
pip install -r requirements.txt
```

```bash
uvicorn app.main:app --reload
```

### Variáveis de ambiente

| Variável | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `PUBSUB_PROJECT_ID` | Não | `""` (no-op) | ID do projeto GCP |
| `PUBSUB_TOPIC_ID` | Não | `cep-consultado` | Nome do tópico |
| `PUBSUB_EMULATOR_HOST` | Não | — | Ex: `localhost:8085`; ativa o emulador local |
| `VIACEP_BASE_URL` | Não | `https://viacep.com.br` | URL base do ViaCEP; use para apontar ao WireMock |

**Worker — variáveis adicionais:**

| Variável | Padrão | Descrição |
|---|---|---|
| `PUBSUB_SUBSCRIPTION_ID` | `cep-consultado-sub` | Subscription a consumir |
| `WORKER_HEALTH_PORT` | `8000` | Porta do health server HTTP |

No ambiente GCP (cluster GKE), essas variáveis são injetadas pelos
`deployment-api.yaml` e `deployment-worker.yaml` em `k8s/`.

---

## Testes

### Unitários

Rodam sem rede — o cliente ViaCEP é substituído por dublês via
`monkeypatch`:

```bash
pip install -r requirements-dev.txt
```

```bash
pytest tests/test_api.py -v
```

Cenários cobertos: CEP válido, CEP com formato inválido (400), CEP
inexistente (404), upstream indisponível (502), `/healthz`, `/readyz`,
endpoint `/metrics` em formato Prometheus, frontend na raiz.

### Integração com WireMock

Os testes de integração fazem requisições HTTP reais contra um servidor
WireMock que simula o ViaCEP. Requerem Docker:

```bash
docker run -d --name wiremock -p 9090:8080 \
  -v $(pwd)/wiremock:/home/wiremock wiremockcloud/wiremock:latest
```

```bash
VIACEP_BASE_URL=http://localhost:9090 pytest tests/test_integracao_wiremock.py -v
```

```bash
docker stop wiremock && docker rm wiremock
```

Os mapeamentos em `wiremock/mappings/` definem respostas fixas para um
conjunto de CEPs de teste, incluindo cenários de erro (404, 503).

> **Nota:** os testes de integração não rodam no CI por ora — exigem
> Docker-in-Docker e aumentam consideravelmente o tempo do pipeline.
> Rodam localmente antes de abrir PRs com mudanças no cliente ViaCEP.

---

## Deploy no GKE

### Como funciona (`.github/workflows/deploy.yml`)

O pipeline tem três jobs encadeados:

**1. `test`** — roda `pytest tests/test_api.py` no runner. Sem Docker,
sem GCP. Falha aqui bloqueia tudo.

**2. `build-push`** — autentica no GCP via Workload Identity Federation,
builda a imagem Docker com o SHA do commit como tag e faz push para o
Artifact Registry (`us-central1-docker.pkg.dev/ia-infra-gcp-project-01/sample-app/buscacep`).

**3. `deploy`** — obtém credenciais do GKE, substitui `IMAGE_PLACEHOLDER`
pelo endereço completo da imagem nos dois Deployments via `sed`, aplica
`kubectl apply -f k8s/` e aguarda rollout de API e worker (timeout: 5m).

O workflow é **idempotente**: cria recursos novos na primeira vez e
atualiza nas seguintes. O `kubectl apply` aplica todos os arquivos em
`k8s/` — incluindo `podmonitoring.yaml`.

### Acionar manualmente

O workflow dispara automaticamente em push para `main`. Para acionar
sem commit:

```bash
gh workflow run deploy.yml --ref main --repo luiarantes/IA-App-GCP-Project-01
```

### Verificar IP externo após deploy

```bash
kubectl get svc buscacep-api -n default
```

O campo `EXTERNAL-IP` leva alguns segundos para ser atribuído pelo GKE
na primeira vez. O workflow já faz esse poll e exibe o IP no log.

---

## Manifestos Kubernetes (`k8s/`)

### `serviceaccount.yaml`

Cria a Kubernetes Service Account (KSA) `buscacep-ksa` com a anotação
de Workload Identity que a vincula à GSA `buscacep-workload` do GCP.
O binding KSA → GSA é criado pelo Terraform no repo de infra — a
anotação aqui é o lado Kubernetes da federação.

### `deployment-api.yaml`

Deployment da API FastAPI. Pontos importantes:

- `image: IMAGE_PLACEHOLDER` — substituído pelo SHA do commit no workflow.
- `ports[0].name: http` — nome obrigatório para o `PodMonitoring`
  referenciar a porta via `port: http`.
- Resources: 100m/128Mi requests, 500m/256Mi limits.
- Probes: `/healthz` (liveness, a partir de 10s) e `/readyz` (readiness,
  a partir de 5s).

### `deployment-worker.yaml`

Mesmo Dockerfile da API, entrypoint diferente (`python -m worker.main`).
Resources: 50m/64Mi requests, 200m/128Mi limits. O worker tem um
servidor HTTP mínimo em thread para as probes do GKE.

### `service.yaml`

LoadBalancer que expõe a API externamente na porta 80 (→ 8000 no pod).
O IP externo é alocado pelo GKE — use `kubectl get svc` para obtê-lo.

### `hpa.yaml`

HorizontalPodAutoscaler somente para a API (não faz sentido escalar o
worker horizontalmente para este volume). Escala entre 1 e 3 réplicas
quando CPU média supera 70%.

> **Atenção:** se a HPA escalar durante um teste de carga e um novo
> deploy rodar logo em seguida, o rollout pode demorar mais que o
> esperado enquanto os pods antigos terminam. O timeout de 5m no
> workflow cobre este cenário.

### `podmonitoring.yaml`

Recurso CRD do Google Managed Prometheus (GMP). Instrui o GMP a fazer
scrape do endpoint `/metrics` em todos os pods com `app: buscacep-api`
a cada 30 segundos.

Sem este recurso, o GMP só coleta métricas de sistema (CPU/memória) —
as métricas de aplicação (`http_requests_total`, `http_request_duration_seconds`)
ficam invisíveis para os alertas do Cloud Monitoring e para o agente
AIOps.

---

## Observabilidade

### Endpoint `/metrics`

A API expõe métricas no formato Prometheus em `GET /metrics`:

| Métrica | Tipo | Labels |
|---|---|---|
| `http_requests_total` | Counter | `method`, `path`, `status` |
| `http_request_duration_seconds` | Histogram | `method`, `path` |

O middleware em `app/main.py` usa o template da rota (`/api/cep/{cep}`)
como label `path` — evita explosão de cardinalidade com CEPs diferentes.

### Coleta pelo GMP

O `podmonitoring.yaml` instrui o GMP a fazer scrape de `/metrics` a
cada 30s. As métricas ficam disponíveis no Cloud Monitoring sob o
prefixo `prometheus.googleapis.com/`.

Os alertas baseados nessas métricas são definidos no repo de infra
(`module "observability_buscacep"` em `infra/environments/test/main.tf`).

### Logs relevantes

| Logger | Nível | Quando aparece |
|---|---|---|
| `app.viacep` | WARNING | ViaCEP retornou `{"erro":true}` — CEP inexistente **ou** rate-limit do upstream |
| `worker.main` | INFO | CEP processado com sucesso (localidade, UF, timestamp) |
| `worker.main` | ERROR | Falha ao decodificar mensagem Pub/Sub |
| `worker.main` | WARNING | Pub/Sub indisponível durante inicialização (retry automático) |

O log WARNING do `viacep` é especialmente útil para o agente AIOps:
se aparecer para CEPs conhecidamente válidos durante um teste de carga,
o culpado é throttling do ViaCEP, não um bug da app.

---

## Comportamento do ViaCEP sob carga

O ViaCEP retorna `HTTP 200` com corpo `{"erro": true}` em **dois
cenários distintos**:

1. CEP com formato válido mas inexistente na base.
2. Rate-limiting / instabilidade do upstream sob alta concorrência.

A API não tem como distinguir os dois casos pela resposta — retorna
`404` em ambos. Sob 20 usuários simultâneos no k6, CEPs válidos podem
receber `{"erro": true}` por conta do throttling do ViaCEP.

**Consequência prática:** em testes de performance, "erros" 404 não
indicam bug na aplicação. Verifique os logs do pod da API — se
`app.viacep` logar o WARNING com CEPs que existem na base, o problema
está no upstream.

---

## Restaurar após destruição do ambiente

O ambiente GCP (cluster, Pub/Sub, IAM) é destruído ao final de cada
sessão de teste pelo `terraform-destroy.yml` no repo de infra. Para
restaurar o BuscaCEP:

**Passo 1:** confirme que o `terraform-apply.yml` do repo de infra
terminou com sucesso (cluster, Pub/Sub e GSAs recriados).

**Passo 2:** acione o deploy do app:

```bash
gh workflow run deploy.yml --ref main --repo luiarantes/IA-App-GCP-Project-01
```

O workflow reconstrói e aplica tudo — imagem Docker, Deployments,
Service, HPA, ServiceAccount e PodMonitoring. Nenhum `kubectl apply`
manual é necessário.

---

## Conexão com o repo de infra

O BuscaCEP **não gerencia** os recursos GCP que consome. Toda
modificação em nomes de tópico, subscription, roles IAM ou Workload
Identity exige uma mudança em `infra/environments/test/main.tf` no
repo `IA-Infra-GCP-Project-01` seguida de um `terraform apply`.

Recursos provisionados pela infra e consumidos por esta app:

| Recurso | Nome | Usado por |
|---|---|---|
| GSA (deploy CI) | `apps-deploy` | workflow `deploy.yml` |
| GSA (workload) | `buscacep-workload` | pods API e worker |
| Pub/Sub topic | `cep-consultado` | API (publisher) |
| Pub/Sub subscription | `cep-consultado-sub` | worker |
| Pub/Sub topic (DLQ) | `cep-consultado-dlq` | infra automático |
| Pub/Sub subscription (DLQ) | `cep-consultado-dlq-sub` | infra / agente AIOps |
| Artifact Registry | `sample-app` | imagem `buscacep` |
| GKE cluster | `aiops-gke` | todos os manifestos `k8s/` |
