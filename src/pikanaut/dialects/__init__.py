"""Диалекты: импортируются явно, чтобы диалект был виден в типах."""

from __future__ import annotations

from .base import Dialect, Feature, Limits
from .postgres import POSTGRES, POSTGRES_PSYCOPG, Postgres, PostgresPsycopg
from .sqlite import SQLITE, SQLITE_34, SQLite, SQLite34

__all__ = [
    "POSTGRES",
    "POSTGRES_PSYCOPG",
    "SQLITE",
    "SQLITE_34",
    "Dialect",
    "Feature",
    "Limits",
    "Postgres",
    "PostgresPsycopg",
    "SQLite",
    "SQLite34",
]
