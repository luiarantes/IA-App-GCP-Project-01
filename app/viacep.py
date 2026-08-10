"""Cliente HTTP para a API pública do ViaCEP (https://viacep.com.br)."""

import os

import httpx

# Permite trocar a base URL via env var — essencial para apontar ao WireMock
# em testes de integração sem alterar o código.
_BASE_URL = os.getenv("VIACEP_BASE_URL", "https://viacep.com.br")
VIACEP_URL = _BASE_URL.rstrip("/") + "/ws/{cep}/json/"
TIMEOUT_SECONDS = 5.0


class CepNaoEncontradoError(Exception):
    """O CEP tem formato válido, mas não existe na base do ViaCEP."""


class UpstreamIndisponivelError(Exception):
    """Falha de rede, timeout ou resposta inválida do ViaCEP."""


async def consultar(cep: str) -> dict:
    """Consulta um CEP (8 dígitos, já normalizado) e retorna o JSON do ViaCEP."""
    url = VIACEP_URL.format(cep=cep)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resposta = await client.get(url)
            resposta.raise_for_status()
            dados = resposta.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UpstreamIndisponivelError(str(exc)) from exc

    # O ViaCEP responde 200 com {"erro": true} em dois cenários distintos:
    #   1. CEP com formato válido mas inexistente na base.
    #   2. Rate limiting / instabilidade do upstream sob alta concorrência
    #      (o ViaCEP retorna o mesmo corpo que o caso 1 — impossível distinguir
    #      via API). Se esse log aparecer para um CEP reconhecidamente válido,
    #      o provável culpado é throttling do upstream, não ausência do CEP.
    if dados.get("erro"):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "viacep retornou {erro:true} para cep=%s — "
            "CEP inexistente ou upstream com throttling",
            cep,
        )
        raise CepNaoEncontradoError(cep)

    return dados
