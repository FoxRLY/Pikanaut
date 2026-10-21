"""Совместимость импорта и строкового контракта Feature между версиями Python."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest


def test_public_api_imports_in_fresh_interpreter() -> None:
    """Пакет импортируется без предварительного импорта его зависимостей тестами."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pikanaut import Col, client, columns, ddl, table; "
            "from pikanaut.dialects import POSTGRES, POSTGRES_PSYCOPG, SQLITE",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RETURNING", "returning"),
        ("SCHEMA", "schema"),
        ("UPSERT", "upsert"),
        ("ILIKE", "ilike"),
        ("FOR_UPDATE", "for_update"),
        ("ARRAYS", "arrays"),
    ],
)
def test_feature_preserves_string_contract(name: str, value: str) -> None:
    """Замена StrEnum не меняет значения, форматирование и строковые ключи."""
    from pikanaut.dialects.base import Feature

    feature = Feature[name]
    assert isinstance(feature, str)
    assert feature.value == value
    assert str(feature) == value
    assert f"{feature}" == value
    assert format(feature, ">16") == format(value, ">16")
    assert feature == value
    assert hash(feature) == hash(value)
    supported: dict[str, str] = {feature: "supported"}
    assert supported[value] == "supported"
    assert json.dumps(feature) == json.dumps(value)
    assert Feature(value) is feature
