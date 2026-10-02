"""Binary sensor entities for Satellite Alarms room endpoints."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SatelliteAlarmRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up room-level Satellite Alarms binary sensors."""
    async_add_entities([AlarmRingingBinarySensor(hass, entry)])


class AlarmRingingBinarySensor(SatelliteAlarmRoomEntity, BinarySensorEntity):
    """Whether an alarm is actively ringing in this room."""

    _attr_translation_key = "alarm_ringing"
    _attr_icon = "mdi:alarm-bell"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the ringing-state sensor."""
        super().__init__(hass, entry, "alarm_ringing")

    @property
    def is_on(self) -> bool:
        """Return whether a room alarm is ringing."""
        return self.playback.active_for_endpoint(self.entry.entry_id) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return active/queued alarm runtime metadata."""
        active = self.playback.active_for_endpoint(self.entry.entry_id)
        return {
            "active_alarm_id": active.alarm_id if active else None,
            "queued_count": len(self.playback.queued_for_endpoint(self.entry.entry_id)),
        }
