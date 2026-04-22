import logging
import sys
from contextvars import ContextVar

import structlog

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def configure_logging(level: str = "INFO") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            timestamper,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")


def get_logger(name: str):
    return structlog.get_logger(name)

