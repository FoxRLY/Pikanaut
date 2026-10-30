"""End-to-end acceptance of the documented generated-table workflow."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


MODELS = '''from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel
from pikanaut import (
    TableModel, IntColumn, StrColumn, DecimalColumn, DateTimeColumn,
    JsonColumn, Generated, Identity, defaults,
)

class Details(BaseModel):
    label: str
    amount: Decimal

class Record(TableModel, table="records"):
    id: int | Generated = IntColumn(pk=True, server_default=Identity())
    name: str = StrColumn(min_length=1, max_length=12)
    age: int = IntColumn(greater_than_or_equal=0, default=0)
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    amount: Decimal = DecimalColumn(default=Decimal("1.50"))
    details: Details = JsonColumn()
    created_at: datetime | Generated = DateTimeColumn(server_default=defaults.NOW)

class Other(TableModel, table="others"):
    id: int = IntColumn(pk=True)
    age: int
'''


EXERCISE = '''import sqlite3
from decimal import Decimal
from pydantic import ValidationError
from pikanaut import GENERATED, QueryError, UnsupportedOperation, client, count, ddl
from pikanaut.dialects import SQLITE
from app.models import Details, Record
from app.generated import records, others

db = client(SQLITE)
value = Record(name="Alice", details=Details(label="one", amount=Decimal("2.50")))
assert value.id is GENERATED
assert value.created_at is GENERATED
assert value.age == 0
try:
    value.model_dump()
except (ValueError, TypeError):
    pass
else:
    raise AssertionError("unresolved generated values must not serialize")
assert value.model_dump(exclude={"id", "created_at"})["name"] == "Alice"

with sqlite3.connect(":memory:") as connection:
    connection.row_factory = sqlite3.Row
    for statement in ddl.create(Record, dialect=SQLITE):
        connection.execute(statement.sql, statement.params)
    statement = db.insert(records, value).returning(records.id).build()
    inserted_id = connection.execute(statement.sql, statement.params).fetchone()[0]
    assert value.id is GENERATED  # no automatic hydration
    query = db.select(records).where(records.id == inserted_id).build()
    restored = Record.model_validate(dict(connection.execute(query.sql, query.params).fetchone()))
    assert restored.id == inserted_id
    assert restored.created_at.tzinfo is not None
    assert restored.details.amount == Decimal("2.50")
    assert restored.amount == Decimal("1.50")
    assert restored.status == "OPEN"

    base = db.update(records).where(records.id == inserted_id)
    changed = base.set(age=-1).set(age=records.age + 2)
    statement = changed.build()
    connection.execute(statement.sql, statement.params)
    assert connection.execute("SELECT age FROM records").fetchone()[0] == 2
    try:
        base.build()
    except QueryError:
        pass
    else:
        raise AssertionError("base UPDATE was mutated by set")
    try:
        base.set(age=-1).build()
    except ValidationError:
        pass
    else:
        raise AssertionError("UPDATE skipped field bounds")
    try:
        db.select(records.amount).order_by(records.amount).build()
    except UnsupportedOperation:
        pass
    else:
        raise AssertionError("SQLite Decimal was ordered as text")
    statement = db.select(count(records.amount)).build()
    assert connection.execute(statement.sql, statement.params).fetchone()[0] == 1
    try:
        db.select(records.id).where(others.age > 0).build()
    except QueryError:
        pass
    else:
        raise AssertionError("foreign source was silently accepted")
    try:
        connection.execute("UPDATE records SET status='INVALID'")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("DDL omitted Literal CHECK")
print("Generated-table SQLite acceptance passed")
'''


def run_python(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Application imports must use the same package root as its CLI invocation.
    env["PYTHONPATH"] = str(project)
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_documented_generation_sqlite_roundtrip(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "__init__.py").write_text("")
    (app / "models.py").write_text(MODELS)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pikanaut]\nmodels = ["app.models"]\n'
        'output_package = "app.generated"\n'
    )
    generated = run_python(tmp_path, "-m", "pikanaut", "generate")
    assert generated.returncode == 0, generated.stdout + generated.stderr
    checked = run_python(tmp_path, "-m", "pikanaut", "generate", "--check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    exercised = run_python(tmp_path, "-c", EXERCISE)
    assert exercised.returncode == 0, exercised.stdout + exercised.stderr
    assert "SQLite acceptance passed" in exercised.stdout

    owned_files = sorted((app / "generated").rglob("*.py"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in owned_files}
    (app / "models.py").write_text(MODELS.replace('"CLOSED"', '"CLOSED", "ARCHIVED"'))
    stale = run_python(tmp_path, "-m", "pikanaut", "generate", "--check")
    assert stale.returncode != 0
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in owned_files}
    assert after == before, "--check must not change generated files"
