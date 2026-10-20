"""Лимиты сборки: ошибка приходит при build(), а не при выполнении запроса.

Семантика (SPEC.md, 5.1):

-   лимиты по умолчанию — политические: 1 000 000 байт текста, 10 000 параметров;
-   число параметров проверяется инкрементально, до рендера строки;
-   длина текста — после рендера, в байтах UTF-8;
-   лимит принадлежит клиенту: client(..., limits=...) не меняет глобальный диалект;
-   сообщение различает политический лимит и предел движка и не печатает запрос целиком.
"""

from __future__ import annotations

import pytest

from pikanaut import QueryTooLong, client
from pikanaut.dialects import POSTGRES, SQLITE, Limits
from tests.models import Note, User


def test_default_limits_are_practical_not_engine() -> None:
    assert SQLITE.limits.max_params == 10_000
    assert SQLITE.limits.max_sql_bytes == 1_000_000
    assert SQLITE.engine_max_params == 32_766        # предел движка остаётся известным
    assert POSTGRES.engine_max_params == 65_535


def test_too_many_params_fails_early(db, U) -> None:
    with pytest.raises(QueryTooLong) as exc:
        db.select(U.id).where(U.age.in_(list(range(10_001)))).build()
    assert exc.value.kind == "params"
    assert exc.value.limit == 10_000
    assert exc.value.length == 10_001


def test_params_error_mentions_engine_ceiling_and_how_to_raise(db, U) -> None:
    with pytest.raises(QueryTooLong) as exc:
        db.select(U.id).where(U.age.in_(list(range(10_001)))).build()
    message = str(exc.value)
    assert "32766" in message.replace(" ", "") or "32 766" in message
    assert "Limits" in message            # подсказка, как поднять лимит
    assert len(message) < 600             # никаких дампов запроса


def test_client_can_raise_the_limit(U) -> None:
    loose = client(SQLITE, limits=Limits(max_params=20_000))
    loose.select(U.id).where(U.age.in_(list(range(11_000)))).build()   # не падает


def test_limits_can_be_disabled(U) -> None:
    free = client(SQLITE, limits=Limits(max_sql_bytes=None, max_params=None))
    free.select(U.id).where(U.age.in_(list(range(12_000)))).build()    # не падает


def test_client_limits_do_not_leak_into_dialect(db, U) -> None:
    tight = client(SQLITE, limits=Limits(max_params=1))
    with pytest.raises(QueryTooLong):
        tight.select(U.id).where(U.age.in_([1, 2])).build()
    db.select(U.id).where(U.age.in_([1, 2])).build()                   # исходный клиент цел
    assert SQLITE.limits.max_params == 10_000


def test_sql_bytes_limit(U) -> None:
    tight = client(SQLITE, limits=Limits(max_sql_bytes=64, max_params=None))
    with pytest.raises(QueryTooLong) as exc:
        tight.select(U.id, U.email, U.full_name).where(U.email.like("%x%")).build()
    assert exc.value.kind == "sql_bytes"
    assert exc.value.limit == 64
    assert exc.value.length > 64


def test_length_is_measured_in_utf8_bytes(U) -> None:
    """Кириллица в идентификаторах: байтов больше, чем символов — считаем байты."""
    from typing import Annotated

    from pydantic import BaseModel

    from pikanaut import Col, columns, table

    @table("товары")
    class Товар(BaseModel):
        id: Annotated[int, Col(pk=True)]
        название: Annotated[str, Col("название")]
        описание: Annotated[str, Col("описание")]

    T = columns(Товар)
    plain = client(SQLITE).select(T.id, T.название, T.описание).build().sql
    chars, octets = len(plain), len(plain.encode("utf-8"))
    assert octets > chars                       # иначе тест ничего не проверяет

    tight = client(SQLITE, limits=Limits(max_sql_bytes=chars + 1, max_params=None))
    with pytest.raises(QueryTooLong) as exc:
        tight.select(T.id, T.название, T.описание).build()
    assert exc.value.length == octets


def test_sql_bytes_message_is_truncated(U) -> None:
    tight = client(SQLITE, limits=Limits(max_sql_bytes=64, max_params=None))
    with pytest.raises(QueryTooLong) as exc:
        tight.select(U.id, U.email, U.full_name).where(U.email.like("%corp%")).build()
    message = str(exc.value)
    assert "truncated" in message
    assert len(message) < 700


def test_insert_many_hints_rows_per_statement(db) -> None:
    rows = [Note(text=f"t{i}") for i in range(10_001)]
    with pytest.raises(QueryTooLong) as exc:
        db.insert_many(rows).build()
    assert exc.value.kind == "params"
    assert "rows" in str(exc.value)       # подсказка про чанки


def test_params_limit_counts_in_every_clause(db, U) -> None:
    """Лимит общий на запрос, а не на clause: where + set + in_ складываются."""
    with pytest.raises(QueryTooLong):
        (
            db.update(User).set(age=1, full_name="x")
            .where(U.id.in_(list(range(9_999))))
            .build()
        )
