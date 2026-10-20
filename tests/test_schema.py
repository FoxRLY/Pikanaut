"""Схема: какие поля становятся колонками и что запрещено на этапе импорта."""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

import pytest
from pydantic import BaseModel

from pikanaut import Col, SchemaError, Skip, table
from pikanaut.schema import table_of
from tests.models import Note, User


def test_fields_become_columns_in_model_order() -> None:
    info = table_of(User)
    assert [f.name for f in info.fields] == ["id", "email", "full_name", "age", "created_at"]
    assert [f.column for f in info.fields] == ["id", "user_email", "full_name", "age", "created_at"]


def test_table_name_and_schema() -> None:
    info = table_of(User)
    assert info.name == "users"
    assert info.schema is None


def test_skip_is_not_a_column() -> None:
    assert "password_hash" not in [f.name for f in table_of(User).fields]


def test_computed_and_private_fields_are_not_columns() -> None:
    names = [f.name for f in table_of(User).fields]
    assert "display_name" not in names
    assert "_cache" not in names


def test_pk_and_unique_flags() -> None:
    fields = {f.name: f for f in table_of(User).fields}
    assert fields["id"].pk is True
    assert fields["email"].unique is True
    assert fields["full_name"].pk is False


def test_nullable_follows_optional() -> None:
    fields = {f.name: f for f in table_of(User).fields}
    assert fields["age"].nullable is True
    assert fields["email"].nullable is False
    assert fields["age"].required is False


def test_duplicate_column_names_rejected() -> None:
    with pytest.raises(SchemaError, match="duplicate column"):

        @table("t")
        class Dupe(BaseModel):
            a: Annotated[str, Col("same")]
            b: Annotated[str, Col("same")]


def test_generic_model_rejected() -> None:
    T = TypeVar("T")

    with pytest.raises(SchemaError, match="TypeVar"):

        @table("t")
        class Box(BaseModel, Generic[T]):
            value: T


def test_all_fields_skipped_rejected() -> None:
    with pytest.raises(SchemaError, match="no columns"):

        @table("t")
        class Empty(BaseModel):
            secret: Annotated[str, Skip]


def test_unknown_annotated_metadata_rejected() -> None:
    with pytest.raises(SchemaError):

        @table("t")
        class Odd(BaseModel):
            x: Annotated[int, object()]


def test_columns_namespace_matches_schema() -> None:
    from pikanaut import columns

    N = columns(Note)
    assert N.id.name == "id"
    assert N.text.name == "text"
    assert N.id.nullable is True
