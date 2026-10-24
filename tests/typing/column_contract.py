"""Типы динамических колонок не должны стирать типы условий и моделей."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from typing_extensions import assert_type

from pikanaut import Column, Cond, columns
from pikanaut.expr import Order
from tests.models import User


def expression_contract() -> None:
    user = User(
        id=1,
        email="a@b.io",
        full_name="Ann",
        password_hash="x",
        created_at=datetime.now(),
    )
    assert_type(user, User)
    # Тип значения поля динамический; сама колонка и её методы известны.
    assert_type(columns(User).id, Column[Any])
    assert_type(columns(User).__iter__(), Iterator[Column[Any]])
    assert_type(columns(User).id == 1, Cond)
    assert_type(columns(User).id.asc(), Order)
