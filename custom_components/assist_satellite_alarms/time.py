"""Time entities for Satellite Alarms."""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import META_DATE, META_DAYS, META_RECURRENCE, META_TIME
from .entity import SatelliteAlarmEntity, setup_dynamic_alarm_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up editable per-alarm clock times."""
    setup_dynamic_alarm_entities(
        hass,
        entry,
        async_add_entities,
        AlarmTimeEntity,
    )


class AlarmTimeEntity(SatelliteAlarmEntity, TimeEntity):
    """Editable alarm clock time."""

    _attr_icon = "mdi:clock-edit-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, alarm_id: str) -> None:
        """Initialize the alarm time entity."""
        super().__init__(hass, entry, alarm_id, "time")

    @property
    def name(self) -> str:
        """Return the alarm-specific display name."""
        return f"{self.alarm_display_name} time"

    @property
    def native_value(self) -> time | None:
        """Return the stored alarm clock time."""
        record = self.record
        if record is None:
            return None
        return dt_util.parse_time(str(record.metadata.get(META_TIME) or ""))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose recurrence/date context for this editable time."""
        record = self.record
        if record is None:
            return None
        response = self.manager.response(record)
        return {
            "alarm_id": record.alarm_id,
            "recurrence": record.metadata.get(META_RECURRENCE),
            "date": record.metadata.get(META_DATE),
            "days": record.metadata.get(META_DAYS),
            "enabled": response.get("enabled"),
            "scheduler_entity_id": response.get("scheduler_entity_id"),
            "next_trigger": response.get("next_trigger"),
        }

    async def async_set_value(self, value: time) -> None:
        """Update the alarm's stored and Scheduler-backed clock time."""
        try:
            await self.manager.async_update(
                alarm_id=self.alarm_id,
                time_value=value.strftime("%H:%M:%S"),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
