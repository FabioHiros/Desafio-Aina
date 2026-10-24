import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Defesa em profundidade: o código não loga PII, mas se algo escapar, sequências longas de dígitos
# (telefones formatados ou não, e também datas como 1990-05-10) são mascaradas antes de sair.
_DIGIT_RUN = re.compile(r"\+?\d[\d\s().-]{8,}\d")


def redact(text: str) -> str:
    return _DIGIT_RUN.sub("[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por log, com request_id para correlacionar e mensagem já mascarada."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False
    # O middleware de requisição já loga método, rota, status e duração com request_id, e sem query string
    # (que pode carregar ids). O access log do uvicorn seria uma cópia pior.
    logging.getLogger("uvicorn.access").disabled = True
