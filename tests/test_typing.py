"""Типовой контракт проверяется линтерами, а не рантаймом.

tests/typing — это не pytest-тесты, а файлы с ожиданиями: позитивные через
``assert_type``, негативные через ``# type: ignore[...]``. Здесь мы запускаем mypy и
pyright и требуем нулевой код возврата. ``--warn-unused-ignores`` превращает
«ожидаемая ошибка не сработала» в ошибку линтера.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = "tests/typing"


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=ROOT, capture_output=True, text=True, timeout=180
    )


def test_mypy_expectations() -> None:
    pytest.importorskip("mypy")
    result = _run(
        sys.executable, "-m", "mypy", "--strict", "--warn-unused-ignores", TARGET
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="pyright требует node")
def test_pyright_expectations() -> None:
    pytest.importorskip("pyright")
    # В tox проверяем зависимости именно текущего окружения, не системного Python.
    result = _run(
        sys.executable, "-m", "pyright", "--pythonpath", sys.executable, TARGET
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
