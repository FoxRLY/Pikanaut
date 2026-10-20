"""PostgreSQL: $n-плейсхолдеры, схема, ILIKE, массивы."""

from __future__ import annotations

from typing import Any

from .base import Dialect, Feature


class Postgres(Dialect):
    name = "postgres"
    engine_max_sql_bytes = 1_000_000_000
    engine_max_params = 65_535
    features = frozenset(
        {
            Feature.RETURNING,
            Feature.SCHEMA,
            Feature.UPSERT,
            Feature.ILIKE,
            Feature.FOR_UPDATE,
            Feature.ARRAYS,
        }
    )

    def placeholder(self, index: int) -> str:
        return f"${index}"

    def adapt(self, value: Any) -> Any:
        """Драйвер psycopg разбирается с типами сам — библиотека ничего не трогает."""
        return value

    def in_list(
        self,
        column_sql: str,
        binder: Any,
        values: list[Any],
        negate: bool = False,
    ) -> str:
        operator = "<> ALL" if negate else "= ANY"
        return f"{column_sql} {operator}({binder.bind_array(values)})"


class PostgresPsycopg(Postgres):
    """Postgres для DB-API драйверов (psycopg2/psycopg3): pyformat-плейсхолдеры.

    Сервер понимает только `$n`; psycopg сам переводит `%s` в `$n` и отправляет
    параметры отдельно. Литеральный `%` в тексте запроса у такого драйвера надо
    удваивать — у нас значения всегда в параметрах, поэтому это касается только `raw()`.
    """

    name = "postgres-psycopg"

    def placeholder(self, index: int) -> str:
        return "%s"


POSTGRES = Postgres()
POSTGRES_PSYCOPG = PostgresPsycopg()
