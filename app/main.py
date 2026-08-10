"""BuscaCEP — API e frontend de consulta de CEP."""

import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from app import publisher, viacep

APP_VERSION = "0.1.0"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="BuscaCEP", version=APP_VERSION)

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
