from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pikanaut.generate import (
    GENERATED_HEADER,
    GenerationError,
    generate,
    main,
)

ROOT = Path(__file__).resolve().parent.parent


def _write_project(
    tmp_path: Path, package: str = "sample_app", *, src: bool = True
) -> Path:
    source_root = tmp_path / "src" if src else tmp_path
    model_package = source_root / package
    model_package.mkdir(parents=True)
    (model_package / "__init__.py").write_text("", encoding="utf-8")
    (model_package / "models.py").write_text(
        f"""from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel
from pikanaut import IntColumn, JsonColumn, StrColumn, TableModel
from pikanaut.defaults import Generated, Identity


class State(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"


class Profile(BaseModel):
    label: str


class Shared(TableModel):
    note: str


class User(Shared, table="users"):
    id: int | Generated = IntColumn(pk=True, server_default=Identity(generated="ALWAYS"))
    age: int | None
    state: Literal["active", "paused"]
    enum_state: State
    profile: Profile = JsonColumn()
    created_at: datetime


# Re-exported from another configured module below; discovery must deduplicate it.
UsersAlias = User
""",
        encoding="utf-8",
    )
    (model_package / "more_models.py").write_text(
        f"""from __future__ import annotations

from pikanaut.schema import TableModel
from {package}.models import User


class Audit(TableModel, table="audit", schema="public"):
    id: int
    user_id: int
""",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        f'''[project]
name = "generation-fixture"
version = "0"

[tool.pikanaut]
models = ["{package}.models", "{package}.more_models"]
output_package = "{package}.generated"
''',
        encoding="utf-8",
    )
    return tmp_path


def test_generate_is_deterministic_and_groups_by_sql_schema(tmp_path: Path) -> None:
    project = _write_project(tmp_path)

    first = generate(project / "pyproject.toml")
    root_init = project / "src/sample_app/generated/__init__.py"
    public_init = project / "src/sample_app/generated/public/__init__.py"
    first_bytes = {path: path.read_bytes() for path in (root_init, public_init)}
    first_mtimes = {path: path.stat().st_mtime_ns for path in first_bytes}

    second = generate(project / "pyproject.toml")

    assert first == second
    assert root_init.read_text(encoding="utf-8").startswith(GENERATED_HEADER)
    root_text = root_init.read_text(encoding="utf-8")
    assert "class UsersSource:" in root_text
    assert "class UsersTable(Table[User, UsersSource]):" in root_text
    assert "id: Column[int, UsersSource]" in root_text
    assert "age: Column[int | None, UsersSource]" in root_text
    assert "class UsersUpdateValues(TypedDict, total=False):" in root_text
    assert (
        "id:"
        not in root_text.split("class UsersUpdateValues", 1)[1].split(
            "class UsersUpdate", 1
        )[0]
    )
    assert "Column[int, UsersSource]" in root_text
    assert "Column[int | None, UsersSource]" in root_text
    assert "class UsersUpdate(Update[UsersSource]):" in root_text
    assert "def set(self, **values: Unpack[UsersUpdateValues]) -> Self:" in root_text
    assert "return self._set_values(values)" in root_text
    assert "super().__init__(User)" in root_text
    assert "self.id = self.__pikanaut_column__('id')" in root_text
    assert "users = UsersTable()" in root_text
    assert "class Public" not in root_text
    assert "class AuditTable(Table[Audit, AuditSource]):" in public_init.read_text(
        encoding="utf-8"
    )
    assert {path: path.read_bytes() for path in first_bytes} == first_bytes
    assert {path: path.stat().st_mtime_ns for path in first_bytes} == first_mtimes


def test_check_is_read_only_and_reports_missing_or_stale_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _write_project(tmp_path, package="check_app")
    config = project / "pyproject.toml"

    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in project.rglob("*")
        if p.is_file()
    }
    assert main(["generate", "--check", "--config", str(config)]) == 1
    after = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in project.rglob("*")
        if p.is_file()
    }
    assert after == before
    assert "missing" in capsys.readouterr().err.lower()

    generate(config)
    generated = project / "src/check_app/generated/__init__.py"
    generated.write_text(
        generated.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8"
    )
    stale_bytes = generated.read_bytes()
    stale_mtime = generated.stat().st_mtime_ns
    time.sleep(0.002)

    assert main(["generate", "--check", "--config", str(config)]) == 1
    assert generated.read_bytes() == stale_bytes
    assert generated.stat().st_mtime_ns == stale_mtime

    generate(config)
    assert main(["generate", "--check", "--config", str(config)]) == 0


