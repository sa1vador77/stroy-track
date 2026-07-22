"""Тесты моста stdlib-логов в общий structlog-форматтер."""

import json
import logging
import sys

import pytest
import structlog

from app.core.logging import configure_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    """configure_logging меняет глобальное состояние — возвращаем его после теста."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    yield
    root.handlers, root.level = saved_handlers, saved_level
    structlog.reset_defaults()


def _stdlib_record(**overrides) -> logging.LogRecord:
    defaults = dict(
        name="aiogram.event",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Update id=%s handled",
        args=(7,),
        exc_info=None,
    )
    return logging.LogRecord(**{**defaults, **overrides})


def _format(record: logging.LogRecord) -> str:
    [handler] = logging.getLogger().handlers
    return handler.format(record)


def test_stdlib_record_rendered_as_json():
    configure_logging(json_logs=True)

    entry = json.loads(_format(_stdlib_record()))

    assert entry["event"] == "Update id=7 handled"
    assert entry["level"] == "info"
    assert "timestamp" in entry


def test_stdlib_exception_rendered_in_json():
    configure_logging(json_logs=True)
    try:
        raise ValueError("boom")
    except ValueError:
        record = _stdlib_record(level=logging.ERROR, exc_info=sys.exc_info())

    entry = json.loads(_format(record))

    assert "boom" in entry["exception"]


def test_console_mode_renders_readable_text():
    configure_logging(json_logs=False)

    line = _format(_stdlib_record())

    assert "Update id=7 handled" in line


def test_console_mode_renders_exception():
    configure_logging(json_logs=False)
    try:
        raise ValueError("boom")
    except ValueError:
        record = _stdlib_record(level=logging.ERROR, exc_info=sys.exc_info())

    line = _format(record)

    assert "ValueError: boom" in line


def test_reconfigure_does_not_stack_handlers():
    configure_logging(json_logs=True)
    configure_logging(json_logs=True)

    assert len(logging.getLogger().handlers) == 1
