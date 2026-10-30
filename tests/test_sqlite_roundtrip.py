"""Round-trip на настоящем sqlite3: сгенерированный SQL реально исполняется."""

from __future__ import annotations

import sqlite3

import pytest

from pikanaut import client, ddl
from pikanaut.dialects import SQLITE
from tests.generated import notes
from tests.models import Note


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    for statement in ddl.create(Note, dialect=SQLITE):
        connection.execute(statement.sql)
    yield connection
    connection.close()


def test_insert_select_update_delete(conn) -> None:
    db = client(SQLITE)
    ins = db.insert(notes, Note(text="привет")).build()
    cursor = conn.execute(ins.sql, ins.params)
    new_id = cursor.lastrowid

    sel = db.select(notes.id, notes.text).build()
    assert conn.execute(sel.sql, sel.params).fetchall() == [(new_id, "привет")]

    upd = db.update(notes).set(text="пока").where(notes.id == new_id).build()
    conn.execute(upd.sql, upd.params)

    sel_one = db.select(notes.text).where(notes.id == new_id).build()
    assert conn.execute(sel_one.sql, sel_one.params).fetchall() == [("пока",)]

    dele = db.delete(notes).where(notes.id == new_id).build()
    conn.execute(dele.sql, dele.params)
    assert conn.execute(sel.sql, sel.params).fetchall() == []


def test_injection_attempt_is_stored_verbatim(conn) -> None:
    db = client(SQLITE)
    evil = "'; DROP TABLE notes--"

    ins = db.insert(notes, Note(text=evil)).build()
    conn.execute(ins.sql, ins.params)

    assert "notes" in {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert conn.execute("SELECT text FROM notes").fetchone() == (evil,)


def test_returning_on_modern_sqlite(conn) -> None:
    db = client(SQLITE)
    ins = db.insert(notes, Note(text="x")).returning(notes.id).build()
    row = conn.execute(ins.sql, ins.params).fetchone()
    assert row is not None and isinstance(row[0], int)
