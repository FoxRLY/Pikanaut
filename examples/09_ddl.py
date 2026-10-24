"""09 — схема из модели: CREATE TABLE / INDEX / DROP.

Запуск: uv run python examples/09_ddl.py

Что показывает:
  * ddl.create() отдаёт список statement'ов: таблица + индексы, каждый можно выполнить отдельно;
  * диалект решает типы и идентичность: rowid в sqlite, GENERATED ... AS IDENTITY в postgres;
  * DDL — тоже чистый генератор: ни соединения, ни параметров, только текст;
  * незнакомый тип не превращается в TEXT молча — SchemaError с подсказкой Col(type=...).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, SchemaError, client, columns, ddl, table
from pikanaut.dialects import POSTGRES, SQLITE


@table("orders")
class Order(BaseModel):
    id: Annotated[int | None, Col(pk=True)] = None  # выдаёт база
    customer: Annotated[str, Col(index=True)]
    email: Annotated[str, Col(unique=True)]
    amount: Decimal
    created_at: Annotated[datetime, Col(default=ddl.NOW)]
    note: str | None = None


@table("weird")
class Weird(BaseModel):
    id: Annotated[int, Col(pk=True)]
    payload: complex  # нет переносимого SQL-типа


def main() -> None:
    print("SQLite:")
    for statement in ddl.create(Order, dialect=SQLITE):
        print("  ", statement.sql)

    print("\nPostgres:")
    for statement in ddl.create(Order, dialect=POSTGRES):
        print("  ", statement.sql)

    print("\nDROP:", ddl.drop(Order, dialect=SQLITE).sql)

    # Схема работает: создаём и сразу пользуемся обычными запросами
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Order, dialect=SQLITE):
        conn.execute(statement.sql)

    db = client(SQLITE)
    O = columns(Order)
    # Внимание: DEFAULT CURRENT_TIMESTAMP живёт в БД, но не освобождает модель
    # от обязательного поля — pydantic требует created_at при создании объекта.
    insert = db.insert(
        Order(
            customer="ann",
            email="ann@corp.com",
            amount=Decimal("10.50"),
            created_at=datetime(2026, 10, 20, 9, 30),
        )
    ).build()
    conn.execute(insert.sql, insert.params)

    select = db.select(O.id, O.customer, O.amount, O.created_at).build()
    print("\nrows:", conn.execute(select.sql, select.params).fetchall())

    # Незнакомый тип — явная ошибка, а не TEXT по умолчанию
    try:
        ddl.create(Weird, dialect=SQLITE)
    except SchemaError as exc:
        print("\nSchemaError:", exc)


if __name__ == "__main__":
    main()
