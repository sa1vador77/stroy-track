"""Настройка structlog, общая для всех процессов приложения."""

import logging
import sys

import structlog


def configure_logging(*, json_logs: bool) -> None:
    """Общая настройка логов для всех сервисов: JSON в проде, читаемый вывод в dev."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    # общую часть пайплайна проходят и наши логи, и stdlib-записи aiogram;
    # uvicorn сюда не попадает — он держит свои хендлеры и propagate=False
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if json_logs:
        # только для JSON: ConsoleRenderer рендерит exc_info сам и с
        # format_exc_info несовместим — тот перехватил бы у него трейсбек
        shared.append(structlog.processors.format_exc_info)
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    # stdlib-логи заворачиваются в тот же рендерер: иначе записи aiogram уходят
    # в питоновский last-resort-хендлер — голый stderr и только WARNING+
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    # замена, а не addHandler: повторный вызов не должен дублировать вывод
    root.handlers = [handler]
    root.setLevel(logging.INFO)
