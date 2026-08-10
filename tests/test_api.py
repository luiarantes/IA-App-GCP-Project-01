"""Testes da API BuscaCEP.

A chamada ao ViaCEP é substituída por dublês (monkeypatch) para que os testes
rodem sem acesso à internet e sem depender do serviço externo.
"""

import pytest
from fastapi.testclient import TestClient

from app import viacep
from app.main import app

client = TestClient(app)

ENDERECO_VIACEP = {
    "cep": "01310-100",
    "logradouro": "Avenida Paulista",
    "complemento": "de 612 a 1510 - lado par",
    "bairro": "Bela Vista",
    "localidade": "São Paulo",
    "uf": "SP",
    "ddd": "11",
}


def test_cep_valido_retorna_endereco(monkeypatch):
    async def consultar_fake(cep):
        assert cep == "01310100"
        return ENDERECO_VIACEP

    monkeypatch.setattr(viacep, "consultar", consultar_fake)

    resposta = client.get("/api/cep/01310-100")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["cep"] == "01310-100"
    assert corpo["logradouro"] == "Avenida Paulista"
    assert corpo["localidade"] == "São Paulo"
    assert corpo["uf"] == "SP"


def test_cep_com_formato_invalido_retorna_400():
    resposta = client.get("/api/cep/123")

    assert resposta.status_code == 400
    assert "inválido" in resposta.json()["detail"]


def test_cep_inexistente_retorna_404(monkeypatch):
    async def consultar_fake(cep):
        raise viacep.CepNaoEncontradoError(cep)

    monkeypatch.setattr(viacep, "consultar", consultar_fake)

    resposta = client.get("/api/cep/99999-999")

    assert resposta.status_code == 404


def test_upstream_indisponivel_retorna_502(monkeypatch):
    async def consultar_fake(cep):
        raise viacep.UpstreamIndisponivelError("timeout")

    monkeypatch.setattr(viacep, "consultar", consultar_fake)

    resposta = client.get("/api/cep/01310-100")

    assert resposta.status_code == 502


def test_healthz():
    resposta = client.get("/healthz")

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


def test_readyz():
    resposta = client.get("/readyz")

    assert resposta.status_code == 200


def test_metrics_expoe_formato_prometheus():
    client.get("/healthz")

    resposta = client.get("/metrics")

    assert resposta.status_code == 200
    assert "http_requests_total" in resposta.text


def test_frontend_na_raiz():
    resposta = client.get("/")

    assert resposta.status_code == 200
    assert "BuscaCEP" in resposta.text
