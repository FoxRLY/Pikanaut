"""Семантика условий: NULL, булева композиция, hash, запрет bool()."""

from __future__ import annotations

import pytest

from pikanaut import and_, not_, or_


def test_eq_none_on_nullable_column_is_is_null(db, U) -> None:
    sql = db.select(U.id).where(U.age == None).build()  # noqa: E711
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "age" IS NULL'
    assert sql.params == []


def test_ne_none_on_nullable_column_is_is_not_null(db, U) -> None:
    assert db.select(U.id).where(U.age != None).build().sql == (  # noqa: E711
        'SELECT "id" FROM "users" WHERE "age" IS NOT NULL'
    )


def test_eq_none_on_not_null_column_raises(U) -> None:
    with pytest.raises(TypeError, match="is_null"):
        U.email == None  # noqa: E711


def test_is_null_always_allowed(U) -> None:
    assert U.email.is_null() is not None


def test_cond_cannot_be_truthy(U) -> None:
    with pytest.raises(TypeError, match="bool"):
        bool(U.age > 18)


def test_column_is_hashable(U) -> None:
    assert len({U.id, U.id, U.email}) == 2
    assert U.id in {U.id}


def test_where_arguments_are_anded(db, U) -> None:
    sql = db.select(U.id).where(U.age > 18, U.age < 65).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "age">? AND "age"<?'
    assert sql.params == [18, 65]


def test_or_at_root_has_no_extra_parens(db, U) -> None:
    sql = db.select(U.id).where(or_(U.age > 18, U.age < 65)).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "age">? OR "age"<?'


def test_nested_or_is_parenthesized(db, U) -> None:
    sql = db.select(U.id).where(or_(U.age > 18, U.age < 65), U.id > 0).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE ("age">? OR "age"<?) AND "id">?'


def test_operators_match_functions(db, U) -> None:
    via_ops = db.select(U.id).where((U.age > 18) & (U.age < 65)).build()
    via_fn = db.select(U.id).where(and_(U.age > 18, U.age < 65)).build()
    assert via_ops.sql == via_fn.sql


def test_not_wraps_condition(db, U) -> None:
    assert db.select(U.id).where(not_(U.age > 18)).build().sql == (
        'SELECT "id" FROM "users" WHERE NOT ("age">?)'
    )


def test_invert_operator_matches_not(db, U) -> None:
    assert db.select(U.id).where(~(U.age > 18)).build().sql == (
        'SELECT "id" FROM "users" WHERE NOT ("age">?)'
    )


def test_contains_renders_like_with_wildcards(db, U) -> None:
    sql = db.select(U.id).where(U.email.contains("corp")).build()
    assert sql.sql == 'SELECT "id" FROM "users" WHERE "user_email" LIKE ?'
    assert sql.params == ["%corp%"]
