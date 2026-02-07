from __future__ import annotations

import logging

import structlog


def setup_logging(json_mode: bool) -> structlog.BoundLogger:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    processors = [
        structlog.processors.add_log_level,
        timestamper,
    ]

    if json_mode:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger()
