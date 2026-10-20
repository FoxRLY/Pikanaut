"""01 — самый маленький пример: модель → SQL.

Запуск: uv run python examples/01_hello.py

Главная мысль: pikanaut не ходит в базу. На выходе всегда (sql, params), а исполнение —
дело драйвера. Здесь драйвер — stdlib sqlite3.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, client, columns, ddl, table
from pikanaut.dialects import SQLITE


@table("notes")
class Note(BaseModel):
    id: Annotated[int | None, Col(pk=True)] = None
    text: str


def main() -> None:
    db = client(SQLITE)          # Client[SQLite]
    N = columns(Note)            # Columns[Note]

    query = db.select(N.id, N.text).where(N.id > 1).limit(5)
    built = query.build()

    print("SQL:   ", built.sql)
    print("params:", built.params)
    print()

    # Исполняем тем, что есть под рукой.
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)
    conn.execute("INSERT INTO notes (text) VALUES (?), (?)", ("первая", "вторая"))

    rows = conn.execute(built.sql, built.params).fetchall()
    print("rows:  ", rows)


if __name__ == "__main__":
    main()
