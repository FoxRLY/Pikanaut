"""04 — агрегаты, группировка, сортировка, страницы.

Запуск: uv run python examples/04_aggregates.py

Что показывает:
  * count/sum/avg типизированы (Column[int], Column[float]) и работают в select;
  * GROUP BY + HAVING;
  * offset() без limit() на sqlite рендерится как LIMIT -1 OFFSET n —
    движок иначе не принимает OFFSET без LIMIT.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BaseModel

from pikanaut import Col, avg, client, columns, count, ddl, table, sum as total
from pikanaut.dialects import SQLITE

@table("orders")
class Order(BaseModel):
    id: Annotated[int, Col(pk=True)]
    customer: str
    amount: int


def main() -> None:
    db = client(SQLITE)
    O = columns(Order)

    grouped = (
        db.select(O.customer, total(O.amount), count())
        .group_by(O.customer)
        .having(total(O.amount) > 100)
        .order_by(O.customer.asc())
        .build()
    )
    print("GROUP BY:", grouped.sql)
    print("params:  ", grouped.params)

    page = db.select(O.id, O.amount).order_by(O.amount.desc()).limit(2).offset(1).build()
    print("\npage:    ", page.sql)

    tail = db.select(O.id).offset(2).build()
    print("offset без limit:", tail.sql)

    conn = sqlite3.connect(":memory:")
    for statement in ddl.create(Order, dialect=SQLITE):
        conn.execute(statement.sql)
    conn.executemany(
        "INSERT INTO orders (customer, amount) VALUES (?, ?)",
        [("ann", 120), ("ann", 60), ("bob", 30), ("bob", 90), ("cid", 200)],
    )

    print("\nпо клиентам (сумма > 100):")
    for row in conn.execute(grouped.sql, grouped.params):
        print("  ", row)

    print("\nсредний чек:", conn.execute(
        db.select(avg(O.amount)).build().sql
    ).fetchone())


if __name__ == "__main__":
    main()
