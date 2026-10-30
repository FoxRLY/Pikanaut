"""Схема: какие поля становятся колонками и что запрещено на этапе импорта."""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

import pytest

from pikanaut import SchemaError, StrColumn, TableModel
from pikanaut.schema import table_of
from tests.generated import notes
from tests.models import Note, User


def test_fields_become_columns_in_model_order() -> None:
    info = table_of(User)
    assert [f.name for f in info.fields] == [
        "id",
        "email",
        "full_name",
        "password_hash",
        "age",
        "created_at",
    ]
    assert [f.column for f in info.fields] == [
        "id",
        "user_email",
        "full_name",
        "password_hash",
        "age",
        "created_at",
    ]


def test_table_name_and_schema() -> None:
    info = table_of(User)
    assert info.name == "users"
    assert info.schema is None


def test_every_ordinary_field_is_a_column() -> None:
    assert "password_hash" in [f.name for f in table_of(User).fields]


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

        class Dupe(TableModel, table="t"):
            a: str = StrColumn(name="same")
            b: str = StrColumn(name="same")


def test_generic_model_rejected() -> None:
    T = TypeVar("T")

    with pytest.raises(SchemaError, match="TypeVar"):

        class Box(TableModel, Generic[T], table="t"):
            value: T


def test_table_without_fields_rejected() -> None:
    with pytest.raises(SchemaError, match="at least one column"):

        class Empty(TableModel, table="t"):
            pass


def test_unknown_annotated_metadata_rejected() -> None:
    with pytest.raises(SchemaError):

        class Odd(TableModel, table="t"):
            x: Annotated[int, object()]


def test_generated_table_matches_schema() -> None:
    assert notes.id.name == "id"
    assert notes.text.name == "text"
    assert notes.id.nullable is False

# Consolidated typed-table coverage.
import json
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import ClassVar, Generic, Literal, TypeVar
from uuid import UUID

import pytest
from pydantic import PrivateAttr, ValidationError, field_validator, model_validator
from pydantic_core import PydanticSerializationError

from pikanaut.defaults import GENERATED, IDENTITY, NOW, Generated
from pikanaut.fields import (
    DateTimeColumn,
    IntColumn,
    JsonColumn,
    StrColumn,
    TimeColumn,
    UuidColumn,
)
from pikanaut.model import TableModel
from pikanaut.schema import (
    UNSET,
    is_concrete_table,
    serialize_field,
    table_of,
    validate_field,
)
from pikanaut.errors import SchemaError


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


class AuditFields(TableModel):
    note: str = "created"


class ModelUser(AuditFields, table="users", schema="public"):
    id: int | Generated = IntColumn(pk=True, server_default=IDENTITY)
    display_name: str = StrColumn(name="display", min_length=2, max_length=30)
    role: Role = Role.MEMBER
    state: Literal["active", "disabled"] = "active"
    lucky: int | None = None
    class_setting: ClassVar[str] = "not a column"
    _cache: dict[str, str] = PrivateAttr(default_factory=dict)


def test_table_model_metadata_and_normalized_fields() -> None:
    info = table_of(ModelUser)

    assert (info.model, info.name, info.schema) == (ModelUser, "users", "public")
    assert [field.name for field in info.fields] == [
        "note",
        "id",
        "display_name",
        "role",
        "state",
        "lucky",
    ]
    assert info.columns == ("note", "id", "display", "role", "state", "lucky")
    assert info.field("id").annotation is int
    assert info.field("id").server_default == IDENTITY
    assert info.field("id").default is UNSET
    assert info.field("display_name").constraints.min_length == 2
    assert info.field("display_name").constraints.max_length == 30
    assert info.field("role").allowed_values == ("admin", "member")
    assert info.field("state").allowed_values == ("active", "disabled")
    assert info.field("lucky").nullable is True
    assert info.pypika_table() is info.pypika_table()


