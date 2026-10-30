"""Модели для тестов. Лежат отдельно, чтобы их мог импортировать и mypy."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import PrivateAttr, computed_field

from pikanaut import Generated, Identity, IntColumn, StrColumn, TableModel


class User(TableModel, table="users"):
    id: int = IntColumn(pk=True)
    email: str = StrColumn(name="user_email", unique=True)
    full_name: str
    password_hash: str
    age: int | None = None
    created_at: datetime

    _cache: dict[str, str] = PrivateAttr(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return self.full_name.split()[0]


class Note(TableModel, table="notes"):
    """PK генерируется базой и остаётся NOT NULL в схеме."""

    id: int | Generated = IntColumn(pk=True, server_default=Identity())
    text: str


class PublicUser(TableModel, table="users", schema="public"):
    id: int = IntColumn(pk=True)
    email: str


class Event(TableModel, table="events"):
    """Все типы, для которых нужен адаптер диалекта."""

    id: int = IntColumn(pk=True)
    is_active: bool
    at: datetime
    amount: Decimal
    uid: UUID


class Product(TableModel, table="products"):
    id: int = IntColumn(pk=True)
    name: str
    description: str
