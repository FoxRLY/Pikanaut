from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

import pytest
from typing_extensions import Self, Unpack

from pikanaut.client import Update, client
from pikanaut.dialects import POSTGRES, SQLITE, Dialect, Limits
from pikanaut.errors import UnsupportedOperation
from pikanaut.expr import Column, count, sum
from pikanaut.fields import DecimalColumn, IntColumn
from pikanaut.schema import TableModel
from pikanaut.tables import Table


class Account(TableModel, table="accounts"):
    id: int = IntColumn(pk=True)
    balance: Decimal = DecimalColumn()


class AccountsSource: ...


class AccountUpdateValues(TypedDict, total=False):
    balance: Decimal | Column[Decimal, AccountsSource]


class AccountUpdate(Update[AccountsSource]):
    def set(self, **values: Unpack[AccountUpdateValues]) -> Self:
        return self._set_values(values)


class AccountsTable(Table[Account, AccountsSource]):
    id: Column[int, AccountsSource]
    balance: Column[Decimal, AccountsSource]

    def __init__(self) -> None:
        super().__init__(Account)
        self.id = self.__pikanaut_column__("id")
        self.balance = self.__pikanaut_column__("balance")

    def __pikanaut_update__(
        self, dialect: Dialect, limits: Limits, require_where: bool = True
    ) -> AccountUpdate:
        return AccountUpdate(  # type: ignore[arg-type]
            dialect, limits, self.__pikanaut_info__, require_where=require_where
        )


accounts = AccountsTable()


@pytest.mark.parametrize(
    "query",
    [
        lambda: (
            client(SQLITE).select(accounts.id).where(accounts.balance > Decimal("1"))
        ),
        lambda: (
            client(SQLITE)
            .select(accounts.id)
            .where(accounts.balance.in_([Decimal("1")]))
        ),
        lambda: client(SQLITE).select(accounts.balance + Decimal("1")),
        lambda: client(SQLITE).select(accounts.balance).order_by(accounts.balance),
        lambda: client(SQLITE).select(accounts.balance).group_by(accounts.balance),
        lambda: client(SQLITE).select(sum(accounts.balance)),
    ],
)
def test_sqlite_rejects_decimal_numeric_operations(query: object) -> None:
    with pytest.raises(UnsupportedOperation, match="Decimal"):
        query().build()  # type: ignore[operator]


def test_sqlite_allows_decimal_storage_null_checks_and_count() -> None:
    insert = (
        client(SQLITE).insert(accounts, Account(id=1, balance=Decimal("10.50"))).build()
    )
    assert insert.params == [1, "10.50"]
    assert (
        client(SQLITE).select(accounts.id).where(accounts.balance.is_not_null()).build()
    )
    assert client(SQLITE).select(count(accounts.balance)).build()


def test_postgres_supports_decimal_arithmetic_comparison_and_aggregate() -> None:
    statement = (
        client(POSTGRES)
        .select(accounts.id, accounts.balance + Decimal("1.25"))
        .where(accounts.balance >= Decimal("10"))
        .order_by(accounts.balance.desc())
        .build()
    )
    assert statement.params == [Decimal("1.25"), Decimal("10")]
    assert client(POSTGRES).select(sum(accounts.balance)).build()


def test_sqlite_rejects_decimal_update_expression_but_not_literal_storage() -> None:
    with pytest.raises(UnsupportedOperation, match="Decimal"):
        (
            client(SQLITE)
            .update(accounts)
            .set(balance=accounts.balance + Decimal("1"))
            .where(accounts.id == 1)
            .build()
        )
    literal = (
        client(SQLITE)
        .update(accounts)
        .set(balance=Decimal("2.50"))
        .where(accounts.id == 1)
        .build()
    )
    assert literal.params == ["2.50", 1]
