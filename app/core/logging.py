import contextvars
import json
import logging
import re

request_id = contextvars.ContextVar("request_id", default="-")
_TICKET = re.compile(r"ticket=[^&\s\"]+")


class RedactTicket(logging.Filter):
    """Ссылка входа не должна попасть в access-лог."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "ticket=" in record.msg:
            record.msg = _TICKET.sub("ticket=redacted", record.msg)
        if record.args:
            record.args = tuple(
                _TICKET.sub("ticket=redacted", item) if isinstance(item, str) else item
                for item in record.args
            )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactTicket())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactTicket())
