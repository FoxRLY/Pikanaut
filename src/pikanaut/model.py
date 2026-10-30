"""Pydantic base model for concrete and reusable table models."""

from __future__ import annotations

import json
from datetime import datetime, time, timezone
from typing import Any, ClassVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    ValidationInfo,
    field_validator,
    model_serializer,
)
from pydantic_core import PydanticSerializationError

from .defaults import GENERATED
from .errors import SchemaError
from .fields import ColumnSpec


def _column_spec(model: type[BaseModel], field_name: str) -> ColumnSpec | None:
    field = model.model_fields.get(field_name)
    if field is None:
        return None
    specs = [item for item in field.metadata if isinstance(item, ColumnSpec)]
    if len(specs) > 1:
        raise SchemaError(
            f"{model.__name__}.{field_name}: multiple column declarations"
        )
    return specs[0] if specs else None


class TableModel(BaseModel):
    """Pydantic model whose ordinary fields can describe a SQL table.

    A subclass is concrete only when that class declares ``table=...`` itself.
    Subclasses without ``table`` are reusable field bases and do not inherit table
    or schema registration from a concrete parent.
    """

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
        validate_default=True,
    )

    __pikanaut_table__: ClassVar[tuple[str, str | None] | None] = None

    def __init_subclass__(
        cls,
        *,
        table: str | None = None,
        schema: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if table is None:
            if schema is not None:
                raise SchemaError(f"{cls.__name__}: schema requires an explicit table")
            cls.__pikanaut_table__ = None
            return
        if not table:
            raise SchemaError(f"{cls.__name__}: table name may not be empty")
        if schema is not None and not schema:
            raise SchemaError(f"{cls.__name__}: schema name may not be empty")
        cls.__pikanaut_table__ = (table, schema)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if cls.__dict__.get("__pikanaut_table__") is not None:
            from .schema import table_of

            table_of(cls)

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def _pikanaut_parse_json(cls, value: object, info: ValidationInfo) -> object:
        field_name = info.field_name
        spec = _column_spec(cls, field_name) if field_name is not None else None
        if spec is None or spec.kind != "json" or not isinstance(value, str):
            return value
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON text") from exc
        if decoded is None:
            raise ValueError("top-level JSON null documents are not supported")
        return decoded

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def _pikanaut_temporal_policy(cls, value: object, info: ValidationInfo) -> object:
        if value is None or value is GENERATED:
            return value
        field_name = info.field_name
        if field_name is None:
            return value
        field = cls.model_fields[field_name]
        spec = _column_spec(cls, field_name)

        if isinstance(value, datetime):
            timezone_enabled = spec.timezone if spec is not None else True
            if timezone_enabled is False:
                if value.tzinfo is not None and value.utcoffset() is not None:
                    raise ValueError("datetime must be naive when timezone=False")
                return value
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("datetime must be timezone-aware")
            return value.astimezone(timezone.utc)

        if isinstance(value, time):
            # Datetime has already returned above; every SQL TIME is naive in v2.
            if value.tzinfo is not None and value.utcoffset() is not None:
                raise ValueError("time must be a time without tzinfo")
            return value

        # Keep the local variable read so static checking catches model-field API drift.
        _ = field
        return value

    @model_serializer(mode="wrap")
    def _pikanaut_serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> object:
        data = cast(object, handler(self))
        if not isinstance(data, dict):
            return data
        for field_name, field in type(self).model_fields.items():
            if getattr(self, field_name, None) is not GENERATED:
                continue
            key = field_name
            if info.by_alias:
                key = field.serialization_alias or field.alias or field_name
            if key in data:
                raise PydanticSerializationError(
                    f"{type(self).__name__}.{field_name}: GENERATED cannot be serialized; "
                    "exclude the field or replace it with a database value"
                )
        return cast(dict[str, object], data)


__all__ = ["TableModel"]
