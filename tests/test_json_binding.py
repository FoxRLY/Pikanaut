"""JSON binding must use Pydantic serialization and SQL NULL for top-level None."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel
from typing_extensions import Self, Unpack

from pikanaut import JsonColumn, StrColumn, TableModel, client, ddl
from pikanaut.client import Update
from pikanaut.dialects import SQLITE
from pikanaut.dialects.base import Dialect, Limits
from pikanaut.expr import Column
from pikanaut.fields import IntColumn
from pikanaut.schema import table_of
from pikanaut.tables import Table


class Detail(BaseModel):
    label: str
    amount: Decimal
    at: datetime


class Document(TableModel, table="documents"):
    id: int = IntColumn(pk=True)
    payload: Detail | None = JsonColumn(default=None)
    note: str = StrColumn(min_length=1)


class DocumentsSource: ...


class DocumentsUpdateValues(TypedDict, total=False):
    id: int | Column[int, DocumentsSource]
    payload: Detail | None | Column[Detail | None, DocumentsSource]
    note: str | Column[str, DocumentsSource]


class DocumentsUpdate(Update[DocumentsSource]):
    def set(self, **values: Unpack[DocumentsUpdateValues]) -> Self:
        return self._set_values(values)


class DocumentsTable(Table[Document, DocumentsSource]):
    id: Column[int, DocumentsSource]
    payload: Column[Detail | None, DocumentsSource]
    note: Column[str, DocumentsSource]

    def __init__(self) -> None:
        super().__init__(Document)
        self.id = self.__pikanaut_column__("id")
        self.payload = self.__pikanaut_column__("payload")
        self.note = self.__pikanaut_column__("note")

    def __pikanaut_update__(
        self, dialect: Dialect, limits: Limits, require_where: bool = True
    ) -> DocumentsUpdate:
        return DocumentsUpdate(
            dialect, limits, self.__pikanaut_info__, require_where=require_where
        )


documents = DocumentsTable()


def test_insert_top_level_json_none_is_sql_null() -> None:
    statement = (
        client(SQLITE)
        .insert(documents, Document(id=1, payload=None, note="x"))
        .build()
    )
    assert statement.params == [1, None, "x"]

    connection = sqlite3.connect(":memory:")
    for item in ddl.create(Document, dialect=SQLITE):
        connection.execute(item.sql)
    connection.execute(statement.sql, statement.params)
    row = connection.execute(
        'SELECT "payload", typeof("payload") FROM "documents"'
    ).fetchone()
    assert row == (None, "null")


def test_insert_nested_pydantic_json_uses_json_mode_serialization() -> None:
    detail = Detail(
        label="one",
        amount=Decimal("2.50"),
        at=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
    )
    statement = (
        client(SQLITE).insert(documents, Document(id=1, payload=detail, note="x")).build()
    )
    assert statement.params[1] == (
        '{"label":"one","amount":"2.50","at":"2026-01-02T09:00:00Z"}'
    )


def test_update_json_literal_serializes_and_keeps_top_level_none_null() -> None:
    cleared = (
        client(SQLITE)
        .update(documents)
        .set(payload=None)
        .where(documents.id == 1)
        .build()
    )
    assert cleared.params == [None, 1]

    nested = (
        client(SQLITE)
        .update(documents)
        .set(payload=Detail(label="x", amount=Decimal("1"), at=datetime.now(timezone.utc)))
        .where(documents.id == 1)
        .build()
    )
    assert isinstance(nested.params[0], str)
    assert '"label":"x"' in nested.params[0]


def test_schema_keeps_none_in_json_field_annotation() -> None:
    field = table_of(Document).field("payload")
    assert field.nullable is True
