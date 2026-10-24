"""Точные типы биндинга и минимальный контракт рендера, включая duck typing."""

from __future__ import annotations

from typing_extensions import LiteralString, assert_type
from pypika import Query, Table

from pikanaut.build import Binder, RenderContext, Sql, render
from pikanaut.dialects import POSTGRES, SQLITE, Limits
from pikanaut import Col, client, ddl, raw
from tests.models import User


def binding_contract(value: object) -> None:
    binder = Binder(SQLITE)
    assert_type(binder.params, list[object])
    assert_type(binder.bind(value), str)
    assert_type(binder.bind_array((1, value)), str)
    assert_type(RenderContext(SQLITE, binder).bind(value), str)
    assert_type(Sql("SELECT 1", [value], SQLITE).params, list[object])
    assert_type(POSTGRES.adapt(value), object)


class RequiredQuoteQuery:
    def get_sql(self, *, quote_char: str) -> str:
        return "SELECT 1"


class OptionalQuoteQuery:
    def get_sql(self, *, quote_char: str | None = None) -> str:
        return "SELECT 1"


def render_contract() -> None:
    assert_type(render(RequiredQuoteQuery(), SQLITE, Limits()), Sql)
    assert_type(render(OptionalQuoteQuery(), SQLITE, Limits()), Sql)
    assert_type(render(Query.from_(Table("notes")).select("id"), SQLITE, Limits()), Sql)
    render(object(), SQLITE, Limits())  # type: ignore[arg-type]


def generated_sql_contract() -> None:
    assert_type(client(SQLITE).select(User).build().sql, LiteralString)
    assert_type(ddl.create(User, dialect=SQLITE)[0].sql, LiteralString)
    assert_type(ddl.drop(User, dialect=SQLITE).sql, LiteralString)


def sql_type_contract() -> None:
    assert_type(Col(type="VECTOR(3)").sql_type, LiteralString | None)


def trusted_sql_inputs_contract(sql_text: str) -> None:
    raw(sql_text)  # pyright: ignore[reportArgumentType]
    Col(type=sql_text)  # pyright: ignore[reportArgumentType]