def test_cleanup_removes_only_owned_stale_files(tmp_path: Path) -> None:
    project = _write_project(tmp_path, package="cleanup_app")
    config = project / "pyproject.toml"
    generate(config)
    output = project / "src/cleanup_app/generated"
    stale = output / "stale.py"
    stale.write_text(GENERATED_HEADER + "stale = True\n", encoding="utf-8")
    user_file = output / "keep.py"
    user_file.write_text("user_owned = True\n", encoding="utf-8")

    generate(config)

    assert not stale.exists()
    assert user_file.read_text(encoding="utf-8") == "user_owned = True\n"


def test_rejects_user_owned_target_and_package_export_collision(tmp_path: Path) -> None:
    project = _write_project(tmp_path, package="collision_app")
    config = project / "pyproject.toml"
    target = project / "src/collision_app/generated/__init__.py"
    target.parent.mkdir(parents=True)
    target.write_text("# user file\n", encoding="utf-8")

    with pytest.raises(GenerationError, match="refusing to overwrite"):
        generate(config)

    target.unlink()
    models = project / "src/collision_app/more_models.py"
    models.write_text(
        models.read_text(encoding="utf-8")
        + """\nclass Public(TableModel, table="public"):\n    id: int\n""",
        encoding="utf-8",
    )
    with pytest.raises(GenerationError, match="collides with schema package"):
        generate(config)


def test_rejects_invalid_names_and_ambiguous_roots(tmp_path: Path) -> None:
    project = _write_project(tmp_path, package="invalid_app")
    config = project / "pyproject.toml"
    models = project / "src/invalid_app/more_models.py"
    models.write_text(
        models.read_text(encoding="utf-8")
        + """\nclass Bad(TableModel, table="not-valid"):\n    id: int\n""",
        encoding="utf-8",
    )
    with pytest.raises(GenerationError, match="valid Python identifier"):
        generate(config)

    ambiguous = _write_project(tmp_path / "ambiguous", package="ambiguous_app")
    flat = ambiguous / "ambiguous_app"
    flat.mkdir()
    (flat / "__init__.py").write_text("", encoding="utf-8")
    with pytest.raises(GenerationError, match="ambiguous"):
        generate(ambiguous / "pyproject.toml")

    explicit = ambiguous / "src/ambiguous_app/generated_explicit"
    generate(ambiguous / "pyproject.toml", output_directory=explicit)
    assert (explicit / "__init__.py").is_file()


def test_cli_generates_from_project_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _write_project(tmp_path, package="cli_app", src=False)
    monkeypatch.chdir(project)

    assert main(["generate"]) == 0
    assert (project / "cli_app/generated/__init__.py").is_file()
    assert main(["generate", "--check"]) == 0


def test_generated_contract_passes_and_negative_cases_fail_both_checkers(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mypy")
    pytest.importorskip("pyright")
    if not (Path(sys.executable).is_file() and os.environ.get("PATH")):
        pytest.skip("checker subprocess environment unavailable")

    project = _write_project(tmp_path, package="typing_app")
    generate(project / "pyproject.toml")
    good = project / "good.py"
    good.write_text(
        """from __future__ import annotations

from typing_extensions import assert_type
from pikanaut.dialects import SQLITE
from pikanaut.expr import Column
from typing_app.generated import UsersSource, users

assert_type(users.id, Column[int, UsersSource])
assert_type(users.age, Column[int | None, UsersSource])
users.__pikanaut_update__(SQLITE, SQLITE.limits).set(age=1).set(age=users.id)
""",
        encoding="utf-8",
    )
    bad = project / "bad.py"
    bad.write_text(
        """from typing_app.generated import users
from typing_app.generated.public import audit
from pikanaut.dialects import SQLITE

update = users.__pikanaut_update__(SQLITE, SQLITE.limits)
users.missing
update.set(missing=1)
update.set(age="wrong")
update.set(age=audit.id)
update.set(id=1)
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(project / "src"), env.get("PYTHONPATH", "")]
    )
    env["MYPYPATH"] = os.pathsep.join([str(ROOT / "src"), str(project / "src")])

    commands = {
        "mypy": [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--python-version",
            "3.10",
            "--explicit-package-bases",
        ],
        "pyright": [
            sys.executable,
            "-m",
            "pyright",
            "--pythonpath",
            sys.executable,
            "--pythonversion",
            "3.10",
        ],
    }
    for name, command in commands.items():
        positive = subprocess.run(
            [*command, str(good)],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert positive.returncode == 0, (
            f"{name}:\n{positive.stdout}\n{positive.stderr}"
        )
        negative = subprocess.run(
            [*command, str(bad)],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        diagnostics = negative.stdout + negative.stderr
        assert negative.returncode != 0, (
            f"{name} accepted invalid generated-table calls"
        )
        for line_number in range(6, 11):
            assert f":{line_number}:" in diagnostics, (
                f"{name} did not reject bad.py line {line_number}:\n{diagnostics}"
            )
