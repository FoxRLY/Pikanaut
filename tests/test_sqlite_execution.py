"""Исполнение сгенерированного SQL на настоящем sqlite3.

Golden-тесты проверяют текст; здесь проверяется, что этот текст движок принимает
и что он делает то, что задумано. Все запросы генерируются pikanaut, руками не пишется
ни один SQL, кроме DDL (DDL в v1 не поддерживается).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pikanaut import client, ddl
from pikanaut.dialects import SQLITE
from tests.generated import events, notes, users
from tests.models import Event, Note, User


@pytest.fixture
def conn():
    """Схема создаётся тем же DDL-генератором, что и в примерах: без ручного SQL."""
    connection = sqlite3.connect(":memory:")
    for model in (Note, User, Event):
        for statement in ddl.create(model, dialect=SQLITE):
            connection.execute(statement.sql)
    yield connection
    connection.close()


def _user(**overrides: int | str | datetime | None) -> User:
    values = dict(
        id=1,
        email="a@b.io",
        full_name="Ann Lee",
        password_hash="secret",
        age=None,
        created_at=datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return User.model_validate(values)


def test_every_statement_is_accepted_by_sqlite(conn) -> None:
    db = client(SQLITE)
    statements = [
        db.insert(notes, Note(text="привет")).build(),
        db.insert(notes, Note(text="второй")).returning(notes.id).build(),
        db.insert(users, _user()).build(),
        db.insert(
            events,
            Event(
                id=1,
                is_active=True,
                at=datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
                amount=Decimal("10.50"),
                uid=__import__("uuid").UUID("12345678-1234-5678-1234-567812345678"),
            ),
        ).build(),
        db.select(users.id, users.email)
        .where(users.age > 18)
        .order_by(users.id.desc())
        .limit(10)
        .build(),
        db.select(users.id).where(users.age.in_([1, 2, 3])).build(),
        db.select(users.id).where(users.age == None).build(),  # noqa: E711
        db.select(users.id).offset(20).build(),
        db.select(users.age).group_by(users.age).having(users.age > 18).build(),
        db.update(users).set(age=30).where(users.id == 1).build(),
        db.delete(notes).where(notes.id == 999).build(),
        db.delete_all(notes).build(),
    ]

    for statement in statements:
        conn.execute(statement.sql, statement.params).fetchall()


def test_is_null_returns_the_null_row(conn) -> None:
    db = client(SQLITE)

    # email помечен unique — схема теперь это правда проверяет,
    # поэтому у двух строк разные адреса
    for user in (
        _user(id=1, email="one@b.io", age=None),
        _user(id=2, email="two@b.io", age=30),
    ):
        statement = db.insert(users, user).build()
        conn.execute(statement.sql, statement.params)

    null_statement = db.select(users.id).where(users.age == None).build()  # noqa: E711
    assert conn.execute(null_statement.sql, null_statement.params).fetchall() == [(1,)]

    adult_statement = db.select(users.id).where(users.age > 18).build()
    assert conn.execute(adult_statement.sql, adult_statement.params).fetchall() == [
        (2,)
    ]


def test_returning_gives_back_the_generated_id(conn) -> None:
    db = client(SQLITE)
    statement = db.insert(notes, Note(text="x")).returning(notes.id).build()
    row = conn.execute(statement.sql, statement.params).fetchone()
    assert row is not None and isinstance(row[0], int)


def test_in_list_and_offset_execute(conn) -> None:
    db = client(SQLITE)
    for text in ("a", "b", "c"):
        statement = db.insert(notes, Note(text=text)).build()
        conn.execute(statement.sql, statement.params)

    in_statement = db.select(notes.text).where(notes.id.in_([1, 2, 3])).build()
    assert conn.execute(in_statement.sql, in_statement.params).fetchall() == [
        ("a",),
        ("b",),
        ("c",),
    ]

    offset_statement = db.select(notes.text).order_by(notes.id.asc()).offset(1).build()
    assert conn.execute(offset_statement.sql, offset_statement.params).fetchall() == [
        ("b",),
        ("c",),
    ]
