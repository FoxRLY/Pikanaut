"""Выражения: колонки, условия, функции (SPEC.md, раздел 4).

Правила:

- ``Column[T]`` — типизированная ссылка на колонку; сравнения возвращают ``Cond``;
- ``bool(cond)`` запрещён: Cond всегда truthy, ``if U.age > 18:`` — почти всегда баг;
- ``U.col == None`` на nullable-колонке даёт ``IS NULL``, на NOT NULL — ``TypeError``;
- ``__eq__`` переопределён, поэтому ``__hash__`` задан явно.

Диалект здесь не участвует: решения, зависящие от диалекта (плейсхолдер, форма IN,
ILIKE), принимаются при рендере через ``build.current()``.
"""

from __future__ import annotations

from functools import reduce
from typing import Any, Generic, TypeVar

from pypika import Table, functions as fn
from pypika.terms import ComplexCriterion, Field, Not, Term

from .build import current
from .dialects.base import Feature
from .errors import QueryError, UnsupportedFeature

T = TypeVar("T")


class Bound(Term):
    """Значение, которое станет параметром при рендере."""

    def __init__(self, value: Any) -> None:
        super().__init__()
        self.value = value

    def get_sql(self, **kwargs: Any) -> str:
        return current().bind(self.value)


class _Paren(Term):
    """Скобки вокруг подвыражения (для NOT)."""

    def __init__(self, inner: Term) -> None:
        super().__init__()
        self.inner = inner

    def get_sql(self, **kwargs: Any) -> str:
        return f"({self.inner.get_sql(**kwargs)})"


class _InList(Term):
    """``IN (?,?,?)`` или ``= ANY($1)`` — решает диалект."""

    def __init__(self, column: Term, values: list[Any], invert: bool) -> None:
        super().__init__()
        self.column = column
        self.values = values
        self.invert = invert

    def get_sql(self, **kwargs: Any) -> str:
        ctx = current()
        return ctx.dialect.in_list(
            self.column.get_sql(**kwargs), ctx.binder, self.values, self.invert
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
                "use .lower().like() or a dialect that supports ILIKE",
            )
        return f"{self.column.get_sql(**kwargs)} ILIKE {ctx.bind(self.pattern)}"


class _Raw(Term):
    def __init__(self, sql: str) -> None:
        super().__init__()
        self.sql = sql

    def get_sql(self, **kwargs: Any) -> str:
        return self.sql


class Cond:
    """SQL-условие. Не bool."""

    __slots__ = ("criterion",)

    def __init__(self, criterion: Term) -> None:
        self.criterion = criterion

    def __bool__(self) -> bool:
        raise TypeError(
            "Cond нельзя приводить к bool: используйте and_(), or_(), оператор & и |, "
            "или передайте условие в .where()"
        )

    def __and__(self, other: Cond) -> Cond:
        return Cond(self.criterion & other.criterion)  # type: ignore[operator]

    def __or__(self, other: Cond) -> Cond:
        return Cond(self.criterion | other.criterion)  # type: ignore[operator]

    def __invert__(self) -> Cond:
        inner = self.criterion
        if isinstance(inner, ComplexCriterion):
            return Cond(Not(inner))
        return Cond(Not(_Paren(inner)))

    def __repr__(self) -> str:
        return f"Cond({self.criterion})"


def _require_conds(conds: tuple[Any, ...], name: str) -> None:
    if not conds:
        raise QueryError(f"{name}() requires at least one condition")
    for cond in conds:
        if not isinstance(cond, Cond):
            raise QueryError(f"{name}() expects Cond, got {type(cond).__name__}")


def and_(*conds: Cond) -> Cond:
    _require_conds(conds, "and_")
    return reduce(lambda a, b: a & b, conds)


def or_(*conds: Cond) -> Cond:
    _require_conds(conds, "or_")
    return reduce(lambda a, b: a | b, conds)


def not_(cond: Any) -> Cond:
    if not isinstance(cond, Cond):
        raise QueryError(f"not_() expects Cond, got {type(cond).__name__}")
    return ~cond


class Order:
    """Направление сортировки."""

    __slots__ = ("term", "ascending")

    def __init__(self, term: Term, ascending: bool) -> None:
        self.term = term
        self.ascending = ascending

    @staticmethod
    def direction(ascending: bool) -> Any:
        from pypika import Order as PypikaOrder

        return PypikaOrder.asc if ascending else PypikaOrder.desc


