"""Immutable single-table SELECT, INSERT, UPDATE, and DELETE builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import copy
from typing import Any, Generic, Protocol, TypeVar, cast, overload

from pydantic import BaseModel
from pypika import Query
from pypika.terms import Field
from typing_extensions import Self

from .build import Sql, render
from .defaults import GENERATED, Identity
from .dialects.base import Dialect, Feature, Limits
from .errors import QueryError, QueryTooLong, UnsupportedFeature, UnsupportedOperation
from .expr import Bound, Column, Cond, Order, decimal_group_operation
from .schema import Field as SchemaField
from .schema import TableInfo, serialize_field, validate_field
from .tables import Table

S = TypeVar("S")
T = TypeVar("T")
M = TypeVar("M")
U = TypeVar("U", bound="Update[Any]")
U_co = TypeVar("U_co", bound="Update[Any]", covariant=True)


class _Default:
    __slots__ = ()


_DEFAULT = _Default()


def _quote_identifier(value: str, quote_char: str) -> str:
    escaped = value.replace(quote_char, quote_char * 2)
    return f"{quote_char}{escaped}{quote_char}"


def _table_sql(info: TableInfo, quote_char: str) -> str:
    table = _quote_identifier(info.name, quote_char)
    if info.schema is not None:
        return f"{_quote_identifier(info.schema, quote_char)}.{table}"
    return table


def _field_kind(field: object) -> object:
    kind = getattr(field, "kind", None)
    if kind is not None:
        return kind
    spec = getattr(field, "spec", None) or getattr(field, "column_info", None)
    return getattr(spec, "kind", None)


def _is_json_field(field: object) -> bool:
    kind = _field_kind(field)
    return kind == "json" or getattr(kind, "value", None) == "json"


def _server_default(field: object) -> object | None:
    value = getattr(field, "server_default", None)
    if value is not None:
        return cast(object, value)
    spec = getattr(field, "spec", None) or getattr(field, "column_info", None)
    return cast(object | None, getattr(spec, "server_default", None))


def _is_always_identity(field: object) -> bool:
    value = _server_default(field)
    return isinstance(value, Identity) and value.generated == "ALWAYS"


def _clone(builder: T, **changes: object) -> T:
    result = copy(builder)
    for name, value in changes.items():
        setattr(result, name, value)
    return result


def _dependencies(value: object) -> frozenset[object]:
    if isinstance(value, (Column, Cond, Order)):
        return value.dependencies
    return frozenset()


def _operations(value: object) -> frozenset[str]:
    if isinstance(value, (Column, Cond, Order)):
        return value.operations
    return frozenset()


def _check_source(info: TableInfo, *values: object) -> None:
    for value in values:
        for dependency in _dependencies(value):
            if dependency is not info:
                raise QueryError(
                    f"expression source belongs to another table, not {info.name!r}"
                )


def _check_operations(dialect: Dialect, *values: object) -> None:
    if not dialect.name.startswith("sqlite"):
        return
    operations: set[str] = set()
    for value in values:
        operations.update(_operations(value))
    if operations:
        operation = ", ".join(sorted(operations))
        raise UnsupportedOperation(
            dialect.name,
            operation,
            "SQLite stores Decimal as TEXT; use PostgreSQL for Decimal numeric operations",
        )


def _returning_names(
    dialect: Dialect, info: TableInfo, returning: tuple[Column[Any, Any], ...]
) -> tuple[str, ...]:
    if returning and not dialect.has(Feature.RETURNING):
        raise UnsupportedFeature(dialect.name, "returning")
    _check_source(info, *returning)
    return tuple(column.name for column in returning)


def _offset_without_limit(query: object) -> bool:
    return bool(getattr(query, "_offset", None)) and not getattr(query, "_limit", None)


class Select(Generic[S]):
    __slots__ = (
        "_dialect",
        "_limits",
        "_info",
        "_columns",
        "_conds",
        "_orders",
        "_groups",
        "_having",
        "_limit",
        "_offset",
    )

    def __init__(
        self,
        dialect: Dialect,
        limits: Limits,
        info: TableInfo,
        columns: tuple[Column[Any, S], ...],
    ) -> None:
        self._dialect = dialect
        self._limits = limits
        self._info = info
        self._columns = columns
        self._conds: tuple[Cond[S], ...] = ()
        self._orders: tuple[Column[Any, S] | Order[S], ...] = ()
        self._groups: tuple[Column[Any, S], ...] = ()
        self._having: tuple[Cond[S], ...] = ()
        self._limit: int | None = None
        self._offset: int | None = None

    def where(self, *conds: Cond[S]) -> Self:
        return _clone(self, _conds=(*self._conds, *conds))

    def order_by(self, *columns: Column[Any, S] | Order[S]) -> Self:
        return _clone(self, _orders=(*self._orders, *columns))

    def group_by(self, *columns: Column[Any, S]) -> Self:
        return _clone(self, _groups=(*self._groups, *columns))

    def having(self, *conds: Cond[S]) -> Self:
        return _clone(self, _having=(*self._having, *conds))

    def limit(self, count: int) -> Self:
        if count < 0:
            raise QueryError("LIMIT may not be negative")
        return _clone(self, _limit=count)

    def offset(self, count: int) -> Self:
        if count < 0:
            raise QueryError("OFFSET may not be negative")
        return _clone(self, _offset=count)

    def build(self) -> Sql:
        values: tuple[object, ...] = (
            *self._columns,
            *self._conds,
            *self._orders,
            *self._groups,
            *self._having,
        )
        _check_source(self._info, *values)
        operation_values: list[object] = list(values)
        for order in self._orders:
            if isinstance(order, Column) and order.is_decimal:
                operation_values.append(order.asc())
        for column in self._groups:
            if decimal_group_operation(column) != column.operations:
                marker = copy(column)
                marker.operations = decimal_group_operation(column)
                operation_values.append(marker)
        _check_operations(self._dialect, *operation_values)

        table = self._info.pypika_table()
        query = Query.from_(table).select(*[column.term for column in self._columns])
        for cond in self._conds:
            query = query.where(cond.criterion)
        for order in self._orders:
            if isinstance(order, Order):
                query = query.orderby(
                    order.term, order=Order.direction(order.ascending)
                )
            else:
                query = query.orderby(order.term)
        for column in self._groups:
            query = query.groupby(column.term)
        for cond in self._having:
            query = query.having(cond.criterion)
        if self._limit is not None:
            query = query.limit(self._limit)
        if self._offset is not None:
            query = query.offset(self._offset)
        if self._dialect.name.startswith("sqlite") and _offset_without_limit(query):
            query = query.limit(-1)
        return render(
            query,
            self._dialect,
            self._limits,
            schema=self._info.schema,
        )


class _InsertQuery:
    __slots__ = ("info", "fields", "rows")

    def __init__(
        self,
        info: TableInfo,
        fields: tuple[SchemaField, ...],
        rows: tuple[tuple[object, ...], ...],
    ) -> None:
        self.info = info
        self.fields = fields
        self.rows = rows

    def get_sql(self, *, quote_char: str) -> str:
        table = _table_sql(self.info, quote_char)
        if not self.fields:
            return f"INSERT INTO {table} DEFAULT VALUES"
        columns = ",".join(
            _quote_identifier(field.column, quote_char) for field in self.fields
        )
        rendered_rows: list[str] = []
        for row in self.rows:
            cells: list[str] = []
            for field, value in zip(self.fields, row, strict=True):
                if value is _DEFAULT:
                    cells.append("DEFAULT")
                elif value is None:
                    # Top-level None in a JSON column is SQL NULL, not JSON null.
                    cells.append(Bound(None).get_sql())
                else:
                    cells.append(Bound(value, json=_is_json_field(field)).get_sql())
            rendered_rows.append(f"({','.join(cells)})")
        return f"INSERT INTO {table} ({columns}) VALUES {','.join(rendered_rows)}"


class Insert(Generic[S]):
    __slots__ = ("_dialect", "_limits", "_info", "_models", "_returning")

    def __init__(
        self,
        dialect: Dialect,
        limits: Limits,
        info: TableInfo,
        models: Sequence[BaseModel],
    ) -> None:
        self._dialect = dialect
        self._limits = limits
        self._info = info
        self._models = tuple(models)
        self._returning: tuple[Column[Any, S], ...] = ()

    def returning(self, *columns: Column[Any, S]) -> Self:
        return _clone(self, _returning=tuple(columns))

    def batch(self) -> InsertBatch[S]:
        return InsertBatch(self)

    def _rows(self) -> tuple[tuple[SchemaField, ...], tuple[dict[str, object], ...]]:
        if not self._models:
            raise QueryError(
                "nothing to insert", hint="pass at least one model instance"
            )
        if any(type(model) is not self._info.model for model in self._models):
            raise QueryError(
                f"model does not match table {self._info.name!r}",
                hint=f"pass instances of {self._info.model.__name__}",
            )
        rows: list[dict[str, object]] = []
        for model in self._models:
            row: dict[str, object] = {}
            for field in self._info.fields:
                value = getattr(model, field.name)
                if value is GENERATED:
                    continue
                if _is_always_identity(field):
                    raise QueryError(
                        f"{field.name!r} is an ALWAYS identity and cannot be inserted explicitly"
                    )
                row[field.name] = serialize_field(field, value)
            rows.append(row)
        return self._info.fields, tuple(rows)

    def _build_rows(self, rows: tuple[dict[str, object], ...]) -> Sql:
        all_fields, _ = self._rows()
        shapes = [
            tuple(field.name for field in all_fields if field.name in row)
            for row in rows
        ]
        if self._dialect.name.startswith("sqlite") and any(
            shape != shapes[0] for shape in shapes[1:]
        ):
            raise QueryError(
                "SQLite insert_many rows have different generated-value shapes",
                hint="call .batch() to split contiguous row shapes",
            )
        union_names = tuple(
            field.name for field in all_fields if any(field.name in row for row in rows)
        )
        fields = tuple(self._info.field(name) for name in union_names)
        if not fields and len(rows) > 1:
            raise QueryError(
                "multiple DEFAULT VALUES rows cannot be represented in one statement",
                hint="call .batch()",
            )
        values = tuple(
            tuple(row.get(field.name, _DEFAULT) for field in fields) for row in rows
        )
        query = _InsertQuery(self._info, fields, values)
        return render(
            query,
            self._dialect,
            self._limits,
            returning=_returning_names(self._dialect, self._info, self._returning),
            schema=self._info.schema,
        )

    def build(self) -> Sql:
        _, rows = self._rows()
        return self._build_rows(rows)


class InsertBatch(Generic[S]):
    __slots__ = ("_insert",)

    def __init__(self, insert: Insert[S]) -> None:
        self._insert = insert

    def build(self) -> list[Sql]:
        _, rows = self._insert._rows()  # pyright: ignore[reportPrivateUsage]
        statements: list[Sql] = []
        start = 0
        while start < len(rows):
            shape = tuple(rows[start])
            shape_end = start + 1
            if self._insert._dialect.name.startswith("sqlite"):  # pyright: ignore[reportPrivateUsage]
                while shape_end < len(rows) and tuple(rows[shape_end]) == shape:
                    shape_end += 1
            else:
                shape_end = len(rows)

            cursor = start
            while cursor < shape_end:
                # Statement size and parameter counts grow monotonically with rows,
                # so binary search avoids quadratic rendering for large batches.
                best = self._insert._build_rows(  # pyright: ignore[reportPrivateUsage]
                    rows[cursor : cursor + 1]
                )
                best_end = cursor + 1
                low = cursor + 2
                high = shape_end
                while low <= high:
                    candidate_end = (low + high) // 2
                    try:
                        candidate = self._insert._build_rows(  # pyright: ignore[reportPrivateUsage]
                            rows[cursor:candidate_end]
                        )
                    except (QueryTooLong, QueryError):
                        high = candidate_end - 1
                    else:
                        best = candidate
                        best_end = candidate_end
                        low = candidate_end + 1
                statements.append(best)
                cursor = best_end
            start = shape_end
        return statements


class Update(Generic[S]):
    """Shared immutable UPDATE implementation; generated subclasses define set()."""

    __slots__ = (
        "_dialect",
        "_limits",
        "_info",
        "_values",
        "_conds",
        "_returning",
        "_require_where",
    )

    def __init__(
        self,
        dialect: Dialect,
        limits: Limits,
        info: TableInfo,
        require_where: bool = True,
    ) -> None:
        self._dialect = dialect
        self._limits = limits
        self._info = info
        self._values: tuple[tuple[str, object], ...] = ()
        self._conds: tuple[Cond[S], ...] = ()
        self._returning: tuple[Column[Any, S], ...] = ()
        self._require_where = require_where

    def _set_values(self, values: Mapping[str, object]) -> Self:
        merged = dict(self._values)
        merged.update(values)
        return _clone(self, _values=tuple(merged.items()))

    def where(self, *conds: Cond[S]) -> Self:
        return _clone(self, _conds=(*self._conds, *conds))

    def returning(self, *columns: Column[Any, S]) -> Self:
        return _clone(self, _returning=tuple(columns))

    def build(self) -> Sql:
        if not self._values:
            raise QueryError("UPDATE without SET", hint="call .set(...) first")
        if self._require_where and not self._conds:
            raise QueryError(
                "UPDATE without WHERE",
                hint="add .where(...) or use update_all() for every row",
            )
        table = self._info.pypika_table()
        query = Query.update(table)  # pyright: ignore[reportUnknownMemberType]
        operation_values: list[object] = [*self._conds]
        for name, value in self._values:
            field = self._info.field(name)
            if value is GENERATED:
                raise QueryError("GENERATED cannot be assigned in UPDATE")
            if _is_always_identity(field):
                raise QueryError(
                    f"{name!r} is an ALWAYS identity and cannot be updated"
                )
            target = Field(field.column, table=table)
            if isinstance(value, Column):
                # Pyright narrows the unparameterised isinstance result to
                # Column[Unknown, Unknown]; cast makes the Any boundary explicit.
                expression = cast("Column[Any, Any]", value)  # type: ignore[redundant-cast]
                _check_source(self._info, expression)
                operation_values.append(expression)
                query = query.set(target, expression.term)
            else:
                value = serialize_field(
                    field, _validate_update_value(self._info, field, value)
                )
                if value is None:
                    query = query.set(target, Bound(None))
                else:
                    query = query.set(target, Bound(value, json=_is_json_field(field)))
        for cond in self._conds:
            query = query.where(cond.criterion)
        _check_source(self._info, *self._conds)
        _check_operations(self._dialect, *operation_values)
        return render(
            query,
            self._dialect,
            self._limits,
            returning=_returning_names(self._dialect, self._info, self._returning),
            schema=self._info.schema,
        )


class Delete(Generic[S]):
    __slots__ = (
        "_dialect",
        "_limits",
        "_info",
        "_conds",
        "_returning",
        "_require_where",
    )

    def __init__(
        self,
        dialect: Dialect,
        limits: Limits,
        info: TableInfo,
        require_where: bool = True,
    ) -> None:
        self._dialect = dialect
        self._limits = limits
        self._info = info
        self._conds: tuple[Cond[S], ...] = ()
        self._returning: tuple[Column[Any, S], ...] = ()
        self._require_where = require_where

    def where(self, *conds: Cond[S]) -> Self:
        return _clone(self, _conds=(*self._conds, *conds))

    def returning(self, *columns: Column[Any, S]) -> Self:
        return _clone(self, _returning=tuple(columns))

    def build(self) -> Sql:
        if self._require_where and not self._conds:
            raise QueryError(
                "DELETE without WHERE",
                hint="add .where(...) or use delete_all() for every row",
            )
        _check_source(self._info, *self._conds)
        _check_operations(self._dialect, *self._conds)
        query = Query.from_(self._info.pypika_table()).delete()
        for cond in self._conds:
            query = query.where(cond.criterion)
        return render(
            query,
            self._dialect,
            self._limits,
            returning=_returning_names(self._dialect, self._info, self._returning),
            schema=self._info.schema,
        )


def _validate_update_value(
    info: TableInfo, field: SchemaField, value: object
) -> object:
    return validate_field(info.model, field.name, value)


class UpdateFactory(Protocol[U_co]):
    def __pikanaut_update__(
        self, dialect: Dialect, limits: Limits, require_where: bool = True
    ) -> U_co: ...


class Client(Generic[T]):
    __slots__ = ("dialect", "limits")

    def __init__(self, dialect: T, limits: Limits | None = None) -> None:
        self.dialect = dialect
        assert isinstance(dialect, Dialect)
        self.limits = limits if limits is not None else dialect.limits

    @overload
    def select(self, table_or_column: Table[M, S]) -> Select[S]: ...

    @overload
    def select(
        self, table_or_column: Column[Any, S], *columns: Column[Any, S]
    ) -> Select[S]: ...

    def select(self, table_or_column: object, *columns: object) -> Select[Any]:
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        if isinstance(table_or_column, Table):
            if columns:
                raise QueryError("select(table) does not accept additional columns")
            info = table_or_column.__pikanaut_info__
            selected_list: list[Column[Any, Any]] = [
                table_or_column.__pikanaut_column__(field.name) for field in info.fields
            ]
            selected = tuple(selected_list)
            return Select(dialect, self.limits, info, selected)
        selected_objects = (table_or_column, *columns)
        if not all(isinstance(column, Column) for column in selected_objects):
            raise QueryError("select() expects a table or columns")
        selected = cast(tuple[Column[Any, Any], ...], selected_objects)
        dependencies: frozenset[object] = frozenset[object]().union(
            *(column.dependencies for column in selected)
        )
        if len(dependencies) != 1:
            raise QueryError("select columns must have exactly one table source")
        source = next(iter(dependencies))
        if not isinstance(source, TableInfo):
            raise QueryError("select columns do not identify a generated table source")
        return Select(dialect, self.limits, source, selected)

    def insert(self, table: Table[M, S], model: M) -> Insert[S]:
        if not isinstance(model, BaseModel):
            raise QueryError("insert() expects a TableModel instance")
        if type(model) is not table.__pikanaut_info__.model:
            raise QueryError(
                f"model does not match table {table.__pikanaut_info__.name!r}"
            )
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        return Insert(dialect, self.limits, table.__pikanaut_info__, [model])

    def insert_many(self, table: Table[M, S], models: Sequence[M]) -> Insert[S]:
        if any(not isinstance(model, BaseModel) for model in models):
            raise QueryError("insert_many() expects TableModel instances")
        if any(type(model) is not table.__pikanaut_info__.model for model in models):
            raise QueryError(
                f"model does not match table {table.__pikanaut_info__.name!r}"
            )
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        return Insert(dialect, self.limits, table.__pikanaut_info__, models)  # type: ignore[arg-type]

    def update(self, table: UpdateFactory[U]) -> U:
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        return table.__pikanaut_update__(dialect, self.limits, True)

    def update_all(self, table: UpdateFactory[U]) -> U:
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        return table.__pikanaut_update__(dialect, self.limits, False)

    def delete(self, table: Table[M, S]) -> Delete[S]:
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        return Delete(dialect, self.limits, table.__pikanaut_info__)

    def delete_all(self, table: Table[M, S]) -> Delete[S]:
        dialect = self.dialect
        assert isinstance(dialect, Dialect)
        return Delete(
            dialect, self.limits, table.__pikanaut_info__, require_where=False
        )


def client(dialect: T, *, limits: Limits | None = None) -> Client[T]:
    return Client(dialect, limits)
