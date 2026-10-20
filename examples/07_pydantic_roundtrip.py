"""07 — граница с pydantic: гидрация строк на стороне пользователя.

Запуск: uv run python examples/07_pydantic_roundtrip.py

pikanaut не превращает строки в объекты — это работа pydantic. Здесь показано,
как выглядит полный цикл: модель → SQL → драйвер → снова модель, с валидацией
и приведением типов на выходе.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, TypeAdapter

from pikanaut import Col, client, columns, ddl, table
from pikanaut.dialects import SQLITE

@table("events")
class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int | None, Col(pk=True)] = None
    name: str
    happened_at: datetime


def main() -> None:
    db = client(SQLITE)
    E = columns(Event)

    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Event, dialect=SQLITE):
        conn.execute(statement.sql)

    statement = db.insert(Event(name="deploy", happened_at=datetime(2026, 10, 20, 9, 30))).build()
    print("INSERT:", statement.sql)
    print("params:", statement.params, "  <- datetime стал ISO-строкой для sqlite")
    conn.execute(statement.sql, statement.params)

    select = db.select(E.id, E.name, E.happened_at).order_by(E.id.asc()).build()
    print("\nSELECT:", select.sql)

    cursor = conn.execute(select.sql, select.params)
    names = [description[0] for description in cursor.description]
    rows = cursor.fetchall()

    # Колонки -> модель. Валидация, дефолты и ошибки — целиком pydantic.
    adapter = TypeAdapter(Event)
    events = [adapter.validate_python(dict(zip(names, row))) for row in rows]
    for event in events:
        print("  ", event, "|", type(event.happened_at).__name__)

    # Если строка не подходит под модель — обычная pydantic-ошибка, а не молчаливый None.
    try:
        adapter.validate_python({"id": 1, "name": "x", "happened_at": "not-a-date"})
    except Exception as exc:  # noqa: BLE001
        print("\nвалидация:", type(exc).__name__, "—", str(exc).splitlines()[0])


if __name__ == "__main__":
    main()
