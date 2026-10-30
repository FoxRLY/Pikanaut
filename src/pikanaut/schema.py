"""Normalized table metadata extracted from :class:`TableModel` classes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from functools import cache
from types import UnionType
from typing import (
    Any,
    Literal,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
)
from uuid import UUID

import annotated_types
from pydantic import BaseModel, TypeAdapter
from pydantic.fields import FieldInfo
from pydantic_core import PydanticSerializationError, SchemaValidator, core_schema
from pydantic_core.core_schema import CoreSchema
from pydantic_core import PydanticUndefined
from pypika import Table

from .defaults import (
    GENERATED,
    NOW,
    TODAY,
    Generated,
    Identity,
    ServerDefault,
    is_server_descriptor,
)
from .errors import SchemaError
from .fields import ColumnConstraints, ColumnSpec
from .model import TableModel

M = TypeVar("M", bound=BaseModel)


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class Field:
    """One normalized stored column.

    ``annotation`` removes :class:`Generated` but deliberately retains ``None``.
    Query builders can therefore distinguish SQL nullability while never treating
    the pending-server-value marker as a bindable column value type.
    """

    name: str
    column: str
    annotation: object
    required: bool
    nullable: bool
    pk: bool
    unique: bool
    index: bool = False
    default: object = UNSET
    server_default: object = UNSET
    default_factory: Callable[..., object] | None = None
    sql_type: str | None = None
    kind: str = "unknown"
    constraints: ColumnConstraints = ColumnConstraints()
    allowed_values: tuple[str | int, ...] = ()
    timezone: bool | None = None
    pydantic_field: FieldInfo = dataclass_field(
        repr=False, compare=False, hash=False, default_factory=FieldInfo
    )


@dataclass(frozen=True, slots=True)
class TableInfo:
    model: type[BaseModel]
    name: str
    schema: str | None = None
    fields: tuple[Field, ...] = ()

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(item.column for item in self.fields)

    def field(self, model_field: str) -> Field:
        for item in self.fields:
            if item.name == model_field:
                return item
        raise SchemaError(
            f"{self.model.__name__}: field {model_field!r} is not a column"
        )

    def pypika_table(self) -> Table:
        return _pypika_table(self.name, self.schema)


@cache
def _pypika_table(name: str, schema: str | None) -> Table:
    return Table(name, schema=schema)


def is_concrete_table(model: type[object]) -> bool:
    """Return whether *model* declares its own table metadata.

    Metadata inherited from a concrete parent never registers a second table.
    """

    return (
        issubclass(model, TableModel)
        and model.__dict__.get("__pikanaut_table__") is not None
    )


def _contains_typevar(annotation: object) -> bool:
    if isinstance(annotation, TypeVar):
        return True
    return any(_contains_typevar(argument) for argument in get_args(annotation))


def _union_args(annotation: object) -> tuple[object, ...]:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return get_args(annotation)
    return (annotation,)


def _remove_generated(annotation: object) -> tuple[object, bool, bool]:
    arguments = _union_args(annotation)
    has_generated = Generated in arguments
    kept = tuple(argument for argument in arguments if argument is not Generated)
    nullable = type(None) in kept
    if not kept:
        raise SchemaError("Generated requires a concrete value type")
    if len(kept) == 1:
        normalized = kept[0]
    else:
        normalized = kept[0]
        for argument in kept[1:]:
            normalized = cast(Any, normalized) | cast(Any, argument)
    return normalized, nullable, has_generated


def _base_annotation(annotation: object) -> object:
    arguments = tuple(
        item for item in _union_args(annotation) if item is not type(None)
    )
    if len(arguments) != 1:
        raise SchemaError(
            f"unsupported union {annotation!r}; only None and Generated are special"
        )
    return arguments[0]


def _allowed_values(annotation: object) -> tuple[str | int, ...]:
    origin = get_origin(annotation)
    if origin is Literal:
        values = cast(tuple[object, ...], get_args(annotation))
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        values = tuple(member.value for member in annotation.__members__.values())
    else:
        return ()
    unique = tuple(dict.fromkeys(values))
    if not unique or any(type(value) not in (str, int) for value in unique):
        raise SchemaError(
            "Literal/Enum values must be homogeneous string or integer values"
        )
    value_types: set[type[object]] = {type(value) for value in unique}
    if len(value_types) != 1:
        raise SchemaError(
            "Literal/Enum values must be homogeneous string or integer values"
        )
    return cast(tuple[str | int, ...], unique)


def _infer_kind(
    annotation: object, spec: ColumnSpec | None
) -> tuple[str, tuple[str | int, ...]]:
    concrete = _base_annotation(annotation)
    allowed = _allowed_values(concrete)
    if allowed:
        return ("str" if isinstance(allowed[0], str) else "int"), allowed
    if spec is not None and spec.kind == "json":
        return "json", ()

    origin = get_origin(concrete)
    if origin in (dict, list, tuple):
        return "json", ()
    kinds: tuple[tuple[object, str], ...] = (
        (bool, "bool"),
        (int, "int"),
        (float, "float"),
        (Decimal, "decimal"),
        (str, "str"),
        (bytes, "bytes"),
        (UUID, "uuid"),
        (datetime, "datetime"),
        (date, "date"),
        (time, "time"),
    )
    for python_type, kind in kinds:
        if concrete is python_type:
            return kind, ()
    raise SchemaError(f"unsupported column annotation {annotation!r}")


def _column_spec(
    model: type[BaseModel], name: str, field_info: FieldInfo
) -> ColumnSpec | None:
    specs = [item for item in field_info.metadata if isinstance(item, ColumnSpec)]
    if len(specs) > 1:
        raise SchemaError(f"{model.__name__}.{name}: multiple column declarations")
    return specs[0] if specs else None


_CONSTRAINT_METADATA = (
    annotated_types.Gt,
    annotated_types.Ge,
    annotated_types.Lt,
    annotated_types.Le,
    annotated_types.MinLen,
    annotated_types.MaxLen,
    annotated_types.Interval,
)


def _check_metadata(model: type[BaseModel], name: str, field_info: FieldInfo) -> None:
    """Reject Annotated metadata this library cannot translate to DDL.

    Column factory constraints are already reflected in ``ColumnSpec``; other
    Pydantic constraint objects are allowed for ordinary coercion but unknown
    metadata would make the declared table semantics ambiguous.
    """

    for item in field_info.metadata:
        if isinstance(item, ColumnSpec) or isinstance(item, _CONSTRAINT_METADATA):
            continue
        raise SchemaError(
            f"{model.__name__}.{name}: unsupported annotation metadata {item!r}"
        )


def _check_server_default(
    model: type[BaseModel], field: Field, has_generated: bool
) -> None:
    path = f"{model.__name__}.{field.name}"
    if field.server_default is not UNSET and not has_generated:
        raise SchemaError(f"{path}: server_default annotation must include Generated")
    if field.server_default is UNSET and has_generated:
        raise SchemaError(f"{path}: Generated is only valid with server_default")
    if isinstance(field.server_default, Identity) and field.kind != "int":
        raise SchemaError(f"{path}: Identity requires an integer column")
    if isinstance(field.server_default, ServerDefault):
        if field.server_default in (NOW,) and not (
            field.kind == "datetime" and field.timezone is not False
        ):
            raise SchemaError(f"{path}: NOW requires a timezone-aware datetime column")
        if field.server_default in (TODAY,) and field.kind != "date":
            raise SchemaError(f"{path}: TODAY requires a date column")


@cache
def table_of(model: type[object]) -> TableInfo:
    """Return immutable normalized metadata for one concrete table model."""

    if not issubclass(model, TableModel):
        name = getattr(model, "__name__", repr(model))
        raise SchemaError(f"{name}: only TableModel subclasses can be tables")
    if not is_concrete_table(model):
        raise SchemaError(f"{model.__name__}: not a concrete table; declare table=...")
    declared = model.__dict__["__pikanaut_table__"]
    assert declared is not None
    table_name, schema_name = declared

    fields: list[Field] = []
    seen: dict[str, str] = {}
    for field_name, field_info in model.model_fields.items():
        original = field_info.annotation
        if _contains_typevar(original):
            raise SchemaError(
                f"{model.__name__}.{field_name}: TypeVar is not supported"
            )
        normalized, nullable, has_generated = _remove_generated(original)
        _check_metadata(model, field_name, field_info)
        spec = _column_spec(model, field_name, field_info)
        kind, allowed = _infer_kind(normalized, spec)
        if spec is not None and spec.kind != kind:
            raise SchemaError(
                f"{model.__name__}.{field_name}: {spec.kind.title()}Column does not match {original!r}"
            )
        column = spec.name if spec is not None and spec.name is not None else field_name
        if column in seen:
            raise SchemaError(
                f"{model.__name__}: duplicate column {column!r} "
                f"(fields {seen[column]!r} and {field_name!r})"
            )
        seen[column] = field_name
        server_default = (
            spec.server_default
            if spec is not None and spec.server_default is not PydanticUndefined
            else UNSET
        )
        default = field_info.default
        if default is PydanticUndefined or default is GENERATED:
            default = UNSET
        if default is not UNSET and is_server_descriptor(default):
            raise SchemaError(
                f"{model.__name__}.{field_name}: SQL descriptors belong in server_default"
            )
        default_factory = field_info.default_factory
        constraints = spec.constraints if spec is not None else ColumnConstraints()
        timezone_enabled = (
            spec.timezone
            if spec is not None
            else (True if kind == "datetime" else None)
        )
        normalized_field = Field(
            name=field_name,
            column=column,
            annotation=normalized,
            required=field_info.is_required(),
            nullable=nullable,
            pk=bool(spec and spec.pk),
            unique=bool(spec and spec.unique),
            index=bool(spec and spec.index),
            default=default,
            server_default=server_default,
            default_factory=default_factory,
            kind=kind,
            constraints=constraints,
            allowed_values=allowed,
            timezone=timezone_enabled,
            pydantic_field=field_info,
        )
        if normalized_field.pk and normalized_field.nullable:
            raise SchemaError(
                f"{model.__name__}.{field_name}: primary key may not be nullable"
            )
        _check_server_default(model, normalized_field, has_generated)
        fields.append(normalized_field)

    if not fields:
        raise SchemaError(
            f"{model.__name__}: a concrete table must have at least one column"
        )
    return TableInfo(
        model=model, name=table_name, schema=schema_name, fields=tuple(fields)
    )


def _field_core_schema(model: type[BaseModel], field_name: str) -> CoreSchema:
    root: CoreSchema = model.__pydantic_core_schema__
    definitions: list[CoreSchema] = []
    if root["type"] == "definitions":
        definitions = cast(list[CoreSchema], root["definitions"])
        root = cast(CoreSchema, root["schema"])
    while root["type"] in ("function-before", "function-after", "function-wrap"):
        root = cast(CoreSchema, cast(dict[str, Any], root)["schema"])
    if root["type"] != "model":
        raise SchemaError(f"{model.__name__}: unsupported Pydantic core schema")
    model_fields = cast(dict[str, Any], root["schema"])["fields"]
    try:
        value_schema = cast(CoreSchema, model_fields[field_name]["schema"])
    except KeyError as exc:
        raise SchemaError(
            f"{model.__name__}: field {field_name!r} is not a column"
        ) from exc
    if definitions:
        return core_schema.definitions_schema(value_schema, definitions)
    return value_schema


def validate_field(model: type[object], field_name: str, value: object) -> object:
    """Validate one supplied literal without defaults, factories or model validators.

    The isolated Pydantic field core schema retains constraints and autonomous
    ``field_validator`` callbacks. Validators that require sibling state receive no
    fabricated row and fail normally; callers should surface that as unsupported.
    """

    info = table_of(cast(Any, model))
    info.field(field_name)
    return SchemaValidator(_field_core_schema(info.model, field_name)).validate_python(
        value
    )


def serialize_field(field: Field, value: object) -> object:
    """Prepare a field value for binding, notably JSON via Pydantic JSON mode.

    Query code should call this before dialect adaptation. It never stringifies
    unknown JSON objects and it preserves top-level ``None`` as SQL NULL.
    """

    if value is GENERATED:
        raise PydanticSerializationError(
            f"{field.name}: GENERATED cannot be serialized"
        )
    if field.kind == "json":
        annotation = field.pydantic_field.annotation
        if annotation is None:
            raise SchemaError(f"{field.name}: unresolved JSON annotation")
        return cast(
            object,
            TypeAdapter(annotation).dump_python(value, mode="json", warnings="error"),
        )
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = [
    "Field",
    "M",
    "TableInfo",
    "TableModel",
    "UNSET",
    "is_concrete_table",
    "serialize_field",
    "table_of",
    "validate_field",
]
