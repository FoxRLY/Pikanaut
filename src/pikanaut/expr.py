"""Typed, source-aware SQL expressions for single-table queries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from functools import reduce
from typing import Any, Generic, overload

from pypika import Order as PypikaOrder, Table as PypikaTable, functions as fn
from pypika.terms import ComplexCriterion, Field, Not, Term
from typing_extensions import LiteralString, TypeVar

from .build import current
from .dialects.base import Feature
from .errors import QueryError, UnsupportedFeature

T = TypeVar("T")
S = TypeVar("S", default=object)

_DECIMAL_COMPARE = "decimal comparison"
_DECIMAL_ARITHMETIC = "Decimal arithmetic"
_DECIMAL_ORDER = "Decimal ordering"
_DECIMAL_GROUP = "Decimal grouping"
_DECIMAL_AGGREGATE = "Decimal aggregate"


class Bound(Term):
    """A value which is bound as a driver parameter while rendering."""

    def __init__(self, value: object, *, json: bool = False) -> None:
        super().__init__()
        self.value = value
        self.json = json

    def get_sql(self, **kwargs: Any) -> str:
        return current().bind(self.value, json=self.json)


class _Paren(Term):
    def __init__(self, inner: Term) -> None:
        super().__init__()
        self.inner = inner

    def get_sql(self, **kwargs: Any) -> str:
        return f"({self.inner.get_sql(**kwargs)})"


class _InList(Term):
    def __init__(
        self,
        column: Term,
        values: Sequence[object],
        invert: bool,
        *,
        json: bool = False,
    ) -> None:
        super().__init__()
        self.column = column
        self.values = values
        self.invert = invert
        self.json = json

    def get_sql(self, **kwargs: Any) -> str:
        ctx = current()
        return ctx.dialect.in_list(
            self.column.get_sql(**kwargs),
            ctx.binder,
            self.values,
            self.invert,
            json=self.json,
        )


class _ILike(Term):
    def __init__(self, column: Term, pattern: str) -> None:
        super().__init__()
        self.column = column
        self.pattern = pattern

    def get_sql(self, **kwargs: Any) -> str:
        ctx = current()
        if not ctx.dialect.has(Feature.ILIKE):
            raise UnsupportedFeature(
                ctx.dialect.name,
                "ILIKE",
                "use lower(column).like(...) or a dialect that supports ILIKE",
            )
        return f"{self.column.get_sql(**kwargs)} ILIKE {ctx.bind(self.pattern)}"


class _Raw(Term):
    def __init__(self, sql: str) -> None:
        super().__init__()
        self.sql = sql

    def get_sql(self, **kwargs: Any) -> str:
        return self.sql


class Cond(Generic[S]):
    """A condition carrying all table sources used by its expression tree."""

    __slots__ = ("criterion", "dependencies", "operations")
    criterion: Term
    dependencies: frozenset[object]
    operations: frozenset[str]

    def __init__(
        self,
        criterion: Term,
        dependencies: frozenset[object] = frozenset(),
        operations: frozenset[str] = frozenset(),
    ) -> None:
        self.criterion = criterion
        self.dependencies = dependencies
        self.operations = operations

    def __bool__(self) -> bool:
        raise TypeError(
            "Cond cannot be converted to bool; use and_(), or_(), &, |, or .where()"
        )

    def __and__(self, other: Cond[S]) -> Cond[S]:
        return Cond(
            self.criterion & other.criterion,  # type: ignore[operator]
            self.dependencies | other.dependencies,
            self.operations | other.operations,
        )

    def __or__(self, other: Cond[S]) -> Cond[S]:
        return Cond(
            self.criterion | other.criterion,  # type: ignore[operator]
            self.dependencies | other.dependencies,
            self.operations | other.operations,
        )

    def __invert__(self) -> Cond[S]:
        inner = self.criterion
        criterion = (
            Not(inner) if isinstance(inner, ComplexCriterion) else Not(_Paren(inner))
        )
        return Cond(criterion, self.dependencies, self.operations)

    def __repr__(self) -> str:
        return f"Cond({self.criterion})"


def _require_conds(conds: tuple[object, ...], name: str) -> None:
    if not conds:
        raise QueryError(f"{name}() requires at least one condition")
    for cond in conds:
        if not isinstance(cond, Cond):
            raise QueryError(f"{name}() expects Cond, got {type(cond).__name__}")


def and_(*conds: Cond[S]) -> Cond[S]:
    _require_conds(conds, "and_")
    return reduce(lambda left, right: left & right, conds)


def or_(*conds: Cond[S]) -> Cond[S]:
    _require_conds(conds, "or_")
    return reduce(lambda left, right: left | right, conds)


def not_(cond: Cond[S]) -> Cond[S]:
    return ~cond


class Order(Generic[S]):
    __slots__ = ("term", "ascending", "dependencies", "operations")
    term: Term
    ascending: bool
    dependencies: frozenset[object]
    operations: frozenset[str]

    def __init__(
        self,
        term: Term,
        ascending: bool,
        dependencies: frozenset[object] = frozenset(),
        operations: frozenset[str] = frozenset(),
    ) -> None:
        self.term = term
        self.ascending = ascending
        self.dependencies = dependencies
        self.operations = operations

    @staticmethod
    def direction(ascending: bool) -> PypikaOrder:
        return PypikaOrder.asc if ascending else PypikaOrder.desc


class Column(Generic[T, S]):
    """A typed SQL value carrying its concrete single-table source."""

    __slots__ = (
        "name",
        "nullable",
        "term",
        "table",
        "dependencies",
        "operations",
        "value_type",
        "is_decimal",
        "is_json",
    )
    dependencies: frozenset[object]
    operations: frozenset[str]

    def __init__(
        self,
        name: str,
        *,
        table: PypikaTable | None = None,
        source: object | None = None,
        nullable: bool = True,
        term: Term | None = None,
        dependencies: frozenset[object] | None = None,
        operations: frozenset[str] = frozenset(),
        value_type: object = object,
        is_decimal: bool = False,
        is_json: bool = False,
    ) -> None:
        self.name = name
        self.nullable = nullable
        self.table = table
        self.term: Term = term if term is not None else Field(name, table=table)
        self.dependencies = (
            dependencies
            if dependencies is not None
            else (frozenset((source,)) if source is not None else frozenset())
        )
        self.operations = operations
        self.value_type = value_type
        self.is_decimal = is_decimal
        self.is_json = is_json

    def __hash__(self) -> int:
        return hash(("pikanaut.Column", self.name, str(self.term), self.dependencies))

    def __repr__(self) -> str:
        return f"Column({self.name!r})"

    def _right(
        self, other: object
    ) -> tuple[Term, frozenset[object], frozenset[str], bool]:
        if isinstance(other, Column):
            return other.term, other.dependencies, other.operations, other.is_decimal
        return (
            Bound(other, json=self.is_json),
            frozenset(),
            frozenset(),
            isinstance(other, Decimal),
        )

    def _comparison(self, other: object, operator: str) -> Cond[S]:
        right, dependencies, operations, right_decimal = self._right(other)
        if self.is_decimal or right_decimal:
            operations = operations | {_DECIMAL_COMPARE}
        if operator == "eq":
            criterion = self.term == right
        elif operator == "ne":
            criterion = self.term != right
        elif operator == "gt":
            criterion = self.term > right
        elif operator == "ge":
            criterion = self.term >= right
        elif operator == "lt":
            criterion = self.term < right
        else:
            criterion = self.term <= right
        return Cond(
            criterion,
            self.dependencies | dependencies,
            self.operations | operations,
        )

    def __eq__(self, other: T | Column[T, S] | None) -> Cond[S]:  # type: ignore[override]
        if other is None:
            if not self.nullable:
                raise TypeError(
                    f"Column {self.name!r} is NOT NULL; use .is_null() only for nullable columns"
                )
            return self.is_null()
        return self._comparison(other, "eq")

    def __ne__(self, other: T | Column[T, S] | None) -> Cond[S]:  # type: ignore[override]
        if other is None:
            if not self.nullable:
                raise TypeError(
                    f"Column {self.name!r} is NOT NULL; use .is_not_null() only for nullable columns"
                )
            return self.is_not_null()
        return self._comparison(other, "ne")

    def __gt__(self, other: T | Column[T, S]) -> Cond[S]:
        return self._comparison(other, "gt")

    def __ge__(self, other: T | Column[T, S]) -> Cond[S]:
        return self._comparison(other, "ge")

    def __lt__(self, other: T | Column[T, S]) -> Cond[S]:
        return self._comparison(other, "lt")

    def __le__(self, other: T | Column[T, S]) -> Cond[S]:
        return self._comparison(other, "le")

    def is_null(self) -> Cond[S]:
        return Cond(self.term.isnull(), self.dependencies, self.operations)

    def is_not_null(self) -> Cond[S]:
        return Cond(self.term.isnotnull(), self.dependencies, self.operations)

    def in_(self, values: Iterable[T]) -> Cond[S]:
        items = list(values)
        if not items:
            raise QueryError(
                "empty IN list",
                hint="an empty IN can never match; skip the clause instead",
            )
        operations = self.operations
        if self.is_decimal:
            operations = operations | {_DECIMAL_COMPARE}
        return Cond(
            _InList(self.term, items, invert=False, json=self.is_json),
            self.dependencies,
            operations,
        )

    def not_in(self, values: Iterable[T]) -> Cond[S]:
        items = list(values)
        if not items:
            raise QueryError(
                "empty IN list",
                hint="an empty NOT IN matches everything; skip the clause instead",
            )
        operations = self.operations
        if self.is_decimal:
            operations = operations | {_DECIMAL_COMPARE}
        return Cond(
            _InList(self.term, items, invert=True, json=self.is_json),
            self.dependencies,
            operations,
        )

    def like(self: Column[str, S], pattern: str) -> Cond[S]:
        return Cond(
            self.term.like(Bound(pattern)),  # type: ignore[arg-type]
            self.dependencies,
            self.operations,
        )

    def ilike(self: Column[str, S], pattern: str) -> Cond[S]:
        return Cond(_ILike(self.term, pattern), self.dependencies, self.operations)

    def contains(self: Column[str, S], text: str) -> Cond[S]:
        return self.like(f"%{text}%")

    def starts_with(self: Column[str, S], text: str) -> Cond[S]:
        return self.like(f"{text}%")

    def ends_with(self: Column[str, S], text: str) -> Cond[S]:
        return self.like(f"%{text}")

    def _ordering_operations(self) -> frozenset[str]:
        extra = frozenset[str]({_DECIMAL_ORDER}) if self.is_decimal else frozenset[str]()
        return self.operations | extra

    def desc(self) -> Order[S]:
        return Order(self.term, False, self.dependencies, self._ordering_operations())

    def asc(self) -> Order[S]:
        return Order(self.term, True, self.dependencies, self._ordering_operations())

    def _arith(self, other: object, op: str) -> Column[Any, S]:
        right, dependencies, operations, right_decimal = self._right(other)
        if op == "add":
            term = self.term + right
        elif op == "sub":
            term = self.term - right
        elif op == "mul":
            term = self.term * right
        else:
            term = self.term / right
        decimal = self.is_decimal or right_decimal
        if decimal:
            operations = operations | {_DECIMAL_ARITHMETIC}
        return _column(
            term,
            self.name,
            nullable=self.nullable,
            table=self.table,
            dependencies=self.dependencies | dependencies,
            operations=self.operations | operations,
            value_type=self.value_type,
            is_decimal=decimal,
        )

    @overload
    def __add__(
        self: Column[int, S], other: int | Column[int, S]
    ) -> Column[int, S]: ...

    @overload
    def __add__(
        self: Column[float, S], other: float | Column[float, S]
    ) -> Column[float, S]: ...

    @overload
    def __add__(
        self: Column[Decimal, S], other: Decimal | Column[Decimal, S]
    ) -> Column[Decimal, S]: ...

    @overload
    def __add__(
        self: Column[str, S], other: str | Column[str, S]
    ) -> Column[str, S]: ...

    def __add__(self, other: object) -> Column[Any, S]:
        return self._arith(other, "add")

    @overload
    def __sub__(
        self: Column[int, S], other: int | Column[int, S]
    ) -> Column[int, S]: ...

    @overload
    def __sub__(
        self: Column[float, S], other: float | Column[float, S]
    ) -> Column[float, S]: ...

    @overload
    def __sub__(
        self: Column[Decimal, S], other: Decimal | Column[Decimal, S]
    ) -> Column[Decimal, S]: ...

    def __sub__(self, other: object) -> Column[Any, S]:
        return self._arith(other, "sub")

    @overload
    def __mul__(
        self: Column[int, S], other: int | Column[int, S]
    ) -> Column[int, S]: ...

    @overload
    def __mul__(
        self: Column[float, S], other: float | Column[float, S]
    ) -> Column[float, S]: ...

    @overload
    def __mul__(
        self: Column[Decimal, S], other: Decimal | Column[Decimal, S]
    ) -> Column[Decimal, S]: ...

    def __mul__(self, other: object) -> Column[Any, S]:
        return self._arith(other, "mul")

    @overload
    def __truediv__(
        self: Column[int, S], other: int | Column[int, S]
    ) -> Column[float, S]: ...

    @overload
    def __truediv__(
        self: Column[float, S], other: float | Column[float, S]
    ) -> Column[float, S]: ...

    @overload
    def __truediv__(
        self: Column[Decimal, S], other: Decimal | Column[Decimal, S]
    ) -> Column[Decimal, S]: ...

    def __truediv__(self, other: object) -> Column[Any, S]:
        return self._arith(other, "div")


def _column(
    term: Term,
    name: str,
    nullable: bool = True,
    table: PypikaTable | None = None,
    *,
    dependencies: frozenset[object] = frozenset(),
    operations: frozenset[str] = frozenset(),
    value_type: object = object,
    is_decimal: bool = False,
    is_json: bool = False,
) -> Column[Any, Any]:
    return Column(
        name,
        term=term,
        table=table,
        nullable=nullable,
        dependencies=dependencies,
        operations=operations,
        value_type=value_type,
        is_decimal=is_decimal,
        is_json=is_json,
    )


def _arg(column: Column[T, S]) -> Term:
    return column.term


@overload
def count(column: Column[Any, S]) -> Column[int, S]: ...


@overload
def count(column: None = None) -> Column[int, Any]: ...


def count(column: Column[Any, Any] | None = None) -> Column[int, Any]:
    term = fn.Count("*") if column is None else fn.Count(_arg(column))
    return _column(
        term,
        "count",
        nullable=False,
        table=None if column is None else column.table,
        dependencies=frozenset() if column is None else column.dependencies,
        operations=frozenset() if column is None else column.operations,
        value_type=int,
    )


def _aggregate_operations(column: Column[Any, Any]) -> frozenset[str]:
    extra = (
        frozenset[str]({_DECIMAL_AGGREGATE}) if column.is_decimal else frozenset[str]()
    )
    return column.operations | extra


def sum(column: Column[T, S]) -> Column[T, S]:
    return _column(
        fn.Sum(_arg(column)),
        "sum",
        table=column.table,
        dependencies=column.dependencies,
        operations=_aggregate_operations(column),
        value_type=column.value_type,
        is_decimal=column.is_decimal,
    )


def avg(column: Column[Any, S]) -> Column[float, S]:
    return _column(
        fn.Avg(_arg(column)),
        "avg",
        table=column.table,
        dependencies=column.dependencies,
        operations=_aggregate_operations(column),
        value_type=float,
        is_decimal=column.is_decimal,
    )


def max(column: Column[T, S]) -> Column[T, S]:
    return _column(
        fn.Max(_arg(column)),
        "max",
        table=column.table,
        dependencies=column.dependencies,
        operations=_aggregate_operations(column),
        value_type=column.value_type,
        is_decimal=column.is_decimal,
    )


def min(column: Column[T, S]) -> Column[T, S]:
    return _column(
        fn.Min(_arg(column)),
        "min",
        table=column.table,
        dependencies=column.dependencies,
        operations=_aggregate_operations(column),
        value_type=column.value_type,
        is_decimal=column.is_decimal,
    )


def coalesce(first: Column[T, S], *values: T | Column[T, S]) -> Column[T, S]:
    all_values: tuple[object, ...] = (first, *values)
    args = [
        value.term if isinstance(value, Column) else Bound(value)
        for value in all_values
    ]
    columns: list[Column[Any, Any]] = [
        value for value in all_values if isinstance(value, Column)
    ]
    dependencies: frozenset[object] = frozenset[object]().union(
        *(column.dependencies for column in columns)
    )
    operations: frozenset[str] = frozenset[str]().union(
        *(column.operations for column in columns)
    )
    return _column(
        fn.Coalesce(*args),  # type: ignore[no-untyped-call]
        "coalesce",
        table=first.table,
        dependencies=dependencies,
        operations=operations,
        value_type=first.value_type,
        is_decimal=any(column.is_decimal for column in columns),
        is_json=first.is_json,
    )


def lower(column: Column[str, S]) -> Column[str, S]:
    return _column(
        fn.Lower(_arg(column)),
        "lower",
        table=column.table,
        dependencies=column.dependencies,
        operations=column.operations,
        value_type=str,
    )


def upper(column: Column[str, S]) -> Column[str, S]:
    return _column(
        fn.Upper(_arg(column)),
        "upper",
        table=column.table,
        dependencies=column.dependencies,
        operations=column.operations,
        value_type=str,
    )


def raw(sql: LiteralString) -> Column[Any, Any]:
    """Escape hatch for developer-authored static SQL."""
    return _column(_Raw(sql), sql)


def decimal_group_operation(column: Column[Any, Any]) -> frozenset[str]:
    """Internal marker used by GROUP BY without exposing operands publicly."""
    if column.is_decimal:
        return column.operations | {_DECIMAL_GROUP}
    return column.operations
