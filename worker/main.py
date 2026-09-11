"""Worker — consome eventos de consulta de CEP do Pub/Sub.

Roda como processo separado da API. Sua existência cria a superfície de falha
desacoplada que queremos testar com o agente de IA:
  - Worker morto: mensagens acumulam, oldest_unacked_message_age sobe.
  - Subscription errada: mensagens nunca chegam ao consumidor certo.
  - Dead-letter queue: mensagens que falharam N vezes são redirecionadas.

Execute localmente (com emulador ativo):
    PUBSUB_EMULATOR_HOST=localhost:8085 \
    PUBSUB_PROJECT_ID=buscacep-local \
    python -m worker.main
"""

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PUBSUB_PROJECT_ID", "buscacep-local")
TOPIC_ID = os.getenv("PUBSUB_TOPIC_ID", "cep-consultado")
SUBSCRIPTION_ID = os.getenv("PUBSUB_SUBSCRIPTION_ID", "cep-consultado-sub")

# Presente apenas no ambiente local com emulador. Em GCP, os recursos são
# criados pelo Terraform e a GSA não tem permissão de criação.
_MODO_EMULADOR = bool(os.getenv("PUBSUB_EMULATOR_HOST"))
_HEALTH_PORT = int(os.getenv("WORKER_HEALTH_PORT", "8000"))

# Instrumentação OpenTelemetry
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
ENABLE_CLOUD_TRACE = os.getenv("ENABLE_CLOUD_TRACE", "true").lower() == "true"

resource = Resource.create({"service.name": "buscacep-worker"})
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
tracer = trace.get_tracer("buscacep-worker")

# Logging OTel
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
if OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        log_headers = {}
        if os.getenv("OTEL_EXPORTER_OTLP_HEADERS"):
            for h in os.getenv("OTEL_EXPORTER_OTLP_HEADERS").split(","):
                if "=" in h:
                    k, v = h.split("=", 1)
                    log_headers[k.strip()] = v.strip()

        logger_provider = LoggerProvider(resource=resource)
        set_logger_provider(logger_provider)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, headers=log_headers))
        )
        handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        logging.getLogger().addHandler(handler)
        logger.info("Logging OTel habilitado via OTLP: %s", OTEL_EXPORTER_OTLP_LOGS_ENDPOINT)
    except Exception as exc:
        logger.warning("Nao foi possivel inicializar OTLPLogExporter: %s", exc)

# Continuous Profiling (Pyroscope)
PYROSCOPE_SERVER_ADDRESS = os.getenv("PYROSCOPE_SERVER_ADDRESS")
if PYROSCOPE_SERVER_ADDRESS:
    try:
        import pyroscope

        pyroscope.configure(
            application_name="buscacep-worker",
            server_address=PYROSCOPE_SERVER_ADDRESS,
            tags={"service_name": "buscacep-worker"},
        )
        logger.info("Pyroscope continuous profiling habilitado: %s", PYROSCOPE_SERVER_ADDRESS)
    except Exception as exc:
        logger.warning("Nao foi possivel inicializar Pyroscope: %s", exc)


def _garantir_recursos() -> tuple:
    """Cria tópico e subscription se não existirem. Retorna (subscriber, subscription_path)."""
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import pubsub_v1

    pub = pubsub_v1.PublisherClient()
    sub = pubsub_v1.SubscriberClient()

    topic_path = pub.topic_path(PROJECT_ID, TOPIC_ID)
    subscription_path = sub.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

    try:
        pub.create_topic(request={"name": topic_path})
        logger.info("Tópico criado: %s", topic_path)
    except AlreadyExists:
        logger.info("Tópico já existe: %s", topic_path)

    try:
        sub.create_subscription(request={"name": subscription_path, "topic": topic_path})
        logger.info("Subscription criada: %s", subscription_path)
    except AlreadyExists:
        logger.info("Subscription já existe: %s", subscription_path)

    return sub, subscription_path


def _processar(message) -> None:
    """Callback chamado pelo cliente Pub/Sub para cada mensagem recebida."""
    carrier = dict(message.attributes)
    ctx = propagate.extract(carrier)

    with tracer.start_as_current_span("buscacep-worker.process_event", context=ctx) as span:
        try:
            dados = json.loads(message.data.decode())
            cep = dados.get("cep", "?")
            encontrado = dados.get("encontrado", False)
            localidade = dados.get("localidade", "-")
            uf = dados.get("uf", "-")
            ts = dados.get("timestamp_iso", "-")

            span.set_attribute("messaging.system", "pubsub")
            span.set_attribute("messaging.destination", TOPIC_ID)
            span.set_attribute("cep", cep)
            span.set_attribute("encontrado", encontrado)

            trace_id = format(span.get_span_context().trace_id, "032x") if span.get_span_context().is_valid else ""
            if encontrado:
                logger.info(
                    "trace_id=%s CEP consultado no worker | cep=%-9s localidade=%s/%s ts=%s",
                    trace_id, cep, localidade, uf, ts,
                )
            else:
                logger.info("trace_id=%s CEP não encontrado no worker | cep=%-9s ts=%s", trace_id, cep, ts)


        except Exception as exc:
            logger.error("Erro ao processar mensagem (id=%s): %s", message.message_id, exc)
            span.record_exception(exc)
        finally:
            # Ack sempre — em cenários de falha real, comentar esta linha para
            # que as mensagens acumulem na fila e o agente AIOps detecte o backlog.
            message.ack()



class _HealthHandler(BaseHTTPRequestHandler):
    """Handler HTTP mínimo para liveness e readiness probes do GKE."""

    def do_GET(self) -> None:
        if self.path in ("/healthz", "/readyz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_) -> None:
        pass  # silencia logs de acesso no stdout


def _iniciar_health_server() -> None:
    """Sobe o servidor de health em thread daemon — não bloqueia o worker."""
    server = HTTPServer(("", _HEALTH_PORT), _HealthHandler)
    logger.info("Health server escutando na porta %d", _HEALTH_PORT)
    server.serve_forever()


def main() -> None:
    # Health server em background — GKE começa a sondar antes do subscriber estar pronto.
    threading.Thread(target=_iniciar_health_server, daemon=True).start()

    # Em modo emulador (local), o worker cria tópico + subscription porque o
    # Terraform não está gerenciando. Em GCP, o Terraform já criou os recursos
    # e a GSA não tem permissão de criação — pula direto para o consume.
    subscriber = None
    subscription_path = None
    for tentativa in range(1, 11):
        try:
            if _MODO_EMULADOR:
                subscriber, subscription_path = _garantir_recursos()
            else:
                from google.cloud import pubsub_v1
                subscriber = pubsub_v1.SubscriberClient()
                subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
                logger.info("Modo GCP: usando subscription existente '%s'", subscription_path)
            break
        except Exception as exc:
            logger.warning(
                "Tentativa %d/10: Pub/Sub indisponível, aguardando 3s... (%s)",
                tentativa, exc,
            )
            time.sleep(3)
    else:
        raise RuntimeError("Pub/Sub indisponível após 10 tentativas.")

    logger.info("Worker pronto. Consumindo mensagens de '%s' ...", subscription_path)

    streaming_pull = subscriber.subscribe(subscription_path, callback=_processar)

    with subscriber:
        try:
            # Bloqueia indefinidamente até interrupção ou erro.
            streaming_pull.result()
        except KeyboardInterrupt:
            streaming_pull.cancel()
            streaming_pull.result()  # Aguarda cancelamento limpo.
            logger.info("Worker encerrado (KeyboardInterrupt).")


if __name__ == "__main__":
    main()
