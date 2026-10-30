"""Shared table models used by the executable examples."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pikanaut import (
    DateTimeColumn,
    Generated,
    Identity,
    IntColumn,
    StrColumn,
    TableModel,
    defaults,
)


class Note(TableModel, table="notes"):
    id: int | Generated = IntColumn(pk=True, server_default=Identity())
    text: str


class User(TableModel, table="users"):
    id: int = IntColumn(pk=True)
    email: str
    age: int | None = None


class PublicUser(TableModel, table="users", schema="public"):
    id: int = IntColumn(pk=True)
    email: str


class Order(TableModel, table="orders"):
    id: int | Generated = IntColumn(pk=True, server_default=Identity())
    customer: str
    amount: int


class Event(TableModel, table="events"):
    id: int | Generated = IntColumn(pk=True, server_default=Identity())
    name: str
    happened_at: datetime


class Purchase(TableModel, table="purchases"):
    id: int | Generated = IntColumn(pk=True, server_default=Identity())
    customer: str = StrColumn(index=True)
    email: str = StrColumn(unique=True)
    amount: Decimal
    created_at: datetime | Generated = DateTimeColumn(server_default=defaults.NOW)
    note: str | None = None
