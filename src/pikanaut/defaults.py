"""Typed markers for database-generated values and SQL defaults."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from .errors import SchemaError


class Generated(str, Enum):
    """A value that is pending generation by the database."""

    GENERATED = "GENERATED"

    def __repr__(self) -> str:
        return "GENERATED"


GENERATED = Generated.GENERATED

IdentityMode = Literal["BY_DEFAULT", "ALWAYS"]


@dataclass(frozen=True, slots=True)
class Identity:
    """Database identity descriptor for an integer ``server_default``."""

    generated: IdentityMode = "BY_DEFAULT"

    def __post_init__(self) -> None:
        if self.generated not in ("BY_DEFAULT", "ALWAYS"):
            raise SchemaError(
                "Identity.generated must be 'BY_DEFAULT' or 'ALWAYS', "
                f"got {self.generated!r}"
            )


@dataclass(frozen=True, slots=True)
class ServerDefault:
    """Known SQL expression rendered by the DDL layer."""

    name: str
    dialect: Literal["postgres", "sqlite"] | None = None

    def __repr__(self) -> str:
        prefix = f"{self.dialect}." if self.dialect else ""
        return f"{prefix}{self.name}"


NOW = ServerDefault("NOW")
TODAY = ServerDefault("TODAY")
IDENTITY = Identity()


class _PostgresDefaults:
    __slots__ = ()

    CURRENT_TIMESTAMP = ServerDefault("CURRENT_TIMESTAMP", "postgres")
    CURRENT_DATE = ServerDefault("CURRENT_DATE", "postgres")
    GEN_RANDOM_UUID = ServerDefault("GEN_RANDOM_UUID", "postgres")


class _SQLiteDefaults:
    __slots__ = ()

    CURRENT_TIMESTAMP = ServerDefault("CURRENT_TIMESTAMP", "sqlite")
    CURRENT_DATE = ServerDefault("CURRENT_DATE", "sqlite")


postgres = _PostgresDefaults()
sqlite = _SQLiteDefaults()


def is_server_descriptor(value: object) -> bool:
    """Return whether *value* is reserved for ``server_default``."""

    return isinstance(value, (Identity, ServerDefault))


__all__ = [
    "GENERATED",
    "IDENTITY",
    "NOW",
    "TODAY",
    "Generated",
    "Identity",
    "IdentityMode",
    "ServerDefault",
    "postgres",
    "sqlite",
]
