"""Часы компании: единое «сегодня» для отчётов бота и напоминаний."""

from datetime import date, datetime

from app.core.config import get_settings


def company_today() -> date:
    # дата считается в поясе компании: вечерний отчёт по UTC-дате уехал бы
    # на другой день; SQL CURRENT_DATE не подходит по той же причине
    return datetime.now(get_settings().company_tzinfo).date()
