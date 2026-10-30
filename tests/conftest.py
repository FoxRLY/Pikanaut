from __future__ import annotations

import pytest

from pikanaut import client
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34
from tests.generated import notes, users
from tests.generated.public import users as public_users


@pytest.fixture
def db():
    """SQLite 3.35+: плейсхолдеры ?, RETURNING есть."""
    return client(SQLITE)


@pytest.fixture
def pg():
    return client(POSTGRES)


@pytest.fixture
def old_sqlite():
    return client(SQLITE_34)


@pytest.fixture
def U():
    return users


@pytest.fixture
def N():
    return notes


@pytest.fixture
def P():
    return public_users
