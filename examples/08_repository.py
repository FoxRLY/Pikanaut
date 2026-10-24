"""08 — сложное: слой-репозиторий поверх клиента.

Запуск: uv run python examples/08_repository.py

Три тонкости, которые видно только на таком слое:

1. Репозиторий сохраняет типы модели и диалекта через `Repository[M, D]`.
   Общий слой использует базовые возможности `Client[D]`.

2. В общем слое нельзя пользоваться dialect-only возможностями (`.returning()`):
   они объявлены только у конкретных классов. Наследник, знающий диалект
   (`Client[SQLite]`), возвращает их обратно — статически.

3. Вставка пачками режется по chunk, чтобы не упереться в лимит параметров.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel

from pikanaut import Client, Col, Sql, client, columns, ddl, table
from pikanaut.dialects import SQLITE, Dialect, Limits, SQLite

M = TypeVar("M", bound=BaseModel)
D = TypeVar("D", bound=Dialect)


@table("notes")
class Note(BaseModel):
    id: Annotated[int | None, Col(pk=True)] = None
    text: str


class Repository(Generic[M, D]):
    """Слой, не привязанный к диалекту: работает с любым клиентом."""

    def __init__(self, db: Client[D], model: type[M]) -> None:
        self.db = db
        self.model = model
        self.columns = columns(model)

    def by_id(self, value: int) -> Sql:
        return self.db.select(self.model).where(self.columns.id == value).build()

    def all(self, limit: int = 100) -> Sql:
        return (
            self.db.select(self.model)
            .order_by(self.columns.id.asc())
            .limit(limit)
            .build()
        )

    def add(self, row: M) -> Sql:
        return self.db.insert(row).build()

    def add_many(self, rows: Sequence[M], chunk: int = 500) -> list[Sql]:
        """Режем пачку по chunk строк: бюджет параметров не превысится."""
        return [
            self.db.insert_many(list(rows[i : i + chunk])).build()
            for i in range(0, len(rows), chunk)
        ]


class SQLiteNoteRepository(Repository[Note, SQLite]):
    """Конкретный диалект — значит RETURNING доступен и проверяется линтером."""

    def __init__(self, db: Client[SQLite]) -> None:
        super().__init__(db, Note)
        self.sqlite_db = db  # типизированная ссылка, чтобы RETURNING был виден

    def add(self, row: Note) -> Sql:
        return self.sqlite_db.insert(row).returning(self.columns.id).build()


def main() -> None:
    db = client(SQLITE, limits=Limits(max_params=1_000))
    repo = SQLiteNoteRepository(db)
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)

    for row in (Note(text="первая"), Note(text="вторая"), Note(text="третья")):
        statement = repo.add(row)
        print("INSERT ... RETURNING:", statement.sql)
        print("  id =", conn.execute(statement.sql, statement.params).fetchone()[0])

    print("\nby_id(2):", repo.by_id(2).sql)
    print("all(2):  ", repo.all(2).sql)
    print("rows:    ", conn.execute(repo.all(2).sql).fetchall())

    batch = [Note(text=f"строка {i}") for i in range(1_200)]
    statements = repo.add_many(batch, chunk=400)
    print(
        f"\nпачка из {len(batch)} строк -> {len(statements)} запроса по 400 параметров"
    )
    for statement in statements:
        conn.execute(statement.sql, statement.params)
    print("всего в таблице:", conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0])


if __name__ == "__main__":
    main()
