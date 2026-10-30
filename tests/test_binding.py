"""Биндинг: значения живут в params, а не в тексте SQL; адаптация под диалект."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pikanaut import client
from pikanaut.dialects import POSTGRES, SQLITE
from tests.generated import events, users
from tests.models import Event, User


def test_value_never_appears_in_sql(db, U) -> None:
    evil = "'; DROP TABLE users--"
    sql = db.select(U.id).where(U.email == evil).build()
    assert evil not in sql.sql
    assert "DROP" not in sql.sql
    assert sql.params == [evil]


def test_sqlite_adapts_scalar_types(db) -> None:
    row = Event(
        id=1,
        is_active=True,
        at=datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
        amount=Decimal("10.50"),
        uid=UUID("12345678-1234-5678-1234-567812345678"),
    )
    sql = db.insert(events, row).build()
    assert sql.params == [
        1,
        1,  # bool → 0/1
        "2026-10-20T12:00:00+00:00",  # aware datetime → ISO 8601
        "10.50",  # Decimal → str, без потери точности
        "12345678-1234-5678-1234-567812345678",
    ]


def test_postgres_passes_types_through(pg) -> None:
    at = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    amount = Decimal("10.50")
    row = Event(id=1, is_active=True, at=at, amount=amount, uid=UUID(int=1))
    sql = pg.insert(events, row).build()
    assert sql.params[1] is True  # bool остаётся bool
    assert sql.params[2] is at  # datetime отдаём драйверу как есть
    assert sql.params[3] is amount


def test_limit_is_rendered_not_bound() -> None:
    """Лимит — не данные пользователя, он рендерится числом, а не параметром."""
    sql = client(SQLITE).select(users).limit(10).build()
    assert sql.sql.endswith("LIMIT 10")
    assert sql.params == []
