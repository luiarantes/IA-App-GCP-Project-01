# BuscaCEP

Aplicação de consulta de CEP: uma API REST em FastAPI que consulta o
[ViaCEP](https://viacep.com.br) e um frontend web simples servido pela própria
aplicação. Não usa banco de dados — é stateless, com container leve e deploy
rápido.

## Endpoints

| Método | Rota             | Descrição                                      |
|--------|------------------|------------------------------------------------|
| GET    | `/`              | Frontend web de consulta                       |
| GET    | `/api/cep/{cep}` | Consulta um CEP (com ou sem hífen)             |
| GET    | `/healthz`       | Liveness probe                                 |
| GET    | `/readyz`        | Readiness probe                                |
| GET    | `/metrics`       | Métricas no formato Prometheus                 |
| GET    | `/docs`          | Documentação interativa da API (Swagger UI)    |

Respostas da API:

- `200` — endereço encontrado
- `400` — CEP com formato inválido (precisa ter 8 dígitos)
- `404` — CEP não existe na base do ViaCEP
- `502` — ViaCEP indisponível (timeout ou erro de rede)

## Rodando localmente

Requisitos: Python 3.12+.

Criar o ambiente virtual:

```bash
python3 -m venv .venv
```

Ativar o ambiente:

```bash
source .venv/bin/activate
```

Instalar as dependências (incluindo as de desenvolvimento):

```bash
pip install -r requirements-dev.txt
```

Subir a aplicação:

```bash
uvicorn app.main:app --reload --port 8000
```

Acesse o frontend em <http://localhost:8000> ou consulte direto pela API:

```bash
curl http://localhost:8000/api/cep/01310-100
```

## Testes

```bash
pytest
```

Os testes substituem a chamada ao ViaCEP por dublês, então rodam offline.

## Docker

Build da imagem:

```bash
docker build -t buscacep:0.1.0 .
```

Rodar o container:

```bash
docker run --rm -p 8000:8000 buscacep:0.1.0
```

## Observabilidade

- `/metrics` expõe `http_requests_total` (por método, rota e status) e
  `http_request_duration_seconds` (histograma de latência), prontos para
  coleta por Prometheus / Google Managed Prometheus.
- `/healthz` e `/readyz` são separados de propósito: liveness indica que o
  processo está vivo; readiness indica que a aplicação pode receber tráfego.
