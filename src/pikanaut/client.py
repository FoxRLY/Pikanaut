"""Клиент и запросы: SELECT / INSERT / UPDATE / DELETE (SPEC.md, раздел 6).

Диалект — тип клиента: ``client(SQLITE)`` возвращает клиент, чьи методы создают
классы запросов именно этого диалекта. Там, где возможность диалекта не выражается
отсутствием метода (схема, ``ILIKE``), проверка происходит при ``build()`` и
поднимает ``UnsupportedFeature``.
"""

from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar, overload

from typing_extensions import Self

from pydantic import BaseModel
from pypika import Query, Table
from pypika.terms import Field

from .build import Sql, render
from .dialects.base import Limits
from .dialects.postgres import Postgres, PostgresPsycopg
from .dialects.sqlite import SQLite, SQLite34
from .errors import QueryError, UnsupportedFeature
from .expr import Bound, Column, Cond, Order
from .schema import Columns, M, TableInfo, table_of

D = TypeVar("D")
T = TypeVar("T")


def _table_of_columns(cols: tuple[Any, ...]) -> Table | None:
    for col in cols:
        if isinstance(col, Column):
            table = col.table if col.table is not None else getattr(col.term, "table", None)
            if isinstance(table, Table):
                return table
    return None


class Select(Generic[D, T]):
    """SELECT. Параметры: диалект и форма строки."""

    __slots__ = ("_dialect", "_limits", "_table", "_schema", "_q", "_returning")

    def __init__(self, dialect: D, limits: Limits, cols: tuple[Any, ...]) -> None:
        self._dialect: Any = dialect
        self._limits = limits
        self._returning: tuple[str, ...] = ()

        model = next(
            (c for c in cols if isinstance(c, type) and issubclass(c, BaseModel)), None
        )
        if model is not None:
            info = table_of(model)
            table, self._schema = info.pypika_table(), info.schema
            self._q = Query.from_(table).select(
                *[Column(f.column, table=table, nullable=f.nullable).term for f in info.fields]
            )
        else:
            found = _table_of_columns(cols)
            if found is None:
                raise QueryError("select() requires columns or a model")
            table = found
            self._schema = getattr(table, "_schema", None)
            self._q = Query.from_(table).select(*[c.term for c in cols])
        self._table = table

    def where(self, *conds: Cond) -> Self:
        for cond in conds:
            self._q = self._q.where(_criterion(cond))
        return self

    def order_by(self, *cols: Any) -> Self:
        for col in cols:
            if isinstance(col, Order):
                self._q = self._q.orderby(col.term, order=Order.direction(col.ascending))
            else:
                self._q = self._q.orderby(_term(col))
        return self

    def group_by(self, *cols: Any) -> Self:
        for col in cols:
            self._q = self._q.groupby(_term(col))
        return self

    def having(self, *conds: Cond) -> Self:
        for cond in conds:
            self._q = self._q.having(_criterion(cond))
        return self

    def limit(self, n: int) -> Self:
        self._q = self._q.limit(n)
        return self

    def offset(self, n: int) -> Self:
        self._q = self._q.offset(n)
        return self

    def build(self) -> Sql:
        query = self._q
        if self._dialect.name.startswith("sqlite") and _offset_without_limit(query):
            query = query.limit(-1)
        return render(
            query, self._dialect, self._limits, returning=self._returning, schema=self._schema
        )


class _ReturningMixin:
    """Возможность RETURNING есть не у всех версий диалекта."""

    def returning(self, *cols: Any) -> Self:
        self._returning = tuple(_column_name(c) for c in cols)
        return self


