"""Статические ожидания: проверяется mypy/pyright, не pytest.

Объём типизации (решение A): диалект связывается с классами запросов, поэтому
несовместимый с диалектом вызов ловится линтером. Форма строки намеренно остаётся
``Any`` — статически вывести её из pydantic-модели без плагина или кодогенерации нельзя.

Неиспользованный ``# type: ignore[...]`` означает, что ожидаемая ошибка не сработала.
"""

from __future__ import annotations

from typing_extensions import assert_type

from pikanaut import Client, client
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34, Postgres, SQLite, SQLite34
from tests.generated import notes, users
from tests.models import Note

db = client(SQLITE)
pg = client(POSTGRES)
old = client(SQLITE_34)
row = Note(text="x")

# диалект выводится из клиента
assert_type(db, Client[SQLite])
assert_type(pg, Client[Postgres])
assert_type(old, Client[SQLite34])

# generated tables preserve model/source/value compatibility
db.select(users.id).where(users.age > 18)
db.insert(notes, row).returning(notes.id)
pg.update(users).set(age=users.id)
db.update(users).set(age="wrong")  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
db.update(users).set(missing=1)  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
db.insert(users, row)  # type: ignore[misc]  # pyright: ignore[reportArgumentType]


# смешивать клиенты разных диалектов нельзя
def _takes_sqlite(c: Client[SQLite]) -> None: ...


_takes_sqlite(pg)  # type: ignore[arg-type]
