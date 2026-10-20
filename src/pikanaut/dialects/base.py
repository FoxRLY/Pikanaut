"""Диалект — объект с флагами возможностей, лимитами и адаптацией значений."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, FrozenSet

DEFAULT_MAX_SQL_BYTES = 1_000_000
DEFAULT_MAX_PARAMS = 10_000


@dataclass(frozen=True, slots=True)
class Limits:
    """Лимиты сборки. ``None`` — не проверять.

    По умолчанию — политические, с запасом относительно пределов движка,
    чтобы ошибка приходила рано и с понятным текстом (SPEC.md, 5.1).
    """

    max_sql_bytes: int | None = DEFAULT_MAX_SQL_BYTES
    max_params: int | None = DEFAULT_MAX_PARAMS


class Feature(StrEnum):
    RETURNING = "returning"
    SCHEMA = "schema"
    UPSERT = "upsert"
    ILIKE = "ilike"
    FOR_UPDATE = "for_update"
    ARRAYS = "arrays"


class Dialect:
    """База: то, что обязано различаться между диалектами."""

    name: str = "base"
    features: FrozenSet[Feature] = frozenset()
    quote_char: str = '"'
    limits: Limits = Limits()
    engine_max_sql_bytes: int | None = None
    engine_max_params: int | None = None

    def __init__(self, *, limits: Limits | None = None) -> None:
        if limits is not None:
            self.limits = limits

    def placeholder(self, index: int) -> str:
        raise NotImplementedError

    def adapt(self, value: Any) -> Any:
        raise NotImplementedError

    def in_list(
        self,
        column_sql: str,
        binder: Any,
        values: list[Any],
        negate: bool = False,
    ) -> str:
        """``IN (?,?,?)`` по умолчанию; диалекты с массивами переопределяют."""
        marks = ",".join(binder.bind(value) for value in values)
        operator = "NOT IN" if negate else "IN"
        return f"{column_sql} {operator} ({marks})"

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def __repr__(self) -> str:
        return f"<dialect {self.name}>"
