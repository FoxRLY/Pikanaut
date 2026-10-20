"""03 — условия: NULL, IN, LIKE, AND/OR/NOT.

Запуск: uv run python examples/03_filters.py

Что показывает:
  * `U.age == None` на nullable-колонке превращается в IS NULL, а на NOT NULL — TypeError;
  * IN разворачивается в отдельный плейсхолдер на каждое значение (sqlite) ;
  * (a) & (b) требует скобок — приоритет & выше сравнений, см. комментарий;
  * пустой IN — ошибка, а не «пустое условие».
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, QueryError, client, columns, ddl, or_, table
from pikanaut.dialects import SQLITE

@table("users")
class User(BaseModel):
    id: Annotated[int, Col(pk=True)]
    email: str
    age: int | None = None


def main() -> None:
    db = client(SQLITE)
    U = columns(User)

    # --- NULL: тип колонки решает, что значит == None
    print("IS NULL:     ", db.select(U.id).where(U.age == None).build().sql)  # noqa: E711

    try:
        _ = U.email == None  # noqa: E711  — email NOT NULL, сравнение с NULL бессмысленно
    except TypeError as exc:
        print("NOT NULL == None ->", exc)

    # --- IN: одно значение = один параметр
    in_query = db.select(U.id).where(U.age.in_([18, 25, 40])).build()
    print("IN:          ", in_query.sql, in_query.params)

    try:
        db.select(U.id).where(U.age.in_([])).build()
    except QueryError as exc:
        print("пустой IN ->", exc)

    # --- LIKE и производные
    print("LIKE:        ", db.select(U.id).where(U.email.like("%@corp.com")).build())
    print("contains:    ", db.select(U.id).where(U.email.contains("corp")).build().params)

    # --- композиция: and_/or_/not_ без операторов приоритета
    safe = or_(U.age > 60, U.age < 18)
    print("OR:          ", db.select(U.id).where(safe).build().sql)

    # (U.age > 18) & (U.age < 65) — скобки обязательны:
    # без них Python считает 1 & U.age и падает с TypeError ещё до SQL.
    both = (U.age > 18) & (U.age < 65)
    mixed = (both, U.email.like("%@corp.com"))
    mixed_query = db.select(U.id).where(*mixed).build()
    print("AND + LIKE:  ", mixed_query.sql, mixed_query.params)

    # --- проверяем на настоящих данных
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(User, dialect=SQLITE):
        conn.execute(statement.sql)
    conn.executemany(
        "INSERT INTO users (id, email, age) VALUES (?, ?, ?)",
        [(1, "a@corp.com", 30), (2, "b@corp.com", 70), (3, "c@other.io", None)],
    )
    rows = conn.execute(mixed_query.sql, mixed_query.params).fetchall()
    print("\nrows (18<age<65 и @corp.com):", rows)


if __name__ == "__main__":
    main()
