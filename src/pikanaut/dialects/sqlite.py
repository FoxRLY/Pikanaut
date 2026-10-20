"""SQLite: два класса — с RETURNING (>= 3.35) и без.

Адаптация значений — самая заметная часть: у sqlite нет bool/date/uuid как типов,
всё лежит в INTEGER/TEXT, поэтому приведение обязательно (SPEC.md, 5.1).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from .base import Dialect, Feature


def _adapt_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value


class SQLite(Dialect):
    name = "sqlite"
    features = frozenset({Feature.RETURNING, Feature.UPSERT})
    engine_max_sql_bytes = 1_000_000_000
    engine_max_params = 32_766

    def placeholder(self, index: int) -> str:
        return "?"

    def adapt(self, value: Any) -> Any:
        return _adapt_value(value)


class SQLite34(Dialect):
    """sqlite < 3.35: всё то же, кроме RETURNING."""

    name = "sqlite-3.4"
    features = frozenset({Feature.UPSERT})
    engine_max_sql_bytes = 1_000_000_000
    engine_max_params = 32_766

    def placeholder(self, index: int) -> str:
        return "?"

    def adapt(self, value: Any) -> Any:
        return _adapt_value(value)


SQLITE = SQLite()
SQLITE_34 = SQLite34()
