"""Иерархия ошибок (SPEC.md, раздел 7)."""

from __future__ import annotations

from typing import Any


class PikanautError(Exception):
    """Базовая ошибка библиотеки."""


class SchemaError(PikanautError):
    """A model cannot be treated as a table: invalid columns, annotations or names."""


class UnsupportedFeature(PikanautError):
    """The selected dialect cannot provide a requested feature."""

    def __init__(self, dialect: str, feature: str, hint: str = "") -> None:
        self.dialect = dialect
        self.feature = feature
        self.hint = hint
        message = f"{dialect} does not support {feature}"
        if hint:
            message = f"{message} — {hint}"
        super().__init__(message)


class UnsupportedOperation(UnsupportedFeature):
    """A value operation is unsafe or unavailable in the selected dialect."""


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
    """Short value description for error messages (model, column, type)."""
    name = getattr(value, "__name__", None)
    if isinstance(name, str):
        return name
    return type(value).__name__
