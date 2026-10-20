"""Статические ожидания: проверяется mypy/pyright, не pytest.

Объём типизации (решение A): диалект связывается с классами запросов, поэтому
несовместимый с диалектом вызов ловится линтером. Форма строки намеренно остаётся
``Any`` — статически вывести её из pydantic-модели без плагина или кодогенерации нельзя.

Неиспользованный ``# type: ignore[...]`` означает, что ожидаемая ошибка не сработала.
"""

from __future__ import annotations

from typing import Any, assert_type

from pikanaut import Client, client, columns
from pikanaut.client import (
    PostgresInsert,
    PostgresSelect,
    SQLite34Select,
    SQLiteInsert,
    SQLiteSelect,
)
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34, Postgres, SQLite, SQLite34
from tests.models import Note, User

db = client(SQLITE)
pg = client(POSTGRES)
old = client(SQLITE_34)
U = columns(User)
N = columns(Note)
row = Note(text="x")

# диалект выводится из клиента
assert_type(db, Client[SQLite])
assert_type(pg, Client[Postgres])
assert_type(old, Client[SQLite34])

# клиент возвращает классы запросов своего диалекта
assert_type(db.select(U.id), SQLiteSelect[Any])
assert_type(old.select(U.id), SQLite34Select[Any])
assert_type(pg.select(U.id), PostgresSelect[Any])
assert_type(db.insert(row), SQLiteInsert)
assert_type(pg.insert(row), PostgresInsert)

# returning есть там, где диалект его умеет, и отсутствует там, где нет
db.insert(row).returning(N.id)
pg.update(User).returning(U.id)
old.insert(row).returning(N.id)  # type: ignore[attr-defined]


# смешивать клиенты разных диалектов нельзя
def _takes_sqlite(c: Client[SQLite]) -> None: ...


_takes_sqlite(pg)  # type: ignore[arg-type]
