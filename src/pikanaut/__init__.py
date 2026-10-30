"""pikanaut — генератор SQL из типизированных моделей pydantic.

Библиотека не исполняет запросы и не превращает строки в объекты: на выходе
всегда ``Sql(sql, params, dialect)``. См. SPEC.md.
"""

from __future__ import annotations

from . import defaults
from .build import Sql
from .client import Client, client
from .defaults import GENERATED, Generated, Identity
from .errors import (
    PikanautError,
    QueryError,
    QueryTooLong,
    SchemaError,
    UnsupportedFeature,
    UnsupportedOperation,
)
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
from .fields import (
    BoolColumn,
    BytesColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntColumn,
    JsonColumn,
    StrColumn,
    TimeColumn,
    UuidColumn,
)
from .schema import TableModel
from .tables import Table

__all__ = [
    "BoolColumn",
    "BytesColumn",
    "Client",
    "Column",
    "Cond",
    "DateColumn",
    "DateTimeColumn",
    "DecimalColumn",
    "FloatColumn",
    "GENERATED",
    "Generated",
    "Identity",
    "IntColumn",
    "JsonColumn",
    "PikanautError",
    "QueryError",
    "QueryTooLong",
    "SchemaError",
    "Sql",
    "StrColumn",
    "Table",
    "TableModel",
    "TimeColumn",
    "UnsupportedFeature",
    "UnsupportedOperation",
    "UuidColumn",
    "and_",
    "avg",
    "coalesce",
    "client",
    "count",
    "defaults",
    "lower",
    "max",
    "min",
    "not_",
    "or_",
    "raw",
    "sum",
    "upper",
]
