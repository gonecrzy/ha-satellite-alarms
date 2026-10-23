"""Sensor entities for Satellite Alarms room endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    META_DATE,
    META_DAYS,
    META_RECURRENCE,
    META_SOURCE_TEXT,
    META_SOURCE_TIME_SLOT,
    META_TIME,
)
from .entity import (
    SatelliteAlarmEntity,
    SatelliteAlarmRoomEntity,
    setup_dynamic_alarm_entities,
)
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
    setup_dynamic_alarm_entities(
        hass,
        entry,
        async_add_entities,
        AlarmScheduleSensor,
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
        enabled_states = [self.manager.response(record).get("enabled") for record in records]
        enabled_count = sum(state is True for state in enabled_states)
        disabled_count = sum(state is False for state in enabled_states)
        return {
            "enabled_count": enabled_count,
            "disabled_count": disabled_count,
            "unknown_schedule_count": len(records) - enabled_count - disabled_count,
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
        return record.name if record and record.name else active.alarm_id

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
            "assist_satellites": [target.assist_satellite_entity_id for target in active.targets],
            "media_players": [target.media_player_entity_id for target in active.targets],
            "queued_alarm_ids": list(self.playback.queued_for_endpoint(self.entry.entry_id)),
        }


class AlarmScheduleSensor(SatelliteAlarmEntity, SensorEntity):
    """Validate one alarm's stored definition against Scheduler state."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, alarm_id: str) -> None:
        """Initialize the alarm schedule validation sensor."""
        super().__init__(hass, entry, alarm_id, "schedule")

    @property
    def name(self) -> str:
        """Return the alarm-specific display name."""
        return f"{self.alarm_display_name} schedule"

    def _scheduler_details(self) -> tuple[str | None, object | None]:
        """Return Scheduler entity ID and state."""
        record = self.record
        if record is None:
            return None, None
        entity_id = (
            self.manager.scheduler.find_entity_id(record.alarm_id) or record.scheduler_entity_id
        )
        return entity_id, self.hass.states.get(entity_id) if entity_id else None

    @staticmethod
    def _scheduler_time(state) -> str | None:
        """Extract the first Scheduler timeslot start time."""
        if state is None:
            return None
        timeslots = state.attributes.get("timeslots")
        if not isinstance(timeslots, list) or not timeslots:
            return None
        first = str(timeslots[0])
        return first.split(" - ", 1)[0].strip() or None

    @staticmethod
    def _local_next_trigger(state) -> datetime | None:
        """Parse Scheduler's raw next trigger as local Home Assistant time."""
        if state is None:
            return None
        raw = state.attributes.get("next_trigger")
        if not raw:
            return None
        parsed = dt_util.parse_datetime(str(raw))
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.now().tzinfo)
        return dt_util.as_local(parsed)

    @property
    def native_value(self) -> str:
        """Return a concise validation state."""
        record = self.record
        if record is None:
            return "missing_alarm"

        entity_id, state = self._scheduler_details()
        if entity_id is None or state is None:
            return "missing_schedule"
        if state.state == STATE_OFF:
            return "disabled"
        if state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            return "scheduler_unavailable"

        stored_time = str(record.metadata.get(META_TIME) or "")
        scheduler_time = self._scheduler_time(state)
        if scheduler_time and scheduler_time != stored_time:
            return "time_mismatch"

        trigger = self._local_next_trigger(state)
        if trigger is not None and trigger.strftime("%H:%M:%S") != stored_time:
            return "next_trigger_mismatch"

        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Show stored and Scheduler values side-by-side for validation."""
        record = self.record
        if record is None:
            return None

        entity_id, state = self._scheduler_details()
        scheduler_time = self._scheduler_time(state)
        trigger = self._local_next_trigger(state)
        response = self.manager.response(record)

        return {
            "alarm_id": record.alarm_id,
            "name": record.name,
            "enabled": response.get("enabled"),
            "stored_time": record.metadata.get(META_TIME),
            "scheduler_time": scheduler_time,
            "recurrence": record.metadata.get(META_RECURRENCE),
            "date": record.metadata.get(META_DATE),
            "days": record.metadata.get(META_DAYS),
            "scheduler_entity_id": entity_id,
            "scheduler_state": state.state if state else None,
            "scheduler_next_trigger_raw": (state.attributes.get("next_trigger") if state else None),
            "next_trigger_local": trigger.isoformat() if trigger else None,
            "home_assistant_timezone": self.hass.config.time_zone,
            "voice_input": record.metadata.get(META_SOURCE_TEXT),
            "voice_time_slot": record.metadata.get(META_SOURCE_TIME_SLOT),
            "skip_next": response.get("skip_next"),
            "override": response.get("override"),
        }
