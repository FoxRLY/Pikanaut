"""Иерархия ошибок (SPEC.md, раздел 7)."""

from __future__ import annotations

from typing import Any


class PikanautError(Exception):
    """Базовая ошибка библиотеки."""


class SchemaError(PikanautError):
    """Модель нельзя превратить в таблицу: дубли колонок, TypeVar, все поля Skip и т.п."""


class UnsupportedFeature(PikanautError):
    """Диалект не поддерживает запрошенную возможность."""

    def __init__(self, dialect: str, feature: str, hint: str = "") -> None:
        self.dialect = dialect
        self.feature = feature
        self.hint = hint
        message = f"{dialect} does not support {feature}"
        if hint:
            message = f"{message} — {hint}"
        super().__init__(message)


class QueryError(PikanautError):
    """Запрос нельзя собрать: пустой WHERE, пустой IN, нечего вставлять."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        self.hint = hint
        super().__init__(f"{message} — {hint}" if hint else message)


class QueryTooLong(QueryError):
    """Запрос превысил лимит сборки: число параметров или длина текста.

    ``kind`` — ``"params"`` или ``"sql_bytes"``. Лимит политический: он может быть
    строже предела движка, поэтому в сообщении приводятся оба числа.
    """

    def __init__(
        self,
        message: str,
        *,
        length: int,
        limit: int,
        kind: str,
        dialect: str,
        hint: str = "",
    ) -> None:
        self.length = length
        self.limit = limit
        self.kind = kind
        self.dialect_name = dialect
        super().__init__(message, hint=hint)


def describe(value: Any) -> str:
    """Короткое описание значения для текста ошибки (модель, колонка, тип)."""
    raise NotImplementedError
