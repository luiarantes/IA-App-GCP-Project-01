"""
Testes de integração do cliente ViaCEP (app/viacep.py).

Diferente dos testes unitários (que usam monkeypatch e nunca tocam a rede),
aqui o cliente HTTP real — httpx, timeout, parse do JSON, tratamento do
{"erro": true} — é exercitado contra o WireMock rodando em Docker.
"""

import os

import pytest

# Aponta o cliente para o WireMock antes de importar o módulo.
# A fixture `wiremock` garante que o container já está de pé quando
# este módulo é carregado.
pytestmark = pytest.mark.usefixtures("wiremock")


@pytest.fixture(autouse=True)
def apontar_para_wiremock(wiremock, monkeypatch):
    """Redireciona VIACEP_URL para o WireMock a cada teste."""
    monkeypatch.setenv("VIACEP_BASE_URL", wiremock)
    # Força a reavaliação da URL no módulo (ela é resolvida no import).
    import importlib
    from app import viacep
    monkeypatch.setattr(viacep, "VIACEP_URL", wiremock.rstrip("/") + "/ws/{cep}/json/")


@pytest.mark.anyio
async def test_cep_encontrado_retorna_endereco_completo():
    from app.viacep import consultar

    dados = await consultar("01310100")

    assert dados["cep"] == "01310-100"
    assert dados["logradouro"] == "Avenida Paulista"
    assert dados["localidade"] == "São Paulo"
    assert dados["uf"] == "SP"
    assert dados["ddd"] == "11"


@pytest.mark.anyio
async def test_cep_nao_encontrado_levanta_erro_correto():
    from app.viacep import CepNaoEncontradoError, consultar

    with pytest.raises(CepNaoEncontradoError):
        await consultar("99999999")


@pytest.mark.anyio
async def test_erro_500_upstream_levanta_upstream_indisponivel():
    from app.viacep import UpstreamIndisponivelError, consultar

    with pytest.raises(UpstreamIndisponivelError):
        await consultar("00000000")


@pytest.mark.anyio
async def test_timeout_levanta_upstream_indisponivel():
    """
    O stub retorna com 8s de delay; nosso timeout é 5s.
    O cliente deve levantar UpstreamIndisponivelError antes de o stub responder.
    """
    from app.viacep import UpstreamIndisponivelError, consultar

    with pytest.raises(UpstreamIndisponivelError):
        await consultar("11111111")
