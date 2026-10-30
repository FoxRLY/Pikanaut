"""Runtime support used by generated, statically typed table modules."""

from __future__ import annotations

from collections.abc import Hashable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Generic, cast, get_args

from typing_extensions import TypeVar

from .dialects.base import Dialect, Limits
from .expr import Column
from .schema import TableInfo, table_of

if TYPE_CHECKING:
    from .client import Update

M = TypeVar("M")
S = TypeVar("S")


def _annotation_contains(annotation: object, expected: type[object]) -> bool:
    if annotation is expected:
        return True
    return any(_annotation_contains(arg, expected) for arg in get_args(annotation))


def _field_is_json(field: object) -> bool:
    for attribute in ("kind", "column_kind", "python_kind"):
        value = getattr(field, attribute, None)
        if value == "json" or getattr(value, "value", None) == "json":
            return True
    declaration = getattr(field, "declaration", None) or getattr(
        field, "column_info", None
    )
    return declaration is not None and type(declaration).__name__ == "JsonColumn"


class Table(Generic[M, S]):
    """Base for generated tables; ordinary names remain available to SQL columns."""

    __slots__ = ("__pikanaut_info__",)

    __pikanaut_info__: TableInfo

    def __init__(self, model: type[M]) -> None:
        self.__pikanaut_info__ = table_of(cast(Hashable, model))

    def __pikanaut_column__(self, field_name: str) -> Column[Any, S]:
        field = self.__pikanaut_info__.field(field_name)
        annotation = getattr(field, "value_annotation", field.annotation)
        return Column(
            field.column,
            table=self.__pikanaut_info__.pypika_table(),
            source=self.__pikanaut_info__,
            nullable=field.nullable,
            value_type=annotation,
            is_decimal=_annotation_contains(annotation, Decimal),
            is_json=_field_is_json(field),
        )

    def __pikanaut_update__(
        self, dialect: Dialect, limits: Limits, require_where: bool = True
    ) -> Update[S]:
        # Any is confined to this override hook. Generated subclasses publish the
        # concrete Update[S] return type consumed by Client's factory protocol.
        from .client import Update

        return Update(
            dialect,
            limits,
            self.__pikanaut_info__,
            require_where=require_where,
        )
