"""06 — лимиты: ошибка при сборке, а не при выполнении.

Запуск: uv run python examples/06_limits.py

Зачем: у баз есть предел на число параметров и на длину текста запроса.
Если узнать об этом от драйвера — запрос уже улетел (а у MySQL ещё и соединение закроется).
Поэтому pikanaut проверяет лимиты при build():

  * параметры — на каждом значении, ещё до рендера строки;
  * длина текста — сразу после рендера, в байтах UTF-8.

Дефолты политические (10 000 параметров, 1 МБ), их можно поднять или снять.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, QueryTooLong, client, columns, ddl, table
from pikanaut.dialects import SQLITE, Limits


@table("notes")
class Note(BaseModel):
    id: Annotated[int | None, Col(pk=True)] = None
    text: str


def main() -> None:
    db = client(SQLITE)
    N = columns(Note)

    # --- 1. слишком много параметров
    try:
        db.select(N.id).where(N.id.in_(range(10_001))).build()
    except QueryTooLong as exc:
        print("params:", exc)
        print("  kind =", exc.kind, "| length =", exc.length, "| limit =", exc.limit)

    # --- 2. то же, но с поднятым лимитом
    wide = client(SQLITE, limits=Limits(max_params=20_000))
    built = wide.select(N.id).where(N.id.in_(range(12_000))).build()
    print("\nс limits=20_000:", len(built.params), "параметров — собралось")

    # --- 3. лимит на длину текста
    tight = client(SQLITE, limits=Limits(max_sql_bytes=120, max_params=None))
    try:
        tight.select(N.id, N.text).where(N.text.like("%" + "x" * 200)).build()
    except QueryTooLong as exc:
        print("\nbytes: ", exc)

    # --- 4. как жить с лимитом: резать insert_many на чанки
    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Note, dialect=SQLITE):
        conn.execute(statement.sql)

    rows = [Note(text=f"заметка {i}") for i in range(2_500)]
    chunk = 100                                   # 1 колонка × 100 строк = 100 параметров
    for start in range(0, len(rows), chunk):
        statement = db.insert_many(rows[start : start + chunk]).build()
        conn.execute(statement.sql, statement.params)
    total = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    print(f"\nвставлено чанками по {chunk}: {total} строк")

    # --- 5. выключить проверки совсем (если вы точно знаете свою базу)
    free = client(SQLITE, limits=Limits(max_sql_bytes=None, max_params=None))
    print("без проверок:", len(free.select(N.id).where(N.id.in_(range(15_000))).build().params))


if __name__ == "__main__":
    main()
