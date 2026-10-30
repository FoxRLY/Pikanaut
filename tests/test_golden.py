"""Golden SQL: точный текст запроса на каждый диалект.

Строки здесь — контракт рендера. Пробелы и кавычки важны: они проверяются.
"""

from __future__ import annotations

import pytest

from pikanaut import QueryError, UnsupportedFeature
from tests.generated import notes, users
from tests.models import Note, User


def test_select_with_where_order_limit(db, U) -> None:
    q = db.select(U.id, U.email).where(U.age > 18).order_by(U.id.desc()).limit(10)
    sql = q.build()
    assert (
        sql.sql
        == 'SELECT "id","user_email" FROM "users" WHERE "age">? ORDER BY "id" DESC LIMIT 10'
    )
    assert sql.params == [18]


def test_postgres_numeric_placeholders(pg, U) -> None:
    sql = pg.select(U.id).where(U.age > 18).where(U.age < 65).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "age">$1 AND "age"<$2'
    assert sql.params == [18, 65]


def test_schema_rendered_on_postgres(pg, P) -> None:
    assert pg.select(P.id).build().sql == 'SELECT "id" FROM "public"."users"'


def test_schema_rejected_on_sqlite(db, P) -> None:
    with pytest.raises(UnsupportedFeature, match="schema"):
        db.select(P.id).build()


def test_insert_uses_only_provided_fields(db, N) -> None:
    sql = db.insert(notes, Note(text="hi")).build()
    assert sql.sql == 'INSERT INTO "notes" ("text") VALUES (?)'
    assert sql.params == ["hi"]


def test_insert_many_rows(db) -> None:
    sql = db.insert_many(notes, [Note(text="a"), Note(text="b")]).build()
    assert sql.sql == 'INSERT INTO "notes" ("text") VALUES (?),(?)'
    assert sql.params == ["a", "b"]


def test_insert_many_requires_same_shape(db) -> None:
    with pytest.raises(QueryError, match="shape"):
        db.insert_many(notes, [Note(text="a"), Note(id=5, text="b")]).build()


def test_update_set_where(db, U) -> None:
    sql = db.update(users).set(age=30).where(U.id == 7).build()
    assert sql.sql == 'UPDATE "users" SET "age"=? WHERE "id"=?'
    assert sql.params == [30, 7]


def test_update_requires_where(db, U) -> None:
    with pytest.raises(QueryError, match="WHERE"):
        db.update(users).set(age=30).build()


def test_delete_requires_where(db) -> None:
    with pytest.raises(QueryError, match="WHERE"):
        db.delete(users).build()


def test_delete_all_is_explicit(db) -> None:
    assert db.delete_all(users).build().sql == 'DELETE FROM "users"'


def test_update_all_is_explicit(db) -> None:
    sql = db.update_all(users).set(age=0).build()
    assert sql.sql == 'UPDATE "users" SET "age"=?'


def test_returning_on_sqlite_335(db, N) -> None:
    sql = db.insert(notes, Note(text="x")).returning(N.id).build()
    assert sql.sql == 'INSERT INTO "notes" ("text") VALUES (?) RETURNING "id"'


def test_returning_absent_before_335(old_sqlite) -> None:
    q = old_sqlite.insert(notes, Note(text="x")).returning(notes.id)
    with pytest.raises(UnsupportedFeature, match="returning"):
        q.build()


def test_offset_without_limit_sqlite(db, U) -> None:
    assert (
        db.select(U.id).offset(20).build().sql
        == 'SELECT "id" FROM "users" LIMIT -1 OFFSET 20'
    )


def test_offset_without_limit_postgres(pg, U) -> None:
    assert (
        pg.select(U.id).offset(20).build().sql == 'SELECT "id" FROM "users" OFFSET 20'
    )


def test_in_expands_qmark_on_sqlite(db, U) -> None:
    sql = db.select(U.id).where(U.age.in_([1, 2, 3])).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "age" IN (?,?,?)'
    assert sql.params == [1, 2, 3]


def test_in_uses_any_on_postgres(pg, U) -> None:
    sql = pg.select(U.id).where(U.age.in_([1, 2, 3])).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "age" = ANY($1)'
    assert sql.params == [[1, 2, 3]]


def test_empty_in_rejected(db, U) -> None:
    with pytest.raises(QueryError, match="IN"):
        db.select(U.id).where(U.age.in_([])).build()


def test_like_binds_pattern(db, U) -> None:
    sql = db.select(U.id).where(U.email.like("%@corp%")).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "user_email" LIKE ?'
    assert sql.params == ["%@corp%"]


def test_ilike_rejected_on_sqlite(db, U) -> None:
    """Column не знает диалекта, поэтому ILIKE проверяется на build(), а не отсутствием метода."""
    with pytest.raises(UnsupportedFeature, match="ILIKE"):
        db.select(U.id).where(U.email.ilike("%x%")).build()


def test_group_by_having(db, U) -> None:
    sql = db.select(U.age).group_by(U.age).having(U.age > 18).build()
    assert sql.sql == 'SELECT "age" FROM "users" GROUP BY "age" HAVING "age">?'
