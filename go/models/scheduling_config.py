"""
GO Model: scheduling_config
System-wide configuration as key-value pairs with JSONB values.
Loaded at the start of every booking/cancel operation.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Any, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import json


@dataclass
class SchedulingConfig:
    id: UUID
    config_key: str
    config_value: Any  # JSONB — can be number, string, object
    description: Optional[str]
    updated_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime


class ConfigModel:

    @staticmethod
    async def get_by_key(db: AsyncSession, key: str) -> Optional[SchedulingConfig]:
        result = await db.execute(
            text("SELECT * FROM scheduling_config WHERE config_key = :key"),
            {"key": key},
        )
        row = result.mappings().first()
        return SchedulingConfig(**row) if row else None

    @staticmethod
    async def get_value(db: AsyncSession, key: str, default: Any = None) -> Any:
        """Get just the value for a config key. Returns default if not found."""
        result = await db.execute(
            text("SELECT config_value FROM scheduling_config WHERE config_key = :key"),
            {"key": key},
        )
        row = result.first()
        if row is None:
            return default
        return row[0]

    @staticmethod
    async def get_all(db: AsyncSession) -> Dict[str, Any]:
        """Get all config as a dict: {key: value}."""
        result = await db.execute(
            text("SELECT config_key, config_value FROM scheduling_config ORDER BY config_key")
        )
        return {row.config_key: row.config_value for row in result.mappings().all()}

    @staticmethod
    async def update_value(
        db: AsyncSession,
        key: str,
        value: Any,
        updated_by: UUID,
    ) -> Optional[SchedulingConfig]:
        result = await db.execute(
            text("""
                UPDATE scheduling_config
                SET config_value = :value, updated_by = :updated_by
                WHERE config_key = :key
                RETURNING *
            """),
            {"key": key, "value": json.dumps(value), "updated_by": updated_by},
        )
        row = result.mappings().first()
        return SchedulingConfig(**row) if row else None
