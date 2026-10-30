"""09 — схема из модели: CREATE TABLE / INDEX / DROP.

Запуск: uv run python examples/09_ddl.py

Что показывает:
  * ddl.create() отдаёт список statement'ов: таблица + индексы, каждый можно выполнить отдельно;
  * диалект решает типы и идентичность: rowid в sqlite, GENERATED ... AS IDENTITY в postgres;
  * DDL — тоже чистый генератор: ни соединения, ни параметров, только текст;
  * незнакомый тип не превращается в TEXT молча — SchemaError с указанием поля.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.generated.models import Purchase
from examples.generated.tables import purchases
from pikanaut import IntColumn, SchemaError, TableModel, client, ddl
from pikanaut.dialects import POSTGRES, SQLITE


def main() -> None:
    print("SQLite:")
    for statement in ddl.create(Purchase, dialect=SQLITE):
        print("  ", statement.sql)

    print("\nPostgres:")
    for statement in ddl.create(Purchase, dialect=POSTGRES):
        print("  ", statement.sql)

    print("\nDROP:", ddl.drop(Purchase, dialect=SQLITE).sql)

    # Схема работает: создаём и сразу пользуемся обычными запросами
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Purchase, dialect=SQLITE):
        conn.execute(statement.sql)

    db = client(SQLITE)
    insert = db.insert(
        purchases,
        Purchase(
            customer="ann",
            email="ann@corp.com",
            amount=Decimal("10.50"),
            created_at=datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc),
        ),
    ).build()
    conn.execute(insert.sql, insert.params)

    select = db.select(
        purchases.id, purchases.customer, purchases.amount, purchases.created_at
    ).build()
    print("\nrows:", conn.execute(select.sql, select.params).fetchall())

    # Незнакомый тип — явная ошибка, а не TEXT по умолчанию
    try:

        class _Weird(TableModel, table="weird"):  # pyright: ignore[reportUnusedClass]
            id: int = IntColumn(pk=True)
            payload: complex
    except SchemaError as exc:
        print("\nSchemaError:", exc)


if __name__ == "__main__":
    main()
