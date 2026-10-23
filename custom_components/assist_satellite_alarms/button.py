"""Button entities for Satellite Alarms."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up per-alarm management buttons."""
    setup_dynamic_alarm_entities(
        hass,
        entry,
        async_add_entities,
        AlarmDeleteButton,
    )


class AlarmDeleteButton(SatelliteAlarmEntity, ButtonEntity):
    """Delete one managed alarm."""

    _attr_icon = "mdi:delete-alert-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, alarm_id: str) -> None:
        """Initialize the delete button."""
        super().__init__(hass, entry, alarm_id, "delete")

    @property
    def name(self) -> str:
        """Return the alarm-specific display name."""
        return f"Delete {self.alarm_display_name}"

    async def async_press(self) -> None:
        """Delete the alarm and clean any active or queued playback."""
        record = self.record
        if record is None:
            raise HomeAssistantError("Alarm no longer exists")

        active = self.playback.active_for_endpoint(record.endpoint_entry_id)
        if active is not None and active.alarm_id == self.alarm_id:
            await self.playback.async_stop(alarm_id=self.alarm_id, reason="delete")

        self.playback.remove_queued_alarm(self.alarm_id)

        try:
            await self.manager.async_delete(self.alarm_id)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