class Insert(Generic[D]):
    __slots__ = ("_dialect", "_limits", "_info", "_rows", "_returning")

    def __init__(self, dialect: D, limits: Limits, info: TableInfo, rows: list[dict[str, Any]]) -> None:
        self._dialect: Any = dialect
        self._limits = limits
        self._info = info
        self._rows = rows
        self._returning: tuple[str, ...] = ()

    def build(self) -> Sql:
        if not self._rows:
            raise QueryError("nothing to insert", hint="pass at least one model instance")
        first = tuple(self._rows[0])
        for index, row in enumerate(self._rows):
            if tuple(row) != first:
                raise QueryError(
                    f"insert_many rows have different shape: row 0 has {first}, "
                    f"row {index} has {tuple(row)}",
                    hint="all rows must set the same fields",
                )
        table = self._info.pypika_table()
        query = Query.into(table).columns(*first)
        for row in self._rows:
            query = query.insert(*[Bound(row[name]) for name in first])
        return render(
            query,
            self._dialect,
            self._limits,
            returning=self._returning,
            schema=self._info.schema,
        )


class Update(Generic[D]):
    __slots__ = ("_dialect", "_limits", "_info", "_values", "_conds", "_returning", "_require_where")

    def __init__(
        self, dialect: D, limits: Limits, info: TableInfo, require_where: bool = True
    ) -> None:
        self._dialect: Any = dialect
        self._limits = limits
        self._info = info
        self._values: dict[str, Any] = {}
        self._conds: list[Cond] = []
        self._returning: tuple[str, ...] = ()
        self._require_where = require_where

    def set(self, **values: Any) -> Self:
        for name, value in values.items():
            self._info.field(name)          # SchemaError, если поля нет
            self._values[name] = value
        return self

    def where(self, *conds: Cond) -> Self:
        self._conds.extend(conds)
        return self

    def build(self) -> Sql:
        if not self._values:
            raise QueryError("UPDATE without SET", hint="call .set(...) with at least one field")
        if self._require_where and not self._conds:
            raise QueryError(
                "UPDATE without WHERE",
                hint="add .where(...) or use update_all() for every row",
            )
        table = self._info.pypika_table()
        query = Query.update(table)  # pyright: ignore[reportUnknownMemberType]
        for name, value in self._values.items():
            field = Field(self._info.field(name).column, table=table)
            query = query.set(field, Bound(value))
        for cond in self._conds:
            query = query.where(_criterion(cond))
        return render(
            query,
            self._dialect,
            self._limits,
            returning=self._returning,
            schema=self._info.schema,
        )


class Delete(Generic[D]):
    __slots__ = ("_dialect", "_limits", "_info", "_conds", "_returning", "_require_where")

    def __init__(
        self, dialect: D, limits: Limits, info: TableInfo, require_where: bool = True
    ) -> None:
        self._dialect: Any = dialect
        self._limits = limits
        self._info = info
        self._conds: list[Cond] = []
        self._returning: tuple[str, ...] = ()
        self._require_where = require_where

    def where(self, *conds: Cond) -> Self:
        self._conds.extend(conds)
        return self

    def build(self) -> Sql:
        if self._require_where and not self._conds:
            raise QueryError(
                "DELETE without WHERE",
                hint="add .where(...) or use delete_all() for every row",
            )
        table = self._info.pypika_table()
        query = Query.from_(table).delete()
        for cond in self._conds:
            query = query.where(_criterion(cond))
        return render(
            query,
            self._dialect,
            self._limits,
            returning=self._returning,
            schema=self._info.schema,
        )


def _criterion(cond: Any) -> Any:
    if not isinstance(cond, Cond):
        raise QueryError(f"expected Cond, got {type(cond).__name__}")
    return cond.criterion


def _term(col: Any) -> Any:
    if isinstance(col, Column):
        return col.term
    raise QueryError(f"expected a column, got {type(col).__name__}")


def _column_name(col: Any) -> str:
    if isinstance(col, Column):
        return col.name
    raise QueryError(f"RETURNING expects columns, got {type(col).__name__}")


def _offset_without_limit(query: Any) -> bool:
    return bool(getattr(query, "_offset", None)) and not getattr(query, "_limit", None)


# --- поверхности диалектов -------------------------------------------------
# Методы, которых нет на классе, ловятся линтером до запуска (test_returning_absent_before_335).


