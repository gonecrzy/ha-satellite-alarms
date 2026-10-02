"""Sensor entities for Satellite Alarms room endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SatelliteAlarmRoomEntity
from .models import AlarmRecord


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up room-level Satellite Alarms sensors."""
    async_add_entities(
        [
            NextAlarmSensor(hass, entry),
            AlarmCountSensor(hass, entry),
            ActiveAlarmSensor(hass, entry),
        ]
    )


def _record_attributes(record: AlarmRecord, response: dict[str, object]) -> dict[str, Any]:
    """Return stable dashboard-friendly attributes for one alarm."""
    return {
        "alarm_id": record.alarm_id,
        "name": record.name,
        "time": response.get("time"),
        "recurrence": response.get("recurrence"),
        "days": response.get("days"),
        "enabled": response.get("enabled"),
        "scheduler_entity_id": response.get("scheduler_entity_id"),
        "skip_next": response.get("skip_next"),
        "override": response.get("override"),
    }


class NextAlarmSensor(SatelliteAlarmRoomEntity, SensorEntity):
    """Next scheduled alarm for a room."""

    _attr_translation_key = "next_alarm"
    _attr_icon = "mdi:alarm"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the next-alarm sensor."""
        super().__init__(hass, entry, "next_alarm")

    @property
    def native_value(self) -> datetime | None:
        """Return the next Scheduler-backed trigger."""
        next_alarm = self.manager.next_alarm_for_endpoint(self.entry.entry_id)
        if next_alarm is None:
            return None
        _record, trigger = next_alarm
        return trigger

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return management metadata for the next alarm."""
        next_alarm = self.manager.next_alarm_for_endpoint(self.entry.entry_id)
        if next_alarm is None:
            return None
        record, _trigger = next_alarm
        return _record_attributes(record, self.manager.response(record))


class AlarmCountSensor(SatelliteAlarmRoomEntity, SensorEntity):
    """Number of alarms configured for a room."""

    _attr_translation_key = "alarm_count"
    _attr_icon = "mdi:alarm-multiple"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the alarm-count sensor."""
        super().__init__(hass, entry, "alarm_count")

    @property
    def native_value(self) -> int:
        """Return the total number of room alarms."""
        return len(self.manager.alarms_for_endpoint(self.entry.entry_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enabled and queued counts."""
        records = self.manager.alarms_for_endpoint(self.entry.entry_id)
        enabled_count = sum(
            self.manager.response(record).get("enabled") is True for record in records
        )
        return {
            "enabled_count": enabled_count,
            "disabled_count": len(records) - enabled_count,
            "queued_count": len(self.playback.queued_for_endpoint(self.entry.entry_id)),
        }


class ActiveAlarmSensor(SatelliteAlarmRoomEntity, SensorEntity):
    """Currently ringing alarm for a room."""

    _attr_translation_key = "active_alarm"
    _attr_icon = "mdi:alarm-light"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the active-alarm sensor."""
        super().__init__(hass, entry, "active_alarm")

    @property
    def native_value(self) -> str | None:
        """Return the active alarm name."""
        active = self.playback.active_for_endpoint(self.entry.entry_id)
        if active is None:
            return None
        record = self.manager.registry.get(active.alarm_id)
        return (record.name if record and record.name else active.alarm_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return runtime details for the active alarm."""
        active = self.playback.active_for_endpoint(self.entry.entry_id)
        if active is None:
            return None

        record = self.manager.registry.get(active.alarm_id)
        return {
            "alarm_id": active.alarm_id,
            "name": record.name if record else None,
            "started_at": active.started_at.isoformat(),
            "playback_mode": active.playback_mode,
            "current_assist_satellite": active.assist_satellite_entity_id,
            "current_media_player": active.media_player_entity_id,
            "assist_satellites": [
                target.assist_satellite_entity_id for target in active.targets
            ],
            "media_players": [target.media_player_entity_id for target in active.targets],
            "queued_alarm_ids": list(
                self.playback.queued_for_endpoint(self.entry.entry_id)
            ),
        }
