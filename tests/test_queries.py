from __future__ import annotations

from typing import TypedDict

import pytest
from typing_extensions import Self, Unpack

from pikanaut.client import Update, client
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34, Dialect, Limits
from pikanaut.errors import QueryError, QueryTooLong, UnsupportedFeature
from pikanaut.expr import Column, lower
from pikanaut.fields import IntColumn, JsonColumn, StrColumn
from pikanaut.schema import TableModel
from pikanaut.tables import Table


class User(TableModel, table="users"):
    id: int = IntColumn(pk=True)
    name: str = StrColumn(min_length=1)
    age: int | None = None
    visits: int = 0
    profile: dict[str, object] = JsonColumn(default_factory=dict)


class Article(TableModel, table="articles"):
    id: int = IntColumn(pk=True)
    title: str
    views: int = 0


class UsersSource: ...


class ArticlesSource: ...


class UsersUpdateValues(TypedDict, total=False):
    id: int | Column[int, UsersSource]
    name: str | Column[str, UsersSource]
    age: int | None | Column[int, UsersSource] | Column[int | None, UsersSource]
    visits: int | Column[int, UsersSource]
    profile: dict[str, object] | Column[dict[str, object], UsersSource]


class UsersUpdate(Update[UsersSource]):
    def set(self, **values: Unpack[UsersUpdateValues]) -> Self:
        return self._set_values(values)


class UsersTable(Table[User, UsersSource]):
    id: Column[int, UsersSource]
    name: Column[str, UsersSource]
    age: Column[int | None, UsersSource]
    visits: Column[int, UsersSource]
    profile: Column[dict[str, object], UsersSource]

    def __init__(self) -> None:
        super().__init__(User)
        self.id = self.__pikanaut_column__("id")
        self.name = self.__pikanaut_column__("name")
        self.age = self.__pikanaut_column__("age")
        self.visits = self.__pikanaut_column__("visits")
        self.profile = self.__pikanaut_column__("profile")

    def __pikanaut_update__(
        self, dialect: Dialect, limits: Limits, require_where: bool = True
    ) -> UsersUpdate:
        return UsersUpdate(  # type: ignore[arg-type]
            dialect, limits, self.__pikanaut_info__, require_where=require_where
        )


class ArticlesTable(Table[Article, ArticlesSource]):
    id: Column[int, ArticlesSource]
    title: Column[str, ArticlesSource]
    views: Column[int, ArticlesSource]

    def __init__(self) -> None:
        super().__init__(Article)
        self.id = self.__pikanaut_column__("id")
        self.title = self.__pikanaut_column__("title")
        self.views = self.__pikanaut_column__("views")


users = UsersTable()
articles = ArticlesTable()


def test_select_table_and_projection() -> None:
    db = client(SQLITE)
    assert db.select(users).build().sql == (
        'SELECT "id","name","age","visits","profile" FROM "users"'
    )
    statement = db.select(users.id, users.name).where(users.id == 7).build()
    assert statement.sql == 'SELECT "id","name" FROM "users" WHERE "id"=?'
    assert statement.params == [7]


def test_expression_and_query_branches_are_immutable() -> None:
    db = client(SQLITE)
    base = db.select(users.id)
    adults = base.where(users.age >= 18)
    named = base.where(lower(users.name) == "alice")
    assert base.build().sql == 'SELECT "id" FROM "users"'
    assert adults.build().params == [18]
    assert named.build().params == ["alice"]


def test_foreign_source_is_rejected_at_runtime() -> None:
    db = client(SQLITE)
    with pytest.raises(QueryError, match="another table|source"):
        db.select(users.id).where(articles.id == 1).build()  # pyright: ignore[reportArgumentType]
    with pytest.raises(QueryError, match="another table|source"):
        db.select(users.id, articles.id).build()  # pyright: ignore[reportArgumentType]
    with pytest.raises(QueryError, match="another table|source"):
        db.update(users).set(visits=articles.views).where(users.id == 1).build()  # pyright: ignore[reportArgumentType]


def test_insert_binds_all_model_values_and_serializes_json() -> None:
    statement = (
        client(SQLITE)
        .insert(users, User(id=1, name="A", profile={"nested": [1, None]}))
        .build()
    )
    assert statement.sql == (
        'INSERT INTO "users" ("id","name","age","visits","profile") VALUES (?,?,?,?,?)'
    )
    assert statement.params == [1, "A", None, 0, '{"nested":[1,null]}']


def test_insert_rejects_model_for_another_table() -> None:
    with pytest.raises(QueryError, match="model|table"):
        client(SQLITE).insert(users, Article(id=1, title="wrong"))  # pyright: ignore[reportArgumentType]


def test_update_merges_last_value_validates_final_value_and_is_immutable() -> None:
    db = client(SQLITE)
    base = db.update(users)
    changed = base.set(name="old", visits=-1).set(name="new", visits=2)
    statement = changed.where(users.id == 7).build()
    assert statement.sql == ('UPDATE "users" SET "name"=?,"visits"=? WHERE "id"=?')
    assert statement.params == ["new", 2, 7]
    with pytest.raises(QueryError, match="SET"):
        base.where(users.id == 7).build()


def test_update_expression_is_rendered_not_bound() -> None:
    statement = (
        client(POSTGRES)
        .update(users)
        .set(visits=users.visits + 1)
        .where(users.id == 7)
        .build()
    )
    assert statement.sql == ('UPDATE "users" SET "visits"="visits"+$1 WHERE "id"=$2')
    assert statement.params == [1, 7]


def test_update_and_delete_require_where() -> None:
    db = client(SQLITE)
    with pytest.raises(QueryError, match="WHERE"):
        db.update(users).set(name="x").build()
    with pytest.raises(QueryError, match="WHERE"):
        db.delete(users).build()
    assert db.update_all(users).set(name="x").build().sql.startswith("UPDATE")
    assert db.delete_all(users).build().sql == 'DELETE FROM "users"'


def test_returning_is_checked_against_runtime_dialect() -> None:
    with pytest.raises(UnsupportedFeature, match="returning"):
        client(SQLITE_34).delete_all(users).returning(users.id).build()


def test_sqlite_batch_splits_for_limits_and_preserves_order() -> None:
    rows = [User(id=i, name=f"u{i}") for i in range(5)]
    db = client(SQLITE, limits=Limits(max_params=10, max_sql_bytes=1_000_000))
    statements = db.insert_many(users, rows).batch().build()
    assert [len(s.params) for s in statements] == [10, 10, 5]
    assert [p for s in statements for p in s.params[::5]] == [0, 1, 2, 3, 4]


def test_batch_raises_when_one_row_cannot_fit() -> None:
    db = client(SQLITE, limits=Limits(max_params=4, max_sql_bytes=None))
    with pytest.raises(QueryTooLong):
        db.insert(users, User(id=1, name="A")).batch().build()


def test_json_unknown_objects_are_not_stringified() -> None:
    class Unknown:
        pass

    # Deliberately bypass model construction to exercise the dialect boundary.
    with pytest.raises((TypeError, ValueError)):
        SQLITE.adapt({"bad": Unknown()}, json=True)