class SQLiteSelect(_ReturningMixin, Select[SQLite, T], Generic[T]): ...


class SQLite34Select(Select[SQLite34, T], Generic[T]): ...


class PostgresSelect(_ReturningMixin, Select[Postgres, T], Generic[T]): ...


class SQLiteInsert(_ReturningMixin, Insert[SQLite]): ...


class SQLite34Insert(Insert[SQLite34]): ...


class PostgresInsert(_ReturningMixin, Insert[Postgres]): ...


class SQLiteUpdate(_ReturningMixin, Update[SQLite]): ...


class SQLite34Update(Update[SQLite34]): ...


class PostgresUpdate(_ReturningMixin, Update[Postgres]): ...


class SQLiteDelete(_ReturningMixin, Delete[SQLite]): ...


class SQLite34Delete(Delete[SQLite34]): ...


class PostgresDelete(_ReturningMixin, Delete[Postgres]): ...


class _Surface:
    __slots__ = ("select", "insert", "update", "delete")

    def __init__(self, select: Any, insert: Any, update: Any, delete: Any) -> None:
        self.select = select
        self.insert = insert
        self.update = update
        self.delete = delete


_SURFACES: dict[type, _Surface] = {
    SQLite: _Surface(SQLiteSelect, SQLiteInsert, SQLiteUpdate, SQLiteDelete),
    SQLite34: _Surface(SQLite34Select, SQLite34Insert, SQLite34Update, SQLite34Delete),
    Postgres: _Surface(PostgresSelect, PostgresInsert, PostgresUpdate, PostgresDelete),
}


def _surface(dialect: Any) -> _Surface:
    for cls, surface in _SURFACES.items():
        if isinstance(dialect, cls):
            return surface
    raise UnsupportedFeature(str(getattr(dialect, "name", dialect)), "dialect", "no renderer")