class Column(Generic[T]):
    """Колонка таблицы (или выражение над ней). Сравнения возвращают Cond."""

    __slots__ = ("name", "nullable", "term", "table")

    def __init__(
        self,
        name: str,
        *,
        table: Table | None = None,
        nullable: bool = True,
        term: Term | None = None,
    ) -> None:
        self.name = name
        self.nullable = nullable
        self.table = table
        self.term: Term = term if term is not None else Field(name, table=table)

    def __hash__(self) -> int:
        return hash(("pikanaut.Column", self.name, str(self.term)))

    def __repr__(self) -> str:
        return f"Column({self.name!r})"


    # сравнения
    def __eq__(self, other: Any) -> Cond:  # type: ignore[override]
        if other is None:
            if not self.nullable:
                raise TypeError(
                    f"Column {self.name!r} is NOT NULL: comparison with None can never match — "
                    "use .is_null() if the column really is nullable"
                )
            return Cond(self.term.isnull())
        return Cond(self.term == Bound(other))

    def __ne__(self, other: Any) -> Cond:  # type: ignore[override]
        if other is None:
            if not self.nullable:
                raise TypeError(
                    f"Column {self.name!r} is NOT NULL: comparison with None can never match — "
                    "use .is_not_null() if the column really is nullable"
                )
            return Cond(self.term.isnotnull())
        return Cond(self.term != Bound(other))

    def __gt__(self, other: Any) -> Cond:
        return Cond(self.term > Bound(other))

    def __ge__(self, other: Any) -> Cond:
        return Cond(self.term >= Bound(other))

    def __lt__(self, other: Any) -> Cond:
        return Cond(self.term < Bound(other))

    def __le__(self, other: Any) -> Cond:
        return Cond(self.term <= Bound(other))

    # предикаты
    def is_null(self) -> Cond:
        return Cond(self.term.isnull())

    def is_not_null(self) -> Cond:
        return Cond(self.term.isnotnull())

    def in_(self, values: Any) -> Cond:
        items = list(values)
        if not items:
            raise QueryError(
                "empty IN list", hint="an empty IN can never match — skip the clause instead"
            )
        return Cond(_InList(self.term, items, invert=False))

    def not_in(self, values: Any) -> Cond:
        items = list(values)
        if not items:
            raise QueryError(
                "empty IN list", hint="an empty NOT IN matches everything — skip the clause instead"
            )
        return Cond(_InList(self.term, items, invert=True))

    def like(self, pattern: str) -> Cond:
        return Cond(self.term.like(Bound(pattern)))  # type: ignore[arg-type]

    def ilike(self, pattern: str) -> Cond:
        return Cond(_ILike(self.term, pattern))

    def contains(self, text: str) -> Cond:
        return self.like(f"%{text}%")

    def starts_with(self, text: str) -> Cond:
        return self.like(f"{text}%")

    def ends_with(self, text: str) -> Cond:
        return self.like(f"%{text}")

    # порядок сортировки
    def desc(self) -> Order:
        return Order(self.term, ascending=False)

    def asc(self) -> Order:
        return Order(self.term, ascending=True)

    # арифметика
    def _arith(self, other: Any, op: str) -> Column[Any]:
        right = other.term if isinstance(other, Column) else Bound(other)
        if op == "add":
            term = self.term + right
        elif op == "sub":
            term = self.term - right
        elif op == "mul":
            term = self.term * right
        else:
            term = self.term / right
        return _column(term, self.name, table=self.table)

    def __add__(self, other: Any) -> Column[Any]:
        return self._arith(other, "add")

    def __sub__(self, other: Any) -> Column[Any]:
        return self._arith(other, "sub")

    def __mul__(self, other: Any) -> Column[Any]:
        return self._arith(other, "mul")

    def __truediv__(self, other: Any) -> Column[Any]:
        return self._arith(other, "div")


def _column(
    term: Term, name: str, nullable: bool = True, table: Table | None = None
) -> Column[Any]:
    """Обернуть произвольный терм (функцию, арифметику) в Column, сохранив таблицу."""
    column: Column[Any] = Column(name, term=term, nullable=nullable)
    column.table = table
    return column


def _arg(column: Column[Any]) -> Term:
    return column.term


def count(column: Column[Any] | None = None) -> Column[int]:
    term = fn.Count("*") if column is None else fn.Count(_arg(column))
    return _column(term, "count", nullable=False, table=None if column is None else column.table)


def sum(column: Column[T]) -> Column[T]:
    return _column(fn.Sum(_arg(column)), "sum", table=column.table)


def avg(column: Column[Any]) -> Column[float]:
    return _column(fn.Avg(_arg(column)), "avg", table=column.table)


def max(column: Column[T]) -> Column[T]:
    return _column(fn.Max(_arg(column)), "max", table=column.table)


def min(column: Column[T]) -> Column[T]:
    return _column(fn.Min(_arg(column)), "min", table=column.table)


def coalesce(*values: Any) -> Column[Any]:
    args = [v.term if isinstance(v, Column) else Bound(v) for v in values]
    table = next((v.table for v in values if isinstance(v, Column)), None)
    return _column(fn.Coalesce(*args), "coalesce", table=table)  # type: ignore[no-untyped-call]


def lower(column: Column[str]) -> Column[str]:
    return _column(fn.Lower(_arg(column)), "lower", table=column.table)


def upper(column: Column[str]) -> Column[str]:
    return _column(fn.Upper(_arg(column)), "upper", table=column.table)


def raw(sql: str) -> Column[Any]:
    """Escape hatch для того, что не покрыто API."""
    return _column(_Raw(sql), sql)
