"""Postgres: настоящий сервер в контейнере + psycopg3.

Проверяется то, что sqlite-набор проверить не может: `$n`→`%s` у драйвера, identity,
NUMERIC, JSONB, UUID, TIMESTAMPTZ, схема `public`, `= ANY(...)`, ILIKE.

Без docker тесты пропускаются; в CI нужно `PIKANAUT_REQUIRE_POSTGRES=1`, чтобы отсутствие
контейнера было падением, а не тихим skip.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from pikanaut import QueryError, client, columns, ddl
from pikanaut.dialects import POSTGRES, POSTGRES_PSYCOPG
from tests.models import Event, Note, PublicUser, User

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("testcontainers.postgres")

REQUIRE = os.environ.get("PIKANAUT_REQUIRE_POSTGRES") == "1"


def _docker_ready() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001 — любая причина означает «нет docker»
        return False


@pytest.fixture(scope="session")
def pg_container() -> Any:
    if not _docker_ready():
        if REQUIRE:
            pytest.fail("PIKANAUT_REQUIRE_POSTGRES=1, но docker недоступен")
        pytest.skip("docker недоступен — Postgres-тесты пропущены")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        yield container


@pytest.fixture
def pg(pg_container: Any) -> Any:
    # get_connection_url() отдаёт SQLAlchemy-стиль (postgresql+psycopg://),
    # psycopg его не понимает — снимаем драйверный суффикс
    dsn = pg_container.get_connection_url().replace("postgresql+psycopg", "postgresql")
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    yield conn
    conn.close()


def _user(uid: int = 1, **overrides: Any) -> User:
    values: dict[str, Any] = dict(
        id=uid,
        email=f"u{uid}@b.io",
        full_name="Ann Lee",
        password_hash="secret",
        age=None,
        created_at=datetime(2026, 10, 20, 12, 0),
    )
    values.update(overrides)
    return User(**values)


def _create(conn: Any, *models: type) -> None:
    for model in models:
        for statement in ddl.create(model, dialect=POSTGRES_PSYCOPG):
            conn.execute(statement.sql)


def test_placeholder_styles_differ_only_in_spelling() -> None:
    U = columns(User)
    asyncpg_sql = client(POSTGRES).select(U.id).where(U.age > 18).build().sql
    psycopg_sql = client(POSTGRES_PSYCOPG).select(U.id).where(U.age > 18).build().sql
    assert asyncpg_sql == 'SELECT "id" FROM "users" WHERE "age">$1'
    assert psycopg_sql == 'SELECT "id" FROM "users" WHERE "age">%s'


def test_ddl_is_accepted_by_server(pg: Any) -> None:
    _create(pg, Note, User, Event, PublicUser)

    columns_found = {
        row[0]
        for row in pg.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users'"
        )
    }
    assert {"id", "user_email", "full_name", "age", "created_at"} <= columns_found

    types = dict(
        pg.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'events'"
        ).fetchall()
    )
    assert types["amount"] == "numeric"
    assert types["meta" if "meta" in types else "uid"] in {"jsonb", "uuid"}


def test_identity_and_returning(pg: Any) -> None:
    _create(pg, Note)
    db = client(POSTGRES_PSYCOPG)
    N = columns(Note)

    ids = []
    for text in ("a", "b"):
        statement = db.insert(Note(text=text)).returning(N.id).build()
        ids.append(pg.execute(statement.sql, statement.params).fetchone()[0])
    assert ids == [1, 2]


def test_in_any_ilike_and_offset(pg: Any) -> None:
    _create(pg, User)
    db = client(POSTGRES_PSYCOPG)
    U = columns(User)

    for user in (_user(1, age=30, email="ann@corp.com"), _user(2, age=17), _user(3, age=None)):
        statement = db.insert(user).build()
        pg.execute(statement.sql, statement.params)

    in_statement = db.select(U.id).where(U.age.in_([30, 17])).order_by(U.id.asc()).build()
    assert [row[0] for row in pg.execute(in_statement.sql, in_statement.params)] == [1, 2]

    nul_statement = db.select(U.id).where(U.age == None).build()  # noqa: E711
    assert [row[0] for row in pg.execute(nul_statement.sql, nul_statement.params)] == [3]

    like_statement = db.select(U.id).where(U.email.ilike("%CORP%")).build()
    assert [row[0] for row in pg.execute(like_statement.sql, like_statement.params)] == [1]

    offset_statement = db.select(U.id).order_by(U.id.asc()).offset(1).build()
    assert [row[0] for row in pg.execute(offset_statement.sql, offset_statement.params)] == [2, 3]


def test_types_come_back_typed(pg: Any) -> None:
    _create(pg, Event)
    db = client(POSTGRES_PSYCOPG)

    event = Event(
        id=1,
        is_active=True,
        at=datetime(2026, 10, 20, 12, 0),
        amount=Decimal("10.50"),
        uid=UUID("12345678-1234-5678-1234-567812345678"),
    )
    statement = db.insert(event).build()
    pg.execute(statement.sql, statement.params)

    selected = db.select(Event).build()
    row = pg.execute(selected.sql, selected.params).fetchone()
    assert row[0] == 1
    assert row[1] is True                       # BOOLEAN, а не 1
    assert row[2].tzinfo is not None            # TIMESTAMPTZ → aware
    assert row[3] == Decimal("10.50")           # NUMERIC без потерь
    assert row[4] == UUID("12345678-1234-5678-1234-567812345678")


def test_value_is_never_interpolated(pg: Any) -> None:
    _create(pg, User)
    db = client(POSTGRES_PSYCOPG)
    U = columns(User)

    evil = "'; DROP TABLE users--"
    statement = db.select(U.id).where(U.email == evil).build()
    assert evil not in statement.sql
    assert pg.execute(statement.sql, statement.params).fetchall() == []

    still_there = pg.execute("SELECT to_regclass('public.users')").fetchone()[0]
    assert still_there is not None


def test_guards_stop_before_the_server(pg: Any) -> None:
    _create(pg, User)
    with pytest.raises(QueryError):
        client(POSTGRES_PSYCOPG).delete(User).build()
    assert pg.execute('SELECT COUNT(*) FROM "users"').fetchone()[0] == 0


def test_drop_removes_table(pg: Any) -> None:
    _create(pg, User)
    assert pg.execute("SELECT to_regclass('public.users')").fetchone()[0] is not None

    pg.execute(ddl.drop(User, dialect=POSTGRES_PSYCOPG).sql)
    assert pg.execute("SELECT to_regclass('public.users')").fetchone()[0] is None


def test_schema_qualified_table(pg: Any) -> None:
    _create(pg, PublicUser)
    db = client(POSTGRES_PSYCOPG)
    P = columns(PublicUser)

    statement = db.insert(PublicUser(id=1, email="a@b.io")).build()
    assert '"public"."users"' in statement.sql
    pg.execute(statement.sql, statement.params)

    selected = db.select(P.id).build()
    assert pg.execute(selected.sql, selected.params).fetchall() == [(1,)]


def test_create_is_idempotent(pg: Any) -> None:
    for _ in range(2):
        _create(pg, Note)
