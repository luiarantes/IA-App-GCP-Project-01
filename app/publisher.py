"""Publicador de eventos de consulta de CEP no Google Pub/Sub.

Fire-and-forget: falhas são logadas mas nunca propagadas para o caller.
Se PUBSUB_PROJECT_ID não estiver configurado, todas as chamadas são no-op
— a app funciona normalmente sem Pub/Sub.
"""

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_PROJECT_ID = os.getenv("PUBSUB_PROJECT_ID", "")
_TOPIC_ID = os.getenv("PUBSUB_TOPIC_ID", "cep-consultado")

# Client criado sob demanda para não bloquear o startup da app.
_client = None


def _get_client():
    global _client
    if _client is None:
        from google.cloud import pubsub_v1
        _client = pubsub_v1.PublisherClient()
    return _client


def _on_publish(future) -> None:
    """Callback chamado quando o Pub/Sub confirma (ou recusa) a mensagem."""
    exc = future.exception()
    if exc:
        logger.warning("Falha ao publicar evento no Pub/Sub: %s", exc)


def publicar_consulta(cep: str, encontrado: bool, dados: dict | None = None) -> None:
    """Publica um evento de consulta no tópico configurado.

    Args:
        cep:       CEP consultado (8 dígitos, sem hífen).
        encontrado: True se o ViaCEP retornou um endereço válido.
        dados:     Dados retornados pelo ViaCEP (opcional, só quando encontrado=True).
    """
    if not _PROJECT_ID:
        return  # Pub/Sub não configurado — no-op silencioso.

    evento: dict = {
        "cep": cep,
        "encontrado": encontrado,
        "timestamp_iso": datetime.now(UTC).isoformat(),
    }
    if encontrado and dados:
        evento["localidade"] = dados.get("localidade", "")
        evento["uf"] = dados.get("uf", "")

    try:
        client = _get_client()
        topic_path = client.topic_path(_PROJECT_ID, _TOPIC_ID)
        payload = json.dumps(evento, ensure_ascii=False).encode()
        future = client.publish(topic_path, payload)
        future.add_done_callback(_on_publish)
    except Exception as exc:
        logger.warning("Erro ao iniciar publicação no Pub/Sub: %s", exc)
