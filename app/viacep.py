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

    # O ViaCEP responde 200 com {"erro": true} quando o CEP não existe.
    if dados.get("erro"):
        raise CepNaoEncontradoError(cep)

    return dados
