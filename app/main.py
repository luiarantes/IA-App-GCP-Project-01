import logging
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from app import publisher, viacep

logger = logging.getLogger("buscacep-api")

# Instrumentação OpenTelemetry
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

PROJECT_ID = os.environ.get("PUBSUB_PROJECT_ID", "aiops-local")
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
ENABLE_CLOUD_TRACE = os.environ.get("ENABLE_CLOUD_TRACE", "true").lower() == "true"

resource = Resource.create({"service.name": "buscacep-api"})
provider = TracerProvider(resource=resource)

if OTEL_EXPORTER_OTLP_ENDPOINT:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    headers = {}
    if os.environ.get("OTEL_EXPORTER_OTLP_HEADERS"):
        for h in os.environ["OTEL_EXPORTER_OTLP_HEADERS"].split(","):
            if "=" in h:
                k, v = h.split("=", 1)
                headers[k.strip()] = v.strip()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT, headers=headers)))
    logger.info("Tracing OTel habilitado via OTLP: %s", OTEL_EXPORTER_OTLP_ENDPOINT)
elif ENABLE_CLOUD_TRACE and PROJECT_ID not in ("aiops-local", "buscacep-local", ""):
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=PROJECT_ID)))
        logger.info("Tracing OTel habilitado via CloudTraceSpanExporter (GCP)")
    except Exception as exc:
        logger.warning("Nao foi possivel inicializar CloudTraceSpanExporter: %s", exc)

trace.set_tracer_provider(provider)

# Logging OTel
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
if OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        log_headers = {}
        if os.environ.get("OTEL_EXPORTER_OTLP_HEADERS"):
            for h in os.environ["OTEL_EXPORTER_OTLP_HEADERS"].split(","):
                if "=" in h:
                    k, v = h.split("=", 1)
                    log_headers[k.strip()] = v.strip()

        logger_provider = LoggerProvider(resource=resource)
        set_logger_provider(logger_provider)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, headers=log_headers))
        )
        handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        for log_name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "buscacep-api"):
            lg = logging.getLogger(log_name)
            lg.addHandler(handler)
            lg.setLevel(logging.INFO)
        logger.info("Logging OTel habilitado via OTLP: %s", OTEL_EXPORTER_OTLP_LOGS_ENDPOINT)

    except Exception as exc:
        logger.warning("Nao foi possivel inicializar OTLPLogExporter: %s", exc)

# Continuous Profiling (Pyroscope)
PYROSCOPE_SERVER_ADDRESS = os.environ.get("PYROSCOPE_SERVER_ADDRESS")
if PYROSCOPE_SERVER_ADDRESS:
    try:
        import pyroscope

        pyroscope.configure(
            application_name="buscacep-api",
            server_address=PYROSCOPE_SERVER_ADDRESS,
            tags={"service_name": "buscacep-api"},
        )
        logger.info("Pyroscope continuous profiling habilitado: %s", PYROSCOPE_SERVER_ADDRESS)
    except Exception as exc:
        logger.warning("Nao foi possivel inicializar Pyroscope: %s", exc)

HTTPXClientInstrumentor().instrument()


APP_VERSION = "0.1.0"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="BuscaCEP", version=APP_VERSION)
FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total de requisições HTTP",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Duração das requisições HTTP em segundos",
    ["method", "path"],
)


@app.middleware("http")
async def coletar_metricas(request: Request, call_next):
    inicio = time.perf_counter()
    resposta = await call_next(request)
    rota = request.scope.get("route")
    # Usa o template da rota (ex: /api/cep/{cep}) para não explodir a cardinalidade.
    caminho = rota.path if rota else request.url.path
    HTTP_REQUESTS.labels(request.method, caminho, resposta.status_code).inc()
    HTTP_LATENCY.labels(request.method, caminho).observe(time.perf_counter() - inicio)
    return resposta


class Endereco(BaseModel):
    cep: str
    logradouro: str
    complemento: str
    bairro: str
    localidade: str
    uf: str
    ddd: str


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/cep/{cep}", response_model=Endereco)
async def buscar_cep(cep: str) -> Endereco:
    digitos = re.sub(r"\D", "", cep)
    if len(digitos) != 8:
        raise HTTPException(
            status_code=400,
            detail="CEP inválido: informe 8 dígitos (ex: 01310-100).",
        )

    try:
        dados = await viacep.consultar(digitos)
    except viacep.CepNaoEncontradoError:
        publisher.publicar_consulta(digitos, encontrado=False)
        raise HTTPException(status_code=404, detail=f"CEP {digitos} não encontrado.")
    except viacep.UpstreamIndisponivelError:
        raise HTTPException(
            status_code=502,
            detail="Serviço de consulta de CEP indisponível no momento.",
        )

    publisher.publicar_consulta(digitos, encontrado=True, dados=dados)

    span = trace.get_current_span()
    trace_id = format(span.get_span_context().trace_id, "032x") if span.get_span_context().is_valid else ""
    logger.info("trace_id=%s Consulta CEP realizada | cep=%s status=200 localidade=%s/%s", trace_id, digitos, dados.get("localidade", ""), dados.get("uf", ""))

    return Endereco(

        cep=dados.get("cep", ""),
        logradouro=dados.get("logradouro", ""),
        complemento=dados.get("complemento", ""),
        bairro=dados.get("bairro", ""),
        localidade=dados.get("localidade", ""),
        uf=dados.get("uf", ""),
        ddd=dados.get("ddd", ""),
    )


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> dict:
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
