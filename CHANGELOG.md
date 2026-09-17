# Changelog

Todas as alterações notáveis deste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/)
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added
- Workflow de CI independente (`.github/workflows/ci.yml`) para validação contínua com Ruff, Mypy e Pytest em commits e pull requests.
- Verificação estática de tipos com **Mypy** nas dependências de desenvolvimento e configuração no `pyproject.toml`.
- Marcador formal `@pytest.mark.integration` no `pyproject.toml` para isolamento de testes de integração com WireMock.

### Changed
- Desacoplamento da esteira de deploy em nuvem (`.github/workflows/deploy.yml`), que passa a operar exclusivamente sob demanda (`workflow_dispatch`), respeitando a efemeridade e o custo zero da infraestrutura GCP.
- Seção de testes no `README.md` reestruturada para "Qualidade de Código e Testes", detalhando uso do Ruff, Mypy e filtros de execução do Pytest.

### Fixed
- **worker**: Tratamento defensivo de retorno `None` no parsing de cabeçalhos OTLP (`OTEL_EXPORTER_OTLP_HEADERS`), prevenindo falhas de desempacotamento de strings.
- **worker**: Importação explícita de `PublisherClient` e `SubscriberClient` diretamente de `google.cloud.pubsub_v1`.
- **app**: Encadeamento explícito de exceções (`from err`) nos disparos de `HTTPException` (404 e 502) no `app/main.py` para preservação do stacktrace original (PEP 3134 / flake8-bugbear B904).
- **viacep**: Tipagem estática de retorno `dict[str, Any]` e validação defensiva de dicionário no cliente HTTP (`isinstance(dados, dict)`).
- Reorganização e ordenação de imports dos módulos OpenTelemetry para o topo dos arquivos conforme a PEP 8 (Ruff E402/I001).

## [0.1.0] - 2026-08-15

### Added
- API REST BuscaCEP construída em FastAPI com integração à API pública do ViaCEP.
- Worker assíncrono para consumo e processamento de eventos publicados via Cloud Pub/Sub.
- Instrumentação de observabilidade com OpenTelemetry SDK (traces e logs correlacionados via traceparent) e exportador contínuo de profiling via Grafana Pyroscope.
- Suíte de testes unitários com dublês e testes de integração de cliente HTTP com WireMock em Docker.
- Manifestos Kubernetes (Deployment, Service, HPA, ServiceAccount) e pipeline de entrega contínua via GitHub Actions com Workload Identity.
- Metadados de catálogo CNCF Backstage/Port (`catalog-info.yaml`).
