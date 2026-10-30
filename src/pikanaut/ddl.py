"""Dialect-safe CREATE/DROP DDL from normalized table metadata."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from typing import cast
from typing_extensions import LiteralString
from uuid import UUID

from .build import Sql
from .defaults import Identity, ServerDefault
from .dialects.base import Dialect, Feature
from .errors import SchemaError, UnsupportedFeature
from .schema import UNSET, Field, M, TableInfo, serialize_field, table_of

MAX_IDENTIFIER = 63

_TYPES: dict[str, tuple[str, str]] = {
    "bool": ("INTEGER", "BOOLEAN"),
    "int": ("INTEGER", "INTEGER"),
    "float": ("REAL", "DOUBLE PRECISION"),
    "str": ("TEXT", "TEXT"),
    "bytes": ("BLOB", "BYTEA"),
    "datetime": ("TEXT", "TIMESTAMPTZ"),
    "date": ("TEXT", "DATE"),
    "time": ("TEXT", "TIME"),
    "uuid": ("TEXT", "UUID"),
    "decimal": ("TEXT", "NUMERIC"),
    "json": ("TEXT", "JSONB"),
}


def create(
    model: type[M], *, dialect: Dialect, if_not_exists: bool = True
) -> list[Sql]:
    info = table_of(model)
    _require_dialect_support(info, dialect)
    _validate_ddl(info, dialect)
    columns = ",".join(_column_sql(item, info, dialect) for item in info.fields)
    constraints = _table_constraints(info, dialect)
    body = f"{columns},{constraints}" if constraints else columns
    prefix = "CREATE TABLE IF NOT EXISTS " if if_not_exists else "CREATE TABLE "
    statements = [
        Sql(_trusted(f"{prefix}{_table_sql(info, dialect)} ({body})"), [], dialect)
    ]
    index_prefix = "CREATE INDEX IF NOT EXISTS " if if_not_exists else "CREATE INDEX "
    for item in info.fields:
        if item.index:
            index = _quote(
                _name("ix", info.name, item.column, dialect=dialect), dialect
            )
            statements.append(
                Sql(
                    _trusted(
                        f"{index_prefix}{index} ON {_table_sql(info, dialect)} "
                        f"({_quote(item.column, dialect)})"
                    ),
                    [],
                    dialect,
                )
            )
    return statements


def drop(model: type[M], *, dialect: Dialect, if_exists: bool = True) -> Sql:
    info = table_of(model)
    _require_dialect_support(info, dialect)
    prefix = "DROP TABLE IF EXISTS " if if_exists else "DROP TABLE "
    return Sql(_trusted(f"{prefix}{_table_sql(info, dialect)}"), [], dialect)


def _family(dialect: Dialect) -> str:
    return "sqlite" if dialect.name.startswith("sqlite") else "postgres"


def _quote(identifier: str, dialect: Dialect) -> str:
    quote = dialect.quote_char
    return f"{quote}{identifier.replace(quote, quote + quote)}{quote}"


def _trusted(sql: str) -> LiteralString:
    return cast(LiteralString, sql)  # type: ignore[redundant-cast]


def _table_sql(info: TableInfo, dialect: Dialect) -> str:
    table = _quote(info.name, dialect)
    return f"{_quote(info.schema, dialect)}.{table}" if info.schema else table


def _require_dialect_support(info: TableInfo, dialect: Dialect) -> None:
    if info.schema and not dialect.has(Feature.SCHEMA):
        raise UnsupportedFeature(
            dialect.name, "schema", "remove schema= or use PostgreSQL"
        )


def _validate_ddl(info: TableInfo, dialect: Dialect) -> None:
    identities = [
        item for item in info.fields if isinstance(item.server_default, Identity)
    ]
    if _family(dialect) == "sqlite" and identities:
        identity = identities[0]
        descriptor = cast(Identity, identity.server_default)
        if descriptor.generated == "ALWAYS":
            raise UnsupportedFeature(dialect.name, "identity ALWAYS")
        primary_keys = [item for item in info.fields if item.pk]
        if len(identities) != 1 or primary_keys != identities:
            raise UnsupportedFeature(
                dialect.name, "identity", "SQLite requires one INTEGER PRIMARY KEY"
            )
    for item in info.fields:
        if (
            _family(dialect) == "sqlite"
            and item.kind == "decimal"
            and any(
                bound is not None
                for bound in (
                    item.constraints.greater_than,
                    item.constraints.greater_than_or_equal,
                    item.constraints.less_than,
                    item.constraints.less_than_or_equal,
                )
            )
        ):
            raise UnsupportedFeature(
                dialect.name,
                "Decimal bounds",
                "SQLite stores Decimal as TEXT and cannot compare it numerically",
            )


def _column_sql(item: Field, info: TableInfo, dialect: Dialect) -> str:
    parts = [_quote(item.column, dialect), _sql_type(item, dialect)]
    identity = isinstance(item.server_default, Identity)
    if _sqlite_inline_identity(item, dialect):
        parts.append("PRIMARY KEY")
    elif not item.nullable and not identity:
        # Identity columns are implicitly NOT NULL in PostgreSQL.
        parts.append("NOT NULL")
    if item.default is not UNSET and item.default is not None:
        parts.append(f"DEFAULT {_constant_default(item, dialect)}")
    if item.server_default is not UNSET and not identity:
        parts.append(f"DEFAULT {_server_default(item.server_default, dialect)}")
    checks = _checks(item, dialect)
    if checks:
        parts.extend(f"CHECK ({check})" for check in checks)
    return " ".join(parts)


def _sql_type(item: Field, dialect: Dialect) -> str:
    if item.sql_type is not None:
        return item.sql_type
    if isinstance(item.server_default, Identity):
        if _family(dialect) == "sqlite":
            return "INTEGER"
        mode = item.server_default.generated.replace("_", " ")
        return f"INTEGER GENERATED {mode} AS IDENTITY"
    if item.kind == "datetime" and item.timezone is False:
        return "TEXT" if _family(dialect) == "sqlite" else "TIMESTAMP WITHOUT TIME ZONE"
    if (
        item.kind == "str"
        and _family(dialect) == "postgres"
        and item.constraints.max_length is not None
    ):
        return f"VARCHAR({item.constraints.max_length})"
    try:
        sqlite_type, postgres_type = _TYPES[item.kind]
    except KeyError as exc:
        raise SchemaError(f"{item.name}: no SQL type for kind {item.kind!r}") from exc
    return sqlite_type if _family(dialect) == "sqlite" else postgres_type


def _sqlite_inline_identity(item: Field, dialect: Dialect) -> bool:
    return _family(dialect) == "sqlite" and isinstance(item.server_default, Identity)


def _checks(item: Field, dialect: Dialect) -> list[str]:
    column = _quote(item.column, dialect)
    result: list[str] = []
    constraints = item.constraints
    for bound, operator_ in (
        (constraints.greater_than, ">"),
        (constraints.greater_than_or_equal, ">="),
        (constraints.less_than, "<"),
        (constraints.less_than_or_equal, "<="),
    ):
        if bound is not None:
            result.append(f"{column} {operator_} {_scalar_literal(bound, dialect)}")
    if constraints.min_length is not None:
        result.append(f"length({column}) >= {constraints.min_length}")
    if constraints.max_length is not None and not (
        item.kind == "str" and _family(dialect) == "postgres"
    ):
        result.append(f"length({column}) <= {constraints.max_length}")
    if item.allowed_values:
        values = ",".join(
            _scalar_literal(value, dialect) for value in item.allowed_values
        )
        result.append(f"{column} IN ({values})")
    if item.kind == "json" and _family(dialect) == "sqlite":
        valid = f"json_valid({column})"
        result.append(f"{column} IS NULL OR {valid}" if item.nullable else valid)
    return result


def _constant_default(item: Field, dialect: Dialect) -> str:
    value = serialize_field(item, item.default)
    if item.kind == "json":
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        literal = _literal(text)
        return literal if _family(dialect) == "sqlite" else f"{literal}::jsonb"
    return _scalar_literal(value, dialect)


def _scalar_literal(value: object, dialect: Dialect) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, bool):
        if _family(dialect) == "sqlite":
            return "1" if value else "0"
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SchemaError("non-finite float cannot be a SQL DEFAULT")
        return repr(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return _literal(str(value))
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(timezone.utc)
        return _literal(value.isoformat())
    if isinstance(value, (date, time)):
        return _literal(value.isoformat())
    if isinstance(value, str):
        return _literal(value)
    if isinstance(value, bytes):
        if _family(dialect) == "sqlite":
            return f"X'{value.hex()}'"
        return f"'\\x{value.hex()}'::bytea"
    raise SchemaError(f"unsupported SQL DEFAULT constant {value!r}")


def _server_default(value: object, dialect: Dialect) -> str:
    if not isinstance(value, ServerDefault):
        raise SchemaError(f"unsupported server_default {value!r}")
    family = _family(dialect)
    if value.dialect is not None and value.dialect != family:
        raise UnsupportedFeature(
            dialect.name, f"{value.dialect} server default {value.name}"
        )
    if value.name == "NOW":
        if family == "sqlite":
            return "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        return "CURRENT_TIMESTAMP"
    if value.name == "TODAY":
        return "CURRENT_DATE"
    if value.name == "CURRENT_TIMESTAMP":
        return "CURRENT_TIMESTAMP"
    if value.name == "CURRENT_DATE":
        return "CURRENT_DATE"
    if value.name == "GEN_RANDOM_UUID" and family == "postgres":
        return "gen_random_uuid()"
    raise UnsupportedFeature(dialect.name, f"server default {value.name}")


def _table_constraints(info: TableInfo, dialect: Dialect) -> str:
    result: list[str] = []
    primary_keys = [item for item in info.fields if item.pk]
    inline = len(primary_keys) == 1 and _sqlite_inline_identity(
        primary_keys[0], dialect
    )
    if primary_keys and not inline:
        columns = ",".join(_quote(item.column, dialect) for item in primary_keys)
        result.append(
            f"CONSTRAINT {_quote(_name('pk', info.name, dialect=dialect), dialect)} "
            f"PRIMARY KEY ({columns})"
        )
    for item in info.fields:
        if item.unique:
            result.append(
                f"CONSTRAINT {_quote(_name('uq', info.name, item.column, dialect=dialect), dialect)} "
                f"UNIQUE ({_quote(item.column, dialect)})"
            )
    return ",".join(result)


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _name(prefix: str, *parts: str, dialect: Dialect) -> str:
    name = "_".join((prefix, *parts))
    if _family(dialect) == "postgres" and len(name) > MAX_IDENTIFIER:
        raise SchemaError(
            f"generated identifier {name!r} exceeds PostgreSQL's {MAX_IDENTIFIER}-character identifier limit"
        )
    return name
