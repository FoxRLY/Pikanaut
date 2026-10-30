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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.generated.models import Order
from examples.generated.tables import orders
from pikanaut import avg, client, count, ddl, sum as total
from pikanaut.dialects import SQLITE


def main() -> None:
    db = client(SQLITE)

    grouped = (
        db.select(orders.customer, total(orders.amount), count())
        .group_by(orders.customer)
        .having(total(orders.amount) > 100)
        .order_by(orders.customer.asc())
        .build()
    )
    print("GROUP BY:", grouped.sql)
    print("params:  ", grouped.params)

    page = (
        db.select(orders.id, orders.amount)
        .order_by(orders.amount.desc())
        .limit(2)
        .offset(1)
        .build()
    )
    print("\npage:    ", page.sql)

    tail = db.select(orders.id).offset(2).build()
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

    print(
        "\nсредний чек:",
        conn.execute(db.select(avg(orders.amount)).build().sql).fetchone(),
    )


if __name__ == "__main__":
    main()
