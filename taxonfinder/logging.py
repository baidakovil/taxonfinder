from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog


def setup_logging(
    json_mode: bool = False,
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    log_file_path: str = "logs/taxonfinder.log",
) -> structlog.BoundLogger:
    """Setup structured logging with console and file outputs.

    Args:
        json_mode: If True, use JSON formatting; otherwise human-readable
        console_level: Log level for console output (DEBUG, INFO, WARNING, ERROR)
        file_level: Log level for file output (DEBUG, INFO, WARNING, ERROR)
        log_file_path: Path to log file (directory created automatically)

    Returns:
        Configured structlog logger
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert string levels to logging constants
    console_log_level = getattr(logging, console_level.upper(), logging.INFO)
    file_log_level = getattr(logging, file_level.upper(), logging.DEBUG)

    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(min(console_log_level, file_log_level))

    # Common processors for structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_log_level)
    if json_mode:
        # JSON output for console (production mode)
        console_formatter = logging.Formatter("%(message)s")
    else:
        # Human-readable output for console (development mode)
        console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation (10MB max, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(file_log_level)
    # Always use JSON format for file logs (easier to parse)
    file_formatter = logging.Formatter("%(message)s")
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Configure structlog
    if json_mode:
        # JSON renderer for production
        renderer = structlog.processors.JSONRenderer()
    else:
        # Colored, human-readable renderer for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Setup ProcessorFormatter for each handler
    console_formatter_struct = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    console_handler.setFormatter(console_formatter_struct)

    file_formatter_struct = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),  # Always JSON for file
        ],
    )
    file_handler.setFormatter(file_formatter_struct)

    logger = structlog.get_logger()
    logger.info(
        "logging_initialized",
        console_level=console_level,
        file_level=file_level,
        log_file=log_file_path,
        json_mode=json_mode,
    )

    return logger
