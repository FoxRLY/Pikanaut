"""Модели для тестов. Лежат отдельно, чтобы их мог импортировать и mypy."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, PrivateAttr, computed_field

from pikanaut import Col, Skip, table


@table("users")
class User(BaseModel):
    id: Annotated[int, Col(pk=True)]
    email: Annotated[str, Col("user_email", unique=True)]
    full_name: str
    password_hash: Annotated[str, Skip]
    age: int | None = None
    created_at: datetime

    _cache: dict[str, str] = PrivateAttr(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return self.full_name.split()[0]


@table("notes")
class Note(BaseModel):
    """PK генерируется базой, поэтому необязателен и null-able."""

    id: Annotated[int | None, Col(pk=True)] = None
    text: str


@table("users", schema="public")
class PublicUser(BaseModel):
    id: Annotated[int, Col(pk=True)]
    email: str


@table("events")
class Event(BaseModel):
    """Все типы, для которых нужен адаптер диалекта."""

    id: Annotated[int, Col(pk=True)]
    is_active: bool
    at: datetime
    amount: Decimal
    uid: UUID
