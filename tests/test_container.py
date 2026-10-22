from typing import Generator
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest

from psycopg.rows import TupleRow
from testcontainers.community.postgres import PostgresContainer
import psycopg

from pikanaut import client, ddl
from pikanaut.dialects.postgres import POSTGRES_PSYCOPG
from tests.models import Event, Note, PublicUser, User


@pytest.fixture(scope="module")
def pg_container() -> Generator[PostgresContainer]:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        yield container

@pytest.fixture(scope="function")
def db_conn(pg_container: PostgresContainer) -> Generator[psycopg.Connection[TupleRow]]:
    connection_url = pg_container.get_connection_url().replace("postgresql+psycopg", "postgresql")

    with psycopg.connect(connection_url, autocommit=True, connect_timeout=5, hostaddr="127.0.0.1") as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")

        for model in (Note, User, Event, PublicUser):
            for statement in ddl.create(model, dialect=POSTGRES_PSYCOPG):
                conn.execute(statement.sql)

        yield conn


def test_types_come_back_typed(db_conn: psycopg.Connection[TupleRow]) -> None:
    db = client(POSTGRES_PSYCOPG)

    event = Event(
        id=1,
        is_active=True,
        at=datetime(2026, 10, 20, 12, 0),
        amount=Decimal("10.50"),
        uid=UUID("12345678-1234-5678-1234-567812345678"),
    )

    statement = db.insert(event).build()
    db_conn.execute(statement.sql, statement.params)

    selected = db.select(Event).build()
    row = db_conn.execute(selected.sql, selected.params).fetchone()

    assert row is not None
    assert row[0] == 1
    assert row[1] is True                       # BOOLEAN, а не 1
    assert row[2].tzinfo is not None            # TIMESTAMPTZ → aware
    assert row[3] == Decimal("10.50")           # NUMERIC без потерь
    assert row[4] == UUID("12345678-1234-5678-1234-567812345678")


