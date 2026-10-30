"""05 — один запрос, два диалекта.

Запуск: uv run python examples/05_dialects.py

Что показывает:
  * диалект — это тип: client(SQLITE) даёт Client[SQLite], client(POSTGRES) — Client[Postgres];
  * плейсхолдеры и IN меняются вместе с диалектом (? → $1, IN (?,?,?) → = ANY($1));
  * схема поддерживается только там, где она есть в движке — и это видно на build();
  * RETURNING объявлен у всех builder'ов, но на SQLite 3.34 проверяется при build()
    и даёт UnsupportedFeature, а не тихую подмену.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.generated.models import User
from examples.generated.tables import users
from examples.generated.tables.public import users as public_users
from pikanaut import UnsupportedFeature, client
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34


def main() -> None:
    # --- SQLite
    sqlite_db = client(SQLITE)  # Client[SQLite]
    print(
        "sqlite:  ",
        sqlite_db.select(users.id, users.email).where(users.age.in_([18, 25])).build(),
    )
    # INSERT ... RETURNING есть с 3.35
    print(
        "         ",
        sqlite_db.insert(users, User(id=1, email="a@b.io"))
        .returning(users.id)
        .build()
        .sql,
    )

    # --- Postgres
    pg = client(POSTGRES)  # Client[Postgres]
    pg_query = pg.select(users.id, users.email).where(users.age.in_([18, 25])).build()
    print("postgres:", pg_query.sql)
    print("          params =", pg_query.params, " <- список ушёл одним параметром")

    # --- схема: postgres умеет, sqlite — нет
    print("\nschema в postgres:", client(POSTGRES).select(public_users.id).build().sql)
    try:
        client(SQLITE).select(public_users.id).build()
    except UnsupportedFeature as exc:
        print("schema в sqlite:  ", exc)

    # --- версия sqlite — тоже тип; DELETE на 3.34 работает без RETURNING
    old = client(SQLITE_34)
    print("\nбез RETURNING:", old.insert(users, User(id=1, email="x")).build().sql)
    try:
        old.insert(users, User(id=1, email="x")).returning(users.id).build()
    except UnsupportedFeature as exc:
        print("RETURNING на 3.34:", exc)


if __name__ == "__main__":
    main()
