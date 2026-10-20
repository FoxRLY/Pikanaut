from __future__ import annotations

import pytest

from pikanaut import client, columns
from pikanaut.dialects import POSTGRES, SQLITE, SQLITE_34
from tests.models import Note, PublicUser, User


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
    return columns(User)


@pytest.fixture
def N():
    return columns(Note)


@pytest.fixture
def P():
    return columns(PublicUser)
