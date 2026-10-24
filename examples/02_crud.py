"""02 — CRUD: SELECT, INSERT, UPDATE, DELETE.

Запуск: uv run python examples/02_crud.py

Что показывает:
  * INSERT строится из model_fields_set — в запрос попадают только заданные поля;
  * UPDATE и DELETE без WHERE запрещены: QueryError вместо «удали всё»;
  * для всех строк есть отдельные методы delete_all() / update_all().
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, QueryError, client, columns, ddl, table
from pikanaut.dialects import SQLITE


@table("notes")
class Note(BaseModel):
    id: Annotated[int | None, Col(pk=True)] = None
    text: str


def main() -> None:
    db = client(SQLITE)
    N = columns(Note)
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)

    # --- INSERT: id не задан, значит колонки id в запросе нет
    insert = db.insert(Note(text="купить хлеб")).build()
    print("INSERT:", insert.sql, insert.params)
    note_id = conn.execute(insert.sql, insert.params).lastrowid

    # --- SELECT с параметрами
    select = db.select(N.id, N.text).where(N.id == note_id).build()
    print("SELECT:", select.sql, select.params)
    print("  ->", conn.execute(select.sql, select.params).fetchall())

    # --- UPDATE: set() принимает имена полей модели, а не колонок
    update = (
        db.update(Note).set(text="купить хлеб и молоко").where(N.id == note_id).build()
    )
    print("UPDATE:", update.sql, update.params)
    conn.execute(update.sql, update.params)

    # --- DELETE
    delete = db.delete(Note).where(N.id == note_id).build()
    print("DELETE:", delete.sql, delete.params)
    conn.execute(delete.sql, delete.params)

    # --- защита от случайного «всех строк»
    try:
        db.delete(Note).build()
    except QueryError as exc:
        print("\nDELETE без WHERE:", exc)

    # --- явный вариант для всех строк
    print("DELETE ALL:", db.delete_all(Note).build().sql)


if __name__ == "__main__":
    main()