def test_only_class_own_table_metadata_makes_a_concrete_table() -> None:
    class Reusable(ModelUser):
        extra: str

    class Concrete(Reusable, table="concrete"):
        value: int

    assert is_concrete_table(ModelUser)
    assert not is_concrete_table(Reusable)
    assert is_concrete_table(Concrete)
    with pytest.raises(SchemaError, match="not a concrete table"):
        table_of(Reusable)
    assert table_of(Concrete).schema is None


def test_table_model_defaults_and_assignment_use_normal_pydantic_coercion() -> None:
    user = ModelUser(display_name="Alice")

    assert user.id is GENERATED
    assert user.lucky is None
    user.lucky = "4"  # type: ignore[assignment]
    assert user.lucky == 4
    with pytest.raises(ValidationError):
        user.display_name = "x"


def test_default_factory_is_not_called_during_schema_extraction() -> None:
    calls = 0

    def factory() -> int:
        nonlocal calls
        calls += 1
        return 7

    class FactoryTable(TableModel, table="factory_table"):
        value: int = IntColumn(default_factory=factory)

    field = table_of(FactoryTable).field("value")
    assert calls == 0
    assert field.default is UNSET
    assert field.default_factory is factory
    assert FactoryTable().value == 7
    assert calls == 1


def test_generated_serialization_fails_unless_field_is_excluded() -> None:
    user = ModelUser(display_name="Alice")

    with pytest.raises(PydanticSerializationError, match="id.*GENERATED"):
        user.model_dump()
    with pytest.raises(PydanticSerializationError, match="id.*GENERATED"):
        user.model_dump_json()
    assert user.model_dump(exclude={"id"})["display_name"] == "Alice"
    assert "id" not in json.loads(user.model_dump_json(exclude={"id"}))


def test_generated_annotation_and_default_declarations_are_checked() -> None:
    with pytest.raises(SchemaError, match="must include Generated"):

        class MissingMarker(TableModel, table="missing_marker"):
            id: int = IntColumn(server_default=IDENTITY)

    with pytest.raises(SchemaError, match="Generated.*only valid"):

        class StrayMarker(TableModel, table="stray_marker"):
            value: int | Generated

    with pytest.raises(SchemaError, match="primary key.*nullable"):

        class NullablePk(TableModel, table="nullable_pk"):
            id: int | None = IntColumn(pk=True)

    with pytest.raises(SchemaError, match="integer column"):

        class BadIdentity(TableModel, table="bad_identity"):
            id: UUID | Generated = UuidColumn(pk=True, server_default=IDENTITY)


def test_column_kind_and_constraints_are_checked_at_class_definition() -> None:
    with pytest.raises(SchemaError, match="IntColumn.*str"):

        class WrongKind(TableModel, table="wrong_kind"):
            value: str = IntColumn()

    with pytest.raises(SchemaError, match="contradictory"):

        class BadBounds(TableModel, table="bad_bounds"):
            value: int = IntColumn(greater_than=5, less_than_or_equal=5)

    with pytest.raises(SchemaError, match="duplicate column"):

        class Duplicate(TableModel, table="duplicate"):
            left: int = IntColumn(name="same")
            right: int = IntColumn(name="same")

    with pytest.raises(SchemaError, match="empty"):

        class EmptyName(TableModel, table=""):
            value: int


def test_unresolved_generic_and_unsupported_unions_are_rejected() -> None:
    T = TypeVar("T")

    with pytest.raises(SchemaError, match="TypeVar"):

        class GenericTable(TableModel, Generic[T], table="generic_table"):
            value: T

    with pytest.raises(SchemaError, match="unsupported union"):

        class UnionTable(TableModel, table="union_table"):
            value: int | str


def test_literal_and_enum_values_must_be_homogeneous_strings_or_integers() -> None:
    with pytest.raises(SchemaError, match="homogeneous string or integer"):

        class MixedLiteral(TableModel, table="mixed_literal"):
            value: Literal["one", 2]

    class BadEnum(Enum):
        TRUE = True
        FALSE = False

    with pytest.raises(SchemaError, match="homogeneous string or integer"):

        class BooleanEnum(TableModel, table="boolean_enum"):
            value: BadEnum


