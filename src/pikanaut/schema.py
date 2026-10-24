"""Схема модели: Annotated-метки, декоратор @table, извлечение полей.

Всё, что здесь происходит, работает на этапе импорта модуля с моделью (SPEC.md, раздел 2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast, get_args
from typing_extensions import LiteralString

if TYPE_CHECKING:
    from .expr import Column

from pydantic import BaseModel
from pypika import Table

from .errors import SchemaError

M = TypeVar("M")


class _Unset:
    """Отсутствие дефолта (отличать от `default=None`)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


class Col:
    """Метка колонки: имя, ключ, уникальность, индекс, SQL-тип, DEFAULT.

    ``type`` — доверенный SQL-фрагмент, заданный разработчиком модели.
    """

    __slots__ = ("name", "pk", "unique", "index", "default", "sql_type")
    sql_type: LiteralString | None

    def __init__(
        self,
        name: str | None = None,
        *,
        pk: bool = False,
        unique: bool = False,
        index: bool = False,
        default: object = UNSET,
        type: LiteralString | None = None,
    ) -> None:
        self.name = name
        self.pk = pk
        self.unique = unique
        self.index = index
        self.default = default
        self.sql_type = type

    def __repr__(self) -> str:
        parts: list[str] = []
        if self.name is not None:
            parts.append(repr(self.name))
        if self.pk:
            parts.append("pk=True")
        if self.unique:
            parts.append("unique=True")
        if self.index:
            parts.append("index=True")
        if self.default is not UNSET:
            parts.append(f"default={self.default!r}")
        if self.sql_type is not None:
            parts.append(f"type={self.sql_type!r}")
        return f"Col({', '.join(parts)})"


class _Skip:
    """Метка «поле не является колонкой»."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "Skip"


Skip = _Skip()


@dataclass(frozen=True, slots=True)
class Field:
    """Одна колонка таблицы, выведенная из поля модели."""

    name: str  # имя поля в модели
    column: str  # имя колонки в БД
    annotation: object  # тип поля (уже разрешённый)
    required: bool  # поле обязательно при вставке
    nullable: bool  # колонка допускает NULL
    pk: bool
    unique: bool
    index: bool = False
    default: object = UNSET
    sql_type: LiteralString | None = None


@dataclass(frozen=True, slots=True)
class TableInfo:
    """Таблица, выведенная из модели."""

    model: type[BaseModel]
    name: str
    schema: str | None = None
    fields: tuple[Field, ...] = ()

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(f.column for f in self.fields)

    def field(self, model_field: str) -> Field:
        for f in self.fields:
            if f.name == model_field:
                return f
        raise SchemaError(
            f"{self.model.__name__}: field {model_field!r} is not a column"
        )

    def pypika_table(self) -> Table:
        """Таблица pypika; одна и та же на всю модель, чтобы ссылки были идентичны."""
        return _pypika_table(self.name, self.schema)


@cache
def _pypika_table(name: str, schema: str | None) -> Table:
    return Table(name, schema=schema)


def _typed_model_cache(
    function: Callable[[type[object]], TableInfo],
) -> Callable[[type[object]], TableInfo]:
    """Keep the typed model signature when wrapping it in ``cache``.

    Runtime class objects are hashable, but mypy does not infer that from
    ``type[object]`` when it sees the stdlib cache wrapper.
    """
    return cast(Callable[[type[object]], TableInfo], cache(function))


T = TypeVar("T", bound=BaseModel)


def table(name: str, *, schema: str | None = None) -> Callable[[type[T]], type[T]]:
    """Декоратор модели: задаёт имя таблицы и схему, возвращает тот же класс."""

    def decorate(cls: type) -> type:
        if not issubclass(cls, BaseModel):
            raise SchemaError(f"{cls.__name__}: @table ожидает pydantic.BaseModel")
        setattr(cls, "__pikanaut_table__", (name, schema))
        table_of(cls)  # схема проверяется на импорте, а не на первом запросе
        return cls

    return decorate


def _is_optional(annotation: object) -> bool:
    return type(None) in get_args(annotation)


def _contains_typevar(annotation: object) -> bool:
    if isinstance(annotation, TypeVar):
        return True
    return any(_contains_typevar(arg) for arg in get_args(annotation))


@_typed_model_cache
def table_of(model: type[object]) -> TableInfo:
    """Схема модели (кэшируется по классу)."""

    declared = getattr(model, "__pikanaut_table__", None)
    if declared is None:
        raise SchemaError(
            f'{model.__name__}: not a table — decorate the model with @table("...")'
        )
    if not issubclass(model, BaseModel):
        raise SchemaError(f"{model.__name__}: only pydantic.BaseModel is supported")

    name, schema = declared
    fields: list[Field] = []
    seen: dict[str, str] = {}

    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        if _contains_typevar(annotation):
            raise SchemaError(
                f"{model.__name__}.{field_name}: TypeVar in annotation — generic models "
                "are not supported, declare a concrete model"
            )

        col: Col | None = None
        skipped = False
        for meta in field_info.metadata:
            if isinstance(meta, Col):
                col = meta
            elif isinstance(meta, _Skip):
                skipped = True
            else:
                raise SchemaError(
                    f"{model.__name__}.{field_name}: unknown Annotated metadata {meta!r} — "
                    "pikanaut understands Col(...) and Skip"
                )
        if skipped:
            continue

        column = col.name if col is not None and col.name is not None else field_name
        if column in seen:
            raise SchemaError(
                f"{model.__name__}: duplicate column {column!r} "
                f"(fields {seen[column]!r} and {field_name!r})"
            )
        seen[column] = field_name

        fields.append(
            Field(
                name=field_name,
                column=column,
                annotation=annotation,
                required=field_info.is_required(),
                nullable=_is_optional(annotation),
                pk=bool(col and col.pk),
                unique=bool(col and col.unique),
                index=bool(col and col.index),
                default=col.default if col is not None else UNSET,
                sql_type=col.sql_type if col is not None else None,
            )
        )

    if not fields:
        raise SchemaError(f"{model.__name__}: no columns — every field is Skip")

    return TableInfo(model=model, name=name, schema=schema, fields=tuple(fields))


class Columns(Generic[M]):
    """Пространство колонок модели: U.age, U.id, ... От диалекта не зависит."""

    __slots__ = ("model", "info", "_cache")

    def __init__(self, model: type[M]) -> None:
        self.model = model
        self.info = table_of(model)
        self._cache: dict[str, Column[Any]] = {}

    def field(self, name: str) -> Field:
        return self.info.field(name)

    def __getattr__(self, name: str) -> Column[Any]:
        # Имена и типы полей динамические, но объект колонки имеет известный API.
        cache: dict[str, Column[Any]] = object.__getattribute__(self, "_cache")
        if name in cache:
            return cache[name]
        info: TableInfo = object.__getattribute__(self, "info")
        try:
            field = info.field(name)
        except SchemaError as exc:
            raise AttributeError(name) from exc

        from .expr import Column

        column: Column[Any] = Column(
            field.column, table=info.pypika_table(), nullable=field.nullable
        )
        cache[name] = column
        return column

    def __iter__(self) -> Iterator[Column[Any]]:
        for field in self.info.fields:
            yield getattr(self, field.name)

    def __repr__(self) -> str:
        return f"Columns({self.model.__name__})"


@cache
def columns(model: type[M]) -> Columns[M]:
    """Получить колонки модели для запросов."""

    return Columns(model)
