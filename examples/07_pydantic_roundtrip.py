"""07 — граница с pydantic: гидрация строк на стороне пользователя.

Запуск: uv run python examples/07_pydantic_roundtrip.py

pikanaut не превращает строки в объекты — это работа pydantic. Здесь показано,
как выглядит полный цикл: модель → SQL → драйвер → снова модель, с валидацией
и приведением типов на выходе.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import TypeAdapter

from examples.generated.models import Event
from examples.generated.tables import events
from pikanaut import client, ddl
from pikanaut.dialects import SQLITE


def main() -> None:
    db = client(SQLITE)

    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Event, dialect=SQLITE):
        conn.execute(statement.sql)

    statement = db.insert(
        events,
        Event(
            name="deploy",
            happened_at=datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc),
        ),
    ).build()
    print("INSERT:", statement.sql)
    print("params:", statement.params, "  <- datetime стал ISO-строкой для sqlite")
    conn.execute(statement.sql, statement.params)

    select = (
        db.select(events.id, events.name, events.happened_at)
        .order_by(events.id.asc())
        .build()
    )
    print("\nSELECT:", select.sql)

    cursor = conn.execute(select.sql, select.params)
    names = [description[0] for description in cursor.description]
    rows = cursor.fetchall()

    # Колонки -> модель. Валидация, дефолты и ошибки — целиком pydantic.
    adapter = TypeAdapter(Event)
    hydrated_events = [adapter.validate_python(dict(zip(names, row))) for row in rows]
    for event in hydrated_events:
        print("  ", event, "|", type(event.happened_at).__name__)

    # Если строка не подходит под модель — обычная pydantic-ошибка, а не молчаливый None.
    try:
        adapter.validate_python({"id": 1, "name": "x", "happened_at": "not-a-date"})
    except Exception as exc:  # noqa: BLE001
        print("\nвалидация:", type(exc).__name__, "—", str(exc).splitlines()[0])


if __name__ == "__main__":
    main()
