"""05 — один запрос, два диалекта.

Запуск: uv run python examples/05_dialects.py

Что показывает:
  * диалект — это тип: client(SQLITE) даёт Client[SQLite], client(POSTGRES) — Client[Postgres];
  * плейсхолдеры и IN меняются вместе с диалектом (? → $1, IN (?,?,?) → = ANY($1));
  * схема поддерживается только там, где она есть в движке — и это видно на build();
  * кнопки, которых у диалекта нет, отсутствуют на классе запроса, поэтому линтер
    ругается на строке вызова ещё до запуска.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, UnsupportedFeature, client, columns, table
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34


@table("users", schema="public")
class PublicUser(BaseModel):
    id: Annotated[int, Col(pk=True)]
    email: str


@table("users")
class User(BaseModel):
    id: Annotated[int, Col(pk=True)]
    email: str
    age: int | None = None


def main() -> None:
    U = columns(User)

    # --- SQLite
    sqlite_db = client(SQLITE)               # Client[SQLite]
    print("sqlite:  ", sqlite_db.select(U.id, U.email).where(U.age.in_([18, 25])).build())
    # INSERT ... RETURNING есть с 3.35
    print("         ", sqlite_db.insert(User(id=1, email="a@b.io")).returning(U.id).build().sql)

    # --- Postgres
    pg = client(POSTGRES)                    # Client[Postgres]
    pg_query = pg.select(U.id, U.email).where(U.age.in_([18, 25])).build()
    print("postgres:", pg_query.sql)
    print("          params =", pg_query.params, " <- список ушёл одним параметром")

    # --- схема: postgres умеет, sqlite — нет
    P = columns(PublicUser)
    print("\nschema в postgres:", client(POSTGRES).select(P.id).build().sql)
    try:
        client(SQLITE).select(P.id).build()
    except UnsupportedFeature as exc:
        print("schema в sqlite:  ", exc)

    # --- версия sqlite — тоже тип
    old = client(SQLITE_34)
    print("\nбез RETURNING:", old.insert(User(id=1, email="x")).build().sql)
    #
    # А вот так уже не скомпилируется — и это цель всей конструкции:
    #
    #     old.insert(User(id=1, email="x")).returning(U.id)
    #     ^ mypy/pyright: "SQLite34Insert" has no attribute "returning"
    #


if __name__ == "__main__":
    main()
