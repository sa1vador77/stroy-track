"""Общее для схем API."""

from typing import Any

from pydantic import model_validator


def no_null_updates(*clearable: str) -> Any:
    """Валидатор PATCH-схем: явный null допустим только для очищаемых (nullable в БД)
    полей — там он означает «сбросить значение»; для остальных это ошибка клиента."""

    def _check(self: Any) -> Any:
        for name in self.model_fields_set - set(clearable):
            if getattr(self, name) is None:
                raise ValueError(f"поле {name} не может быть null")
        return self

    return model_validator(mode="after")(_check)
