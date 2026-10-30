"""02 — CRUD: SELECT, INSERT, UPDATE, DELETE.

Запуск: uv run python examples/02_crud.py

Что показывает:
  * GENERATED-поля пропускаются, остальные значения модели связываются параметрами;
  * UPDATE и DELETE без WHERE запрещены: QueryError вместо «удали всё»;
  * для всех строк есть отдельные методы delete_all() / update_all().
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.generated.models import Note
from examples.generated.tables import notes
from pikanaut import QueryError, client, ddl
from pikanaut.dialects import SQLITE


def main() -> None:
    db = client(SQLITE)
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)

    # --- INSERT: id не задан, значит колонки id в запросе нет
    insert = db.insert(notes, Note(text="купить хлеб")).build()
    print("INSERT:", insert.sql, insert.params)
    note_id = conn.execute(insert.sql, insert.params).lastrowid

    # --- SELECT с параметрами
    select = db.select(notes.id, notes.text).where(notes.id == note_id).build()
    print("SELECT:", select.sql, select.params)
    print("  ->", conn.execute(select.sql, select.params).fetchall())

    # --- UPDATE: set() принимает имена полей модели, а не колонок
    update = (
        db.update(notes)
        .set(text="купить хлеб и молоко")
        .where(notes.id == note_id)
        .build()
    )
    print("UPDATE:", update.sql, update.params)
    conn.execute(update.sql, update.params)

    # --- DELETE
    delete = db.delete(notes).where(notes.id == note_id).build()
    print("DELETE:", delete.sql, delete.params)
    conn.execute(delete.sql, delete.params)

    # --- защита от случайного «всех строк»
    try:
        db.delete(notes).build()
    except QueryError as exc:
        print("\nDELETE без WHERE:", exc)

    # --- явный вариант для всех строк
    print("DELETE ALL:", db.delete_all(notes).build().sql)


if __name__ == "__main__":
    main()
