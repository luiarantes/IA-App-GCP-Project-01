"""Fixtures de integração: sobe e derruba o WireMock via Docker."""

import subprocess
import time
from pathlib import Path

import httpx
import pytest

WIREMOCK_IMAGE = "wiremock/wiremock:3.13.0"
WIREMOCK_PORT = 9090
WIREMOCK_URL = f"http://localhost:{WIREMOCK_PORT}"
MAPPINGS_DIR = Path(__file__).resolve().parents[2] / "wiremock" / "mappings"


def _aguardar_wiremock(timeout: int = 20) -> None:
    """Aguarda o WireMock responder no /__admin/health antes de rodar os testes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{WIREMOCK_URL}/__admin/health", timeout=2)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"WireMock não respondeu em {timeout}s — verifique o Docker.")


@pytest.fixture(scope="session")
def wiremock():
    """
    Sobe um container WireMock para a sessão de testes e o derruba ao fim.
    Monta a pasta wiremock/mappings/ para que os stubs sejam carregados
    automaticamente, sem precisar registrá-los via API.
    """
    container_name = "buscacep-wiremock-test"

    # Remove container anterior se existir (falha silenciosa intencional).
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
    )

    subprocess.run(
        [
            "docker", "run", "--rm", "--detach",
            "--name", container_name,
            "-p", f"{WIREMOCK_PORT}:8080",
            "-v", f"{MAPPINGS_DIR}:/home/wiremock/mappings",
            WIREMOCK_IMAGE,
        ],
        check=True,
    )

    _aguardar_wiremock()

    yield WIREMOCK_URL

    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