def test_datetime_and_time_policies_apply_to_declared_and_inferred_columns() -> None:
    class Event(TableModel, table="events"):
        aware: datetime
        explicit_aware: datetime = DateTimeColumn()
        local: datetime = DateTimeColumn(timezone=False)
        clock: time = TimeColumn()

    offset = timezone(timedelta(hours=3))
    event = Event(
        aware=datetime(2026, 1, 2, 12, tzinfo=offset),
        explicit_aware=datetime(2026, 1, 2, 9, tzinfo=timezone.utc),
        local=datetime(2026, 1, 2, 9),
        clock=time(9, 30),
    )
    assert event.aware == datetime(2026, 1, 2, 9, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="timezone-aware"):
        Event(
            aware=datetime(2026, 1, 2, 12),
            explicit_aware=datetime(2026, 1, 2, 9, tzinfo=timezone.utc),
            local=datetime(2026, 1, 2, 9),
            clock=time(9, 30),
        )
    with pytest.raises(ValidationError, match="naive"):
        Event(
            aware=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
            explicit_aware=datetime(2026, 1, 2, 9, tzinfo=timezone.utc),
            local=datetime(2026, 1, 2, 9, tzinfo=timezone.utc),
            clock=time(9, 30),
        )
    with pytest.raises(ValidationError, match="time without tzinfo"):
        Event(
            aware=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
            explicit_aware=datetime(2026, 1, 2, 9, tzinfo=timezone.utc),
            local=datetime(2026, 1, 2, 9),
            clock=time(9, 30, tzinfo=timezone.utc),
        )


def test_json_column_parses_text_and_serializes_with_pydantic_json_mode() -> None:
    class Payload(TableModel):
        uid: UUID
        at: datetime

    class Document(TableModel, table="documents"):
        payload: Payload = JsonColumn()
        optional: dict[str, int] | None = JsonColumn(default=None)

    document = Document(  # pyright: ignore[reportArgumentType]
            payload='{"uid":"12345678-1234-5678-1234-567812345678",'  # pyright: ignore[reportArgumentType]
            '"at":"2026-01-02T09:00:00Z"}'
        )
    assert isinstance(document.payload, Payload)
    field = table_of(Document).field("payload")
    assert serialize_field(field, document.payload) == {
        "uid": "12345678-1234-5678-1234-567812345678",
        "at": "2026-01-02T09:00:00Z",
    }
    assert serialize_field(table_of(Document).field("optional"), None) is None

    with pytest.raises(ValidationError, match="top-level JSON null"):
        Document(payload="null")  # pyright: ignore[reportArgumentType]


def test_validate_field_runs_field_constraints_and_autonomous_validators_only() -> None:
    class Validated(TableModel, table="validated"):
        code: str = StrColumn(min_length=2)
        model_validator_calls: ClassVar[int] = 0

        @field_validator("code")
        @classmethod
        def uppercase(cls, value: str) -> str:
            if not value.isupper():
                raise ValueError("must be uppercase")
            return value

        @model_validator(mode="after")
        def observe_model(self) -> Validated:
            type(self).model_validator_calls += 1
            return self

    assert validate_field(Validated, "code", "OK") == "OK"
    assert Validated.model_validator_calls == 0
    with pytest.raises(ValidationError, match="at least 2 characters"):
        validate_field(Validated, "code", "X")
    with pytest.raises(ValidationError, match="must be uppercase"):
        validate_field(Validated, "code", "no")
    assert Validated.model_validator_calls == 0


def test_default_options_are_mutually_exclusive() -> None:
    with pytest.raises(SchemaError, match="mutually exclusive"):
        IntColumn(default=1, default_factory=lambda: 2)
    with pytest.raises(SchemaError, match="server_default"):
        IntColumn(default=NOW)
