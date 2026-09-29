"""Persistent alarm metadata registry.

Scheduler Component owns the actual schedule definitions. This registry stores
only Satellite Alarms metadata needed to associate those schedules with an
Assist satellite endpoint and alarm-specific behavior.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import AlarmRecord


class AlarmRegistry:
    """Versioned persistent registry for Satellite Alarms metadata."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registry."""
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._alarms: dict[str, AlarmRecord] = {}

    async def async_load(self) -> None:
        """Load alarm metadata from storage."""
        data = await self._store.async_load() or {}
        records = data.get("alarms", [])
        self._alarms = {
            record.alarm_id: record
            for item in records
            if (record := AlarmRecord.from_dict(item))
        }

    async def async_save(self) -> None:
        """Persist the current registry."""
        await self._store.async_save(
            {"alarms": [record.as_dict() for record in self._alarms.values()]}
        )

    def get(self, alarm_id: str) -> AlarmRecord | None:
        """Return one alarm record."""
        return self._alarms.get(alarm_id)

    def all(self) -> tuple[AlarmRecord, ...]:
        """Return all alarm records."""
        return tuple(self._alarms.values())

    def for_endpoint(self, entry_id: str) -> tuple[AlarmRecord, ...]:
        """Return alarm records owned by a config entry."""
        return tuple(
            record
            for record in self._alarms.values()
            if record.endpoint_entry_id == entry_id
        )

    async def async_upsert(self, record: AlarmRecord) -> None:
        """Create or replace an alarm metadata record."""
        self._alarms[record.alarm_id] = record
        await self.async_save()

    async def async_remove(self, alarm_id: str) -> bool:
        """Remove an alarm metadata record."""
        if alarm_id not in self._alarms:
            return False
        del self._alarms[alarm_id]
        await self.async_save()
        return True
