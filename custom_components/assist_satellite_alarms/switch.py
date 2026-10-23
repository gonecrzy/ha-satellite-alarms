"""Switch entities for Satellite Alarms."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SatelliteAlarmEntity, setup_dynamic_alarm_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up per-alarm enable switches."""
    setup_dynamic_alarm_entities(
        hass,
        entry,
        async_add_entities,
        AlarmEnabledSwitch,
    )


class AlarmEnabledSwitch(SatelliteAlarmEntity, SwitchEntity):
    """Enable or disable one Scheduler-backed alarm."""

    _attr_icon = "mdi:alarm-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, alarm_id: str) -> None:
        """Initialize the alarm enabled switch."""
        super().__init__(hass, entry, alarm_id, "enabled")

    @property
    def name(self) -> str:
        """Return the alarm-specific display name."""
        return f"{self.alarm_display_name} enabled"

    @property
    def is_on(self) -> bool | None:
        """Return the Scheduler-backed enabled state."""
        record = self.record
        if record is None:
            return None
        response = self.manager.response(record)
        enabled = response.get("enabled")
        return enabled if isinstance(enabled, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the backing alarm and Scheduler identifiers."""
        record = self.record
        if record is None:
            return None
        response = self.manager.response(record)
        return {
            "alarm_id": record.alarm_id,
            "scheduler_entity_id": response.get("scheduler_entity_id"),
            "scheduler_state": (
                self.hass.states.get(str(response.get("scheduler_entity_id"))).state
                if response.get("scheduler_entity_id")
                and self.hass.states.get(str(response.get("scheduler_entity_id")))
                else None
            ),
            "stored_time": response.get("time"),
            "next_trigger": response.get("next_trigger"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the alarm."""
        try:
            await self.manager.async_set_enabled(self.alarm_id, True)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the alarm."""
        try:
            await self.manager.async_set_enabled(self.alarm_id, False)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