class Client(Generic[D]):
    """Фабрика запросов для одного диалекта.

    Перегрузки по ``self`` связывают диалект с классами запросов: ``client(SQLITE_34)``
    возвращает клиент, у запросов которого нет ``returning`` — линтер покажет это
    на строке вызова, а не в рантайме.
    """

    __slots__ = ("dialect", "limits")

    def __init__(self, dialect: D, limits: Limits | None = None) -> None:
        self.dialect = dialect
        self.limits = limits if limits is not None else getattr(dialect, "limits", Limits())

    @overload
    def select(self: Client[SQLite], *cols: Any) -> SQLiteSelect[Any]: ...
    @overload
    def select(self: Client[SQLite34], *cols: Any) -> SQLite34Select[Any]: ...
    @overload
    def select(self: Client[Postgres], *cols: Any) -> PostgresSelect[Any]: ...
    @overload
    def select(self: Client[PostgresPsycopg], *cols: Any) -> PostgresSelect[Any]: ...
    @overload
    def select(self, *cols: Any) -> Select[D, Any]: ...
    def select(self, *cols: Any) -> Any:
        if not cols:
            raise QueryError("select() requires columns or a model")
        return _surface(self.dialect).select(self.dialect, self.limits, cols)

    @overload
    def insert(self: Client[SQLite], row: BaseModel) -> SQLiteInsert: ...
    @overload
    def insert(self: Client[SQLite34], row: BaseModel) -> SQLite34Insert: ...
    @overload
    def insert(self: Client[Postgres], row: BaseModel) -> PostgresInsert: ...
    @overload
    def insert(self: Client[PostgresPsycopg], row: BaseModel) -> PostgresInsert: ...
    @overload
    def insert(self, row: BaseModel) -> Insert[D]: ...
    def insert(self, row: BaseModel) -> Any:
        return self._insert([row])

    @overload
    def insert_many(self: Client[SQLite], rows: Sequence[BaseModel]) -> SQLiteInsert: ...
    @overload
    def insert_many(self: Client[SQLite34], rows: Sequence[BaseModel]) -> SQLite34Insert: ...
    @overload
    def insert_many(self: Client[Postgres], rows: Sequence[BaseModel]) -> PostgresInsert: ...
    @overload
    def insert_many(self: Client[PostgresPsycopg], rows: Sequence[BaseModel]) -> PostgresInsert: ...
    @overload
    def insert_many(self, rows: Sequence[BaseModel]) -> Insert[D]: ...
    def insert_many(self, rows: Sequence[BaseModel]) -> Any:
        return self._insert(rows)

    def _insert(self, rows: Sequence[BaseModel]) -> Any:
        if not rows:
            raise QueryError("nothing to insert", hint="pass at least one model instance")
        info = table_of(type(rows[0]))
        return _surface(self.dialect).insert(
            self.dialect, self.limits, info, [_row_values(info, row) for row in rows]
        )

    @overload
    def update(self: Client[SQLite], model: type[Any]) -> SQLiteUpdate: ...
    @overload
    def update(self: Client[SQLite34], model: type[Any]) -> SQLite34Update: ...
    @overload
    def update(self: Client[Postgres], model: type[Any]) -> PostgresUpdate: ...
    @overload
    def update(self: Client[PostgresPsycopg], model: type[Any]) -> PostgresUpdate: ...
    @overload
    def update(self, model: type[Any]) -> Update[D]: ...
    def update(self, model: type[M]) -> Any:
        return _surface(self.dialect).update(self.dialect, self.limits, table_of(model))

    @overload
    def update_all(self: Client[SQLite], model: type[Any]) -> SQLiteUpdate: ...
    @overload
    def update_all(self: Client[SQLite34], model: type[Any]) -> SQLite34Update: ...
    @overload
    def update_all(self: Client[Postgres], model: type[Any]) -> PostgresUpdate: ...
    @overload
    def update_all(self: Client[PostgresPsycopg], model: type[Any]) -> PostgresUpdate: ...
    @overload
    def update_all(self, model: type[Any]) -> Update[D]: ...
    def update_all(self, model: type[M]) -> Any:
        return _surface(self.dialect).update(
            self.dialect, self.limits, table_of(model), require_where=False
        )

    @overload
    def delete(self: Client[SQLite], model: type[Any]) -> SQLiteDelete: ...
    @overload
    def delete(self: Client[SQLite34], model: type[Any]) -> SQLite34Delete: ...
    @overload
    def delete(self: Client[Postgres], model: type[Any]) -> PostgresDelete: ...
    @overload
    def delete(self: Client[PostgresPsycopg], model: type[Any]) -> PostgresDelete: ...
    @overload
    def delete(self, model: type[Any]) -> Delete[D]: ...
    def delete(self, model: type[M]) -> Any:
        return _surface(self.dialect).delete(self.dialect, self.limits, table_of(model))

    @overload
    def delete_all(self: Client[SQLite], model: type[Any]) -> SQLiteDelete: ...
    @overload
    def delete_all(self: Client[SQLite34], model: type[Any]) -> SQLite34Delete: ...
    @overload
    def delete_all(self: Client[Postgres], model: type[Any]) -> PostgresDelete: ...
    @overload
    def delete_all(self: Client[PostgresPsycopg], model: type[Any]) -> PostgresDelete: ...
    @overload
    def delete_all(self, model: type[Any]) -> Delete[D]: ...
    def delete_all(self, model: type[M]) -> Any:
        return _surface(self.dialect).delete(
            self.dialect, self.limits, table_of(model), require_where=False
        )

    def columns(self, model: type[M]) -> Columns[M]:
        return Columns(model)


def _row_values(info: TableInfo, row: BaseModel) -> dict[str, Any]:
    provided = row.model_fields_set
    values: dict[str, Any] = {}
    for field in info.fields:
        if field.name in provided:
            values[field.column] = getattr(row, field.name)
    return values


def client(dialect: D, *, limits: Limits | None = None) -> Client[D]:
    """Клиент для диалекта. ``limits`` переопределяет дефолты pikanaut для этого клиента."""
    return Client(dialect, limits)
