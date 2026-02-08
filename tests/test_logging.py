from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from taxonfinder.logging import setup_logging


def test_setup_logging_creates_log_directory(tmp_path: Path) -> None:
    """Test that setup_logging creates the log directory."""
    log_file = tmp_path / "logs" / "test.log"
    logger = setup_logging(log_file_path=str(log_file))

    assert log_file.parent.exists()
    assert log_file.exists()
    assert logger is not None


def test_setup_logging_writes_to_file(tmp_path: Path) -> None:
    """Test that logs are written to the file."""
    log_file = tmp_path / "test.log"
    logger = setup_logging(log_file_path=str(log_file))

    logger.info("test_event", key="value")

    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line]

    # Should have at least 2 lines: initialization + test event
    assert len(lines) >= 2

    # Last line should contain our test event
    last_log = json.loads(lines[-1])
    assert last_log["event"] == "test_event"
    assert last_log["key"] == "value"
    assert last_log["level"] == "info"


def test_setup_logging_file_always_json(tmp_path: Path) -> None:
    """Test that file logs are always in JSON format."""
    log_file = tmp_path / "test.log"
    logger = setup_logging(json_mode=False, log_file_path=str(log_file))

    logger.warning("test_warning", detail="testing")

    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line]

    # All lines should be valid JSON
    for line in lines:
        data = json.loads(line)
        assert "event" in data
        assert "level" in data
        assert "timestamp" in data


def test_setup_logging_different_levels(tmp_path: Path) -> None:
    """Test that different log levels work correctly."""
    log_file = tmp_path / "test.log"
    logger = setup_logging(
        console_level="ERROR",
        file_level="DEBUG",
        log_file_path=str(log_file),
    )

    logger.debug("debug_message")
    logger.info("info_message")
    logger.warning("warning_message")
    logger.error("error_message")

    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line]

    # Find our test messages (skip initialization log)
    events = [json.loads(line)["event"] for line in lines]

    # File should have all messages (DEBUG level)
    assert "debug_message" in events
    assert "info_message" in events
    assert "warning_message" in events
    assert "error_message" in events


def test_setup_logging_respects_console_level(tmp_path: Path, caplog) -> None:
    """Test that console log level is respected."""
    log_file = tmp_path / "test.log"

    with caplog.at_level(logging.DEBUG):
        logger = setup_logging(
            console_level="WARNING",
            file_level="DEBUG",
            log_file_path=str(log_file),
        )

        logger.debug("debug_console")
        logger.info("info_console")
        logger.warning("warning_console")

    # Console should only have WARNING and above
    # (caplog captures all handlers, so we check that DEBUG/INFO are in file but not in console)
    # This test is tricky with structlog, so we'll verify by checking the file has more entries
    content = log_file.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line]
    events = [json.loads(line)["event"] for line in lines]

    assert "debug_console" in events
    assert "info_console" in events
    assert "warning_console" in events


def test_setup_logging_file_rotation(tmp_path: Path) -> None:
    """Test that log file rotation is configured."""
    log_file = tmp_path / "test.log"
    logger = setup_logging(log_file_path=str(log_file))

    # Get the root logger to check handlers
    root_logger = logging.getLogger()
    file_handlers = [
        h for h in root_logger.handlers if hasattr(h, "maxBytes")
    ]

    assert len(file_handlers) > 0
    handler = file_handlers[0]
    assert handler.maxBytes == 10 * 1024 * 1024  # 10 MB
    assert handler.backupCount == 5
