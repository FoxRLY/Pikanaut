"""pikanaut — генератор SQL из типизированных моделей pydantic.

Библиотека не исполняет запросы и не превращает строки в объекты: на выходе
всегда ``Sql(sql, params, dialect)``. См. SPEC.md.
"""

from __future__ import annotations

from .build import Sql
from .client import Client, client
from .errors import PikanautError, QueryError, QueryTooLong, SchemaError, UnsupportedFeature
from .expr import (
    Column,
    Cond,
    and_,
    avg,
    coalesce,
    count,
    lower,
    max,
    min,
    not_,
    or_,
    raw,
    sum,
    upper,
)
from .schema import Col, Columns, Skip, columns, table

__all__ = [
    "Client",
    "Col",
    "Column",
    "Columns",
    "Cond",
    "PikanautError",
    "QueryError",
    "QueryTooLong",
    "SchemaError",
    "Skip",
    "Sql",
    "UnsupportedFeature",
    "and_",
    "avg",
    "coalesce",
    "client",
    "columns",
    "count",
    "lower",
    "max",
    "min",
    "not_",
    "or_",
    "raw",
    "sum",
    "upper",
    "table",
]
