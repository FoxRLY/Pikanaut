"""Сборка: ``Sql``, биндер и контекст рендера (SPEC.md, разделы 5 и 5.1).

Инвариант: значение из данных никогда не попадает в текст SQL — только в ``params``.
Диалект-зависимые решения (плейсхолдер, адаптация значения, форма IN) принимаются
в момент рендера, поэтому выражения остаются диалект-независимыми.
"""

from __future__ import annotations

from contextvars import ContextVar
from collections.abc import Sequence
from typing import NamedTuple, Protocol, cast
from typing_extensions import LiteralString

from .dialects.base import Dialect, Feature, Limits
from .errors import QueryTooLong, UnsupportedFeature


class Sql(NamedTuple):
    """Результат сборки: текст запроса, параметры, диалект."""

    sql: LiteralString
    params: list[object]
    dialect: Dialect


class Binder:
    """Копит параметры и выдаёт плейсхолдеры диалекта.

    Счётчик проверяется на каждом значении: превышение ``limits.max_params``
    поднимает ``QueryTooLong`` до рендера текста запроса.
    """

    __slots__ = ("dialect", "limits", "params", "_n")

    def __init__(self, dialect: Dialect, limits: Limits | None = None) -> None:
        self.dialect = dialect
        self.limits = limits if limits is not None else dialect.limits
        self.params: list[object] = []
        self._n = 0

    def _take(self, count: int) -> int:
        limit = self.limits.max_params
        if limit is not None and self._n + count > limit:
            engine = self.dialect.engine_max_params
            engine_note = f"; engine max {engine}" if engine else ""
            raise QueryTooLong(
                f"{self.dialect.name}: {self._n + count} placeholders, limit {limit} "
                f"(pikanaut default{engine_note})",
                length=self._n + count,
                limit=limit,
                kind="params",
                dialect=self.dialect.name,
                hint=(
                    "chunk the statement (split insert_many into chunks of rows, or the IN list) "
                    f"or raise the limit with client({self.dialect.name.upper()}, "
                    "limits=Limits(max_params=...))"
                ),
            )
        self._n += count
        return self._n

    def bind(self, value: object) -> str:
        """Значение → params, наружу плейсхолдер (``?`` / ``$1`` / ``%s``)."""
        index = self._take(1)
        self.params.append(self.dialect.adapt(value))
        return self.dialect.placeholder(index)

    def bind_array(self, values: Sequence[object]) -> str:
        """Список значений как один параметр (``= ANY($1)``)."""
        index = self._take(1)
        self.params.append([self.dialect.adapt(v) for v in values])
        return self.dialect.placeholder(index)


class RenderContext:
    """То, что нужно термам во время рендера: диалект и биндер."""

    __slots__ = ("dialect", "binder")

    def __init__(self, dialect: Dialect, binder: Binder) -> None:
        self.dialect = dialect
        self.binder = binder

    def bind(self, value: object) -> str:
        return self.binder.bind(value)

    def require(self, feature: Feature, hint: str = "") -> None:
        if not self.dialect.has(feature):
            raise UnsupportedFeature(self.dialect.name, feature.value, hint)


_current: ContextVar[RenderContext | None] = ContextVar("pikanaut_render", default=None)


def current() -> RenderContext:
    ctx = _current.get()
    if ctx is None:  # pragma: no cover - защита от рендера вне build()
        raise RuntimeError("pikanaut: query rendered outside build()")
    return ctx


class SqlQuery(Protocol):
    """Рендеру нужен только get_sql с явно переданным символом кавычек."""

    def get_sql(self, *, quote_char: str) -> str: ...


def render(
    query: SqlQuery,
    dialect: Dialect,
    limits: Limits,
    *,
    returning: tuple[str, ...] = (),
    schema: str | None = None,
) -> Sql:
    """Отрендерить pypika-запрос с биндингом и проверками лимитов."""
    if schema is not None and not dialect.has(Feature.SCHEMA):
        raise UnsupportedFeature(
            dialect.name,
            "schema",
            "drop @table(schema=...) or use a dialect that supports schemas",
        )

    binder = Binder(dialect, limits)
    token = _current.set(RenderContext(dialect, binder))
    try:
        sql = query.get_sql(quote_char=dialect.quote_char)
    finally:
        _current.reset(token)

    if returning:
        quoted = ",".join(
            f"{dialect.quote_char}{c}{dialect.quote_char}" for c in returning
        )
        sql = f"{sql} RETURNING {quoted}"

    max_bytes = limits.max_sql_bytes
    if max_bytes is not None:
        size = len(sql.encode("utf-8"))
        if size > max_bytes:
            head = sql[:160]
            tail = sql[-60:] if len(sql) > 220 else ""
            preview = f"{head} … {tail}" if tail else head
            raise QueryTooLong(
                f"{dialect.name}: query is {size} bytes, limit {max_bytes} "
                f"(pikanaut default) — SQL: {preview} (truncated)",
                length=size,
                limit=max_bytes,
                kind="sql_bytes",
                dialect=dialect.name,
                hint=(
                    "select fewer columns or raise the limit with "
                    f"client({dialect.name.upper()}, limits=Limits(max_sql_bytes=...))"
                ),
            )

    # Pyright различает LiteralString и str; mypy пока считает cast избыточным.
    return Sql(cast(LiteralString, sql), binder.params, dialect)  # type: ignore[redundant-cast]
