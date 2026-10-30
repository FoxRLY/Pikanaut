"""Pydantic-compatible typed column declaration factories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import Field as PydanticField
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from .defaults import GENERATED, ServerDefault, Identity, is_server_descriptor
from .errors import SchemaError

ColumnKind = Literal[
    "int",
    "float",
    "decimal",
    "bool",
    "str",
    "bytes",
    "uuid",
    "date",
    "time",
    "datetime",
    "json",
]


@dataclass(frozen=True, slots=True)
class ColumnConstraints:
    greater_than: object | None = None
    greater_than_or_equal: object | None = None
    less_than: object | None = None
    less_than_or_equal: object | None = None
    min_length: int | None = None
    max_length: int | None = None


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    kind: ColumnKind
    name: str | None = None
    pk: bool = False
    unique: bool = False
    index: bool = False
    server_default: object = PydanticUndefined
    constraints: ColumnConstraints = ColumnConstraints()
    timezone: bool | None = None


DefaultFactory = Callable[[], Any] | Callable[[dict[str, Any]], Any]


def _validate_constraints(constraints: ColumnConstraints) -> None:
    lower: list[tuple[object, bool]] = []
    upper: list[tuple[object, bool]] = []
    if constraints.greater_than is not None:
        lower.append((constraints.greater_than, False))
    if constraints.greater_than_or_equal is not None:
        lower.append((constraints.greater_than_or_equal, True))
    if constraints.less_than is not None:
        upper.append((constraints.less_than, False))
    if constraints.less_than_or_equal is not None:
        upper.append((constraints.less_than_or_equal, True))
    try:
        for low, low_inclusive in lower:
            for high, high_inclusive in upper:
                comparable_low = cast(Any, low)
                if comparable_low > high or (
                    low == high and not (low_inclusive and high_inclusive)
                ):
                    raise SchemaError("contradictory numeric bounds")
    except TypeError as exc:
        raise SchemaError("numeric bounds must be mutually comparable") from exc

    if (
        constraints.min_length is not None
        and constraints.max_length is not None
        and constraints.min_length > constraints.max_length
    ):
        raise SchemaError("contradictory string length constraints")
    if constraints.min_length is not None and constraints.min_length < 0:
        raise SchemaError("min_length must be non-negative")
    if constraints.max_length is not None and constraints.max_length < 0:
        raise SchemaError("max_length must be non-negative")


def _column(
    kind: ColumnKind,
    *,
    name: str | None,
    pk: bool,
    unique: bool,
    index: bool,
    default: Any,
    default_factory: DefaultFactory | None,
    server_default: object,
    constraints: ColumnConstraints = ColumnConstraints(),
    timezone: bool | None = None,
) -> Any:
    supplied = sum(
        (
            default is not PydanticUndefined,
            default_factory is not None,
            server_default is not PydanticUndefined,
        )
    )
    if supplied > 1:
        raise SchemaError(
            "default, default_factory and server_default are mutually exclusive"
        )
    if default is not PydanticUndefined and is_server_descriptor(default):
        raise SchemaError("SQL descriptors belong in server_default, not default")
    if server_default is not PydanticUndefined and not isinstance(
        server_default, (Identity, ServerDefault)
    ):
        raise SchemaError("server_default must be a pikanaut SQL descriptor")
    if name == "":
        raise SchemaError("column name may not be empty")
    _validate_constraints(constraints)

    field_kwargs: dict[str, Any] = {}
    if constraints.greater_than is not None:
        field_kwargs["gt"] = constraints.greater_than
    if constraints.greater_than_or_equal is not None:
        field_kwargs["ge"] = constraints.greater_than_or_equal
    if constraints.less_than is not None:
        field_kwargs["lt"] = constraints.less_than
    if constraints.less_than_or_equal is not None:
        field_kwargs["le"] = constraints.less_than_or_equal
    if constraints.min_length is not None:
        field_kwargs["min_length"] = constraints.min_length
    if constraints.max_length is not None:
        field_kwargs["max_length"] = constraints.max_length

    if server_default is not PydanticUndefined:
        field_info = PydanticField(default=GENERATED, **field_kwargs)
    elif default_factory is not None:
        field_info = PydanticField(default_factory=default_factory, **field_kwargs)
    elif default is not PydanticUndefined:
        field_info = PydanticField(default=default, **field_kwargs)
    else:
        field_info = PydanticField(**field_kwargs)

    assert isinstance(field_info, FieldInfo)
    field_info.metadata.append(
        ColumnSpec(
            kind=kind,
            name=name,
            pk=pk,
            unique=unique,
            index=index,
            server_default=server_default,
            constraints=constraints,
            timezone=timezone,
        )
    )
    return field_info


def _numeric_column(
    kind: Literal["int", "float", "decimal"],
    *,
    name: str | None,
    pk: bool,
    unique: bool,
    index: bool,
    default: Any,
    default_factory: DefaultFactory | None,
    server_default: object,
    greater_than: object | None,
    greater_than_or_equal: object | None,
    less_than: object | None,
    less_than_or_equal: object | None,
) -> Any:
    return _column(
        kind,
        name=name,
        pk=pk,
        unique=unique,
        index=index,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        constraints=ColumnConstraints(
            greater_than=greater_than,
            greater_than_or_equal=greater_than_or_equal,
            less_than=less_than,
            less_than_or_equal=less_than_or_equal,
        ),
    )


def IntColumn(
    *,
    name: str | None = None,
    pk: bool = False,
    unique: bool = False,
    index: bool = False,
    default: Any = PydanticUndefined,
    default_factory: DefaultFactory | None = None,
    server_default: object = PydanticUndefined,
    greater_than: object | None = None,
    greater_than_or_equal: object | None = None,
    less_than: object | None = None,
    less_than_or_equal: object | None = None,
) -> Any:
    return _numeric_column(
        "int",
        name=name,
        pk=pk,
        unique=unique,
        index=index,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        greater_than=greater_than,
        greater_than_or_equal=greater_than_or_equal,
        less_than=less_than,
        less_than_or_equal=less_than_or_equal,
    )


def FloatColumn(
    *,
    name: str | None = None,
    pk: bool = False,
    unique: bool = False,
    index: bool = False,
    default: Any = PydanticUndefined,
    default_factory: DefaultFactory | None = None,
    server_default: object = PydanticUndefined,
    greater_than: object | None = None,
    greater_than_or_equal: object | None = None,
    less_than: object | None = None,
    less_than_or_equal: object | None = None,
) -> Any:
    return _numeric_column(
        "float",
        name=name,
        pk=pk,
        unique=unique,
        index=index,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        greater_than=greater_than,
        greater_than_or_equal=greater_than_or_equal,
        less_than=less_than,
        less_than_or_equal=less_than_or_equal,
    )


def DecimalColumn(
    *,
    name: str | None = None,
    pk: bool = False,
    unique: bool = False,
    index: bool = False,
    default: Any = PydanticUndefined,
    default_factory: DefaultFactory | None = None,
    server_default: object = PydanticUndefined,
    greater_than: object | None = None,
    greater_than_or_equal: object | None = None,
    less_than: object | None = None,
    less_than_or_equal: object | None = None,
) -> Any:
    return _numeric_column(
        "decimal",
        name=name,
        pk=pk,
        unique=unique,
        index=index,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        greater_than=greater_than,
        greater_than_or_equal=greater_than_or_equal,
        less_than=less_than,
        less_than_or_equal=less_than_or_equal,
    )


def StrColumn(
    *,
    name: str | None = None,
    pk: bool = False,
    unique: bool = False,
    index: bool = False,
    default: Any = PydanticUndefined,
    default_factory: DefaultFactory | None = None,
    server_default: object = PydanticUndefined,
    min_length: int | None = None,
    max_length: int | None = None,
) -> Any:
    return _column(
        "str",
        name=name,
        pk=pk,
        unique=unique,
        index=index,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        constraints=ColumnConstraints(min_length=min_length, max_length=max_length),
    )


def _simple_factory(kind: ColumnKind) -> Callable[..., Any]:
    def factory(
        *,
        name: str | None = None,
        pk: bool = False,
        unique: bool = False,
        index: bool = False,
        default: Any = PydanticUndefined,
        default_factory: DefaultFactory | None = None,
        server_default: object = PydanticUndefined,
    ) -> Any:
        return _column(
            kind,
            name=name,
            pk=pk,
            unique=unique,
            index=index,
            default=default,
            default_factory=default_factory,
            server_default=server_default,
        )

    factory.__name__ = f"{kind.title()}Column"
    return factory


BoolColumn = _simple_factory("bool")
BytesColumn = _simple_factory("bytes")
UuidColumn = _simple_factory("uuid")
DateColumn = _simple_factory("date")
TimeColumn = _simple_factory("time")
JsonColumn = _simple_factory("json")


def DateTimeColumn(
    *,
    name: str | None = None,
    pk: bool = False,
    unique: bool = False,
    index: bool = False,
    default: Any = PydanticUndefined,
    default_factory: DefaultFactory | None = None,
    server_default: object = PydanticUndefined,
    timezone: bool = True,
) -> Any:
    return _column(
        "datetime",
        name=name,
        pk=pk,
        unique=unique,
        index=index,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        timezone=timezone,
    )


__all__ = [
    "BoolColumn",
    "BytesColumn",
    "ColumnConstraints",
    "ColumnKind",
    "ColumnSpec",
    "DateColumn",
    "DateTimeColumn",
    "DecimalColumn",
    "FloatColumn",
    "IntColumn",
    "JsonColumn",
    "StrColumn",
    "TimeColumn",
    "UuidColumn",
]
