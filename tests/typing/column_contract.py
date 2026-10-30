"""Типы динамических колонок не должны стирать типы условий и моделей."""

from __future__ import annotations

from datetime import datetime, timezone
from typing_extensions import assert_type

from pikanaut import Column, Cond, client
from pikanaut.dialects import SQLITE
from pikanaut.expr import Order
from tests.generated import UsersSource, users
from tests.generated.public import users as public_users
from tests.models import User


def expression_contract() -> None:
    user = User(
        id=1,
        email="a@b.io",
        full_name="Ann",
        password_hash="x",
        created_at=datetime.now(timezone.utc),
    )
    assert_type(user, User)
    assert_type(users.id, Column[int, UsersSource])
    assert_type(users.age, Column[int | None, UsersSource])
    assert_type(users.id == 1, Cond[UsersSource])
    assert_type(users.id.asc(), Order[UsersSource])

    # Оба чека: и mypy (`list-item`/`operator`), и pyright.
    users.id.in_(["wrong"])  # type: ignore[list-item]  # pyright: ignore[reportArgumentType]
    users.id + "wrong"  # type: ignore[operator]  # pyright: ignore[reportOperatorIssue]
    users.email.in_([1])  # type: ignore[list-item]  # pyright: ignore[reportArgumentType]

    # `==`/`!=` c колонкой другого типа, другой nullable-формы или другого источника
    # отклоняются: оба чекера вызывают `__eq__` с обеих сторон и обе стороны не
    # принимают операнд. Скалярные литералы не отклоняются (SPEC.md §10).
    users.id == users.email  # type: ignore[operator]  # pyright: ignore[reportOperatorIssue]
    users.id != users.email  # type: ignore[operator]  # pyright: ignore[reportOperatorIssue]
    users.age == users.id  # type: ignore[operator]  # pyright: ignore[reportOperatorIssue]
    users.id == public_users.id  # type: ignore[operator]  # pyright: ignore[reportOperatorIssue]


def source_contract() -> None:
    db = client(SQLITE)
    # Другая таблица (даже с тем же именем источника в другом пакете) не проходит.
    db.select(users.id).where(public_users.id == 1)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    db.select(users.id, public_users.id)  # type: ignore[misc]  # pyright: ignore[reportArgumentType]
