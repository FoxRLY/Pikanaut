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


def main() -> None:
    conn = get_connection()

    inserted_note = insert_note("Hello", conn)
    selected_note = select_first_note(conn)

    print("Вставленный объект: ", inserted_note)
    print("Прочитанный объект: ", selected_note)


@table("notes")
class Note(BaseModel):
    id: Annotated[int | None, Col(pk=True)] = None
    text: str


NoteTable = columns(Note)

sqlgen = client(SQLITE)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)

    return conn


def insert_note(text: str, conn: sqlite3.Connection) -> Note:
    new_note = Note(text=text)

    query = sqlgen.insert(new_note).returning(NoteTable.id).build()

    print(query)

    for row in conn.execute(query.sql, query.params):
        new_note.id = row["id"]
        break

    if new_note.id is None:
        raise Exception("huh")

    return new_note


def select_first_note(conn: sqlite3.Connection) -> Note:
    query = sqlgen.select(NoteTable.id, NoteTable.text).limit(5).build()

    print(query)

    row = conn.execute(query.sql, query.params).fetchone()
    if row:
        return Note(id=row["id"], text=row["text"])
    else:
        raise Exception("Huh")


if __name__ == "__main__":
    main()
