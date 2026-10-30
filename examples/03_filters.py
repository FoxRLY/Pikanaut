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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.generated.models import User
from examples.generated.tables import users
from pikanaut import QueryError, client, ddl, or_
from pikanaut.dialects import SQLITE


def main() -> None:
    db = client(SQLITE)

    # --- NULL: тип колонки решает, что значит == None
    print(
        "IS NULL:     ",
        db.select(users.id).where(users.age == None).build().sql,  # noqa: E711
    )

    try:
        _ = users.email == None  # noqa: E711
    except TypeError as exc:
        print("NOT NULL == None ->", exc)

    # --- IN: одно значение = один параметр
    in_query = db.select(users.id).where(users.age.in_([18, 25, 40])).build()
    print("IN:          ", in_query.sql, in_query.params)

    try:
        db.select(users.id).where(users.age.in_([])).build()
    except QueryError as exc:
        print("пустой IN ->", exc)

    # --- LIKE и производные
    print(
        "LIKE:        ",
        db.select(users.id).where(users.email.like("%@corp.com")).build(),
    )
    print(
        "contains:    ",
        db.select(users.id).where(users.email.contains("corp")).build().params,
    )

    # --- композиция: and_/or_/not_ без операторов приоритета
    safe = or_(users.age > 60, users.age < 18)
    print("OR:          ", db.select(users.id).where(safe).build().sql)

    # (U.age > 18) & (U.age < 65) — скобки обязательны:
    # без них Python считает 1 & U.age и падает с TypeError ещё до SQL.
    both = (users.age > 18) & (users.age < 65)
    mixed = (both, users.email.like("%@corp.com"))
    mixed_query = db.select(users.id).where(*mixed).build()
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
