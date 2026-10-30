"""01 — самый маленький пример: модель → SQL.

Запуск: uv run python examples/01_insert_select.py

Главная мысль: pikanaut не ходит в базу. На выходе всегда (sql, params), а исполнение —
дело драйвера. Здесь драйвер — stdlib sqlite3.
"""

from __future__ import annotations

import sqlite3
# import sys
# from pathlib import Path

# sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from .generated.models import Note
from .generated.tables import notes
from pikanaut import GENERATED, client, ddl
from pikanaut.dialects import SQLITE


def main() -> None:
    conn = get_connection()

    inserted_note = insert_note("Hello", conn)
    selected_note = select_first_note(conn)

    print("Вставленный объект: ", inserted_note)
    print("Прочитанный объект: ", selected_note)


sqlgen = client(SQLITE)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)

    return conn


def insert_note(text: str, conn: sqlite3.Connection) -> Note:
    new_note = Note(text=text)

    query = sqlgen.insert(notes, new_note).returning(notes.id).build()

    print(query)

    for row in conn.execute(query.sql, query.params):
        new_note.id = row["id"]
        break

    if new_note.id is GENERATED:
        raise Exception("huh")

    return new_note


def select_first_note(conn: sqlite3.Connection) -> Note:
    query = sqlgen.select(notes.id, notes.text).limit(5).build()

    print(query)

    row = conn.execute(query.sql, query.params).fetchone()
    if row:
        return Note.model_validate(dict(row))
    else:
        raise Exception("Huh")


if __name__ == "__main__":
    main()
