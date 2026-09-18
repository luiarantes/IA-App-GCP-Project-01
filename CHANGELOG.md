# Changelog

Todas as alterações notáveis deste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/)
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Changed
- **k8s**: Migração de todos os manifestos Kubernetes (`deployment-api`, `deployment-worker`, `service`, `hpa`, `serviceaccount`, `podmonitoring`) do namespace `default` para o namespace isolado `apps`.
- **telemetry**: Atualização dos endpoints de telemetria para FQDNs entre namespaces (`otel-collector.observability:4318` e `pyroscope.observability:4040`).
- **ci/cd**: Alinhamento do workflow `.github/workflows/deploy.yml` para deployment direcionado no namespace `apps` com criação declarativa e idempotente.

## [0.4.0] - 2026-09-17

### Added
- Workflow de CI independente (`.github/workflows/ci.yml`) para validação contínua com Ruff, Mypy e Pytest em commits e pull requests.
- Verificação estática de tipos com **Mypy** nas dependências de desenvolvimento e configuração no `pyproject.toml`.
- Marcador formal `@pytest.mark.integration` no `pyproject.toml` para isolamento de testes de integração com WireMock.

### Changed
- Desacoplamento da esteira de deploy em nuvem (`.github/workflows/deploy.yml`), que passa a operar exclusivamente sob demanda (`workflow_dispatch`), respeitando a efemeridade e o custo zero da infraestrutura GCP.
- Documentação do `README.md` expandida com guia de qualidade de código (Ruff, Mypy, Pytest) e detalhamento da esteira de CI/CD desacoplada.

### Fixed
- **worker**: Tratamento defensivo de retorno `None` no parsing de cabeçalhos OTLP (`OTEL_EXPORTER_OTLP_HEADERS`), prevenindo falhas de desempacotamento de strings.
- **worker**: Importação explícita de `PublisherClient` e `SubscriberClient` diretamente de `google.cloud.pubsub_v1`.
- **app**: Encadeamento explícito de exceções (`from err`) nos disparos de `HTTPException` (404 e 502) no `app/main.py` para preservação do stacktrace original (PEP 3134 / flake8-bugbear B904).
- **viacep**: Tipagem estática de retorno `dict[str, Any]` e validação defensiva de dicionário no cliente HTTP (`isinstance(dados, dict)`).
- Reorganização e ordenação de imports dos módulos OpenTelemetry para o topo dos arquivos conforme a PEP 8 (Ruff E402/I001).

## [0.3.0] - 2026-09-11

### Added
- Instrumentação de profiling contínuo com **Grafana Pyroscope** na API e no Worker (`pyroscope-io`).
- Exportador de logs OTLP com correlação de traces (`traceparent` injetado nos atributos da mensagem do Pub/Sub) para rastreabilidade ponta a ponta.
- Instrumentação automática do FastAPI e HTTPX via OpenTelemetry SDK com exportação para Cloud Trace / OTLP Collector.

## [0.2.0] - 2026-09-09

### Added
- Metadados de serviço para catálogo CNCF Backstage / Port (`catalog-info.yaml`).

### Fixed
- **ci**: Alinhamento de localização do cluster para `us-central1-a` em conformidade com a migração para cluster GKE Standard Zonal.

## [0.1.0] - 2026-08-11

### Added
- API REST BuscaCEP construída em FastAPI com consulta de CEP e retorno JSON.
- Cliente HTTP assíncrono para integração com ViaCEP com suporte a override de URL base.
- Worker assíncrono para consumo e processamento de eventos publicados via Cloud Pub/Sub com Dead Letter Queue (DLQ).
- Suíte de testes unitários com dublês (monkeypatch) para execução 100% offline.
- Suíte de testes de integração com container **WireMock** via Docker simulando latência e cenários de erro do ViaCEP.
- Ambiente local completo via Docker Compose (API + Worker + Emulador Pub/Sub).
- Manifestos Kubernetes (Deployment, Service, HPA, ServiceAccount, PodMonitoring) e pipeline de deploy no GKE com Workload Identity Federation.

### Fixed
- Configuração do `pythonpath` no Pytest para resolução de importação de módulos no CI.
- Aumento do timeout de rollout do Deployment para 5 minutos no pipeline de CD.
- Tratamento de log para throttling do ViaCEP (`{erro: true}`).
