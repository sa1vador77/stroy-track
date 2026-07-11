"""Настройка structlog, общая для всех процессов приложения."""

import logging

import structlog


def configure_logging(*, json_logs: bool) -> None:
    """Общая настройка логов для всех сервисов: JSON в проде, читаемый вывод в dev."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
