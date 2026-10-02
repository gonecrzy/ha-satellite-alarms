"""Tests for Satellite Alarms room entities."""

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.binary_sensor import (
    AlarmRingingBinarySensor,
)
from custom_components.assist_satellite_alarms.alarm_manager import AlarmManager
from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DATA_ALARM_MANAGER,
    DATA_PLAYBACK_MANAGER,
    DOMAIN,
    META_DATE,
    META_DAYS,
    META_RECURRENCE,
    META_SKIP_NEXT,
    META_TIME,
    PLAYBACK_MODE_ALL,
    RECURRENCE_DAILY,
)
from custom_components.assist_satellite_alarms.models import AlarmEndpoint, AlarmRecord
from custom_components.assist_satellite_alarms.playback import (
    ActiveAlarm,
    ActivePlaybackTarget,
    PlaybackManager,
)
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter
from custom_components.assist_satellite_alarms.sensor import (
    ActiveAlarmSensor,
    AlarmCountSensor,
    NextAlarmSensor,
)


async def _setup_runtime(
    hass: HomeAssistant,
) -> tuple[MockConfigEntry, AlarmRegistry, AlarmManager, PlaybackManager, SchedulerAdapter]:
    """Set up the small runtime surface used by entity tests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        data={
            CONF_NAME: "Bedroom",
            CONF_ASSIST_SATELLITE: "assist_satellite.bedroom",
            CONF_MEDIA_PLAYER: "media_player.bedroom",
        },
        entry_id="bedroom-entry",
    )
    entry.add_to_hass(hass)
    entry.runtime_data = AlarmEndpoint.from_config_entry(entry)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    manager = AlarmManager(hass, registry, scheduler)
    playback = PlaybackManager(hass, registry, scheduler)
    hass.data[DOMAIN] = {
        DATA_ALARM_MANAGER: manager,
        DATA_PLAYBACK_MANAGER: playback,
    }
    return entry, registry, manager, playback, scheduler


async def test_next_alarm_and_count_entities(hass: HomeAssistant) -> None:
    """Room sensors should expose Scheduler-backed next alarm metadata."""
    entry, registry, _manager, _playback, scheduler = await _setup_runtime(hass)
    alarm_id = "work-alarm"
    entity_id = scheduler.expected_entity_id(alarm_id)
    await registry.async_upsert(
        AlarmRecord(
            alarm_id=alarm_id,
            endpoint_entry_id=entry.entry_id,
            scheduler_entity_id=entity_id,
            name="Work",
            metadata={
                META_TIME: "06:30:00",
                META_RECURRENCE: RECURRENCE_DAILY,
                META_DATE: None,
                META_DAYS: None,
                META_SKIP_NEXT: False,
            },
        )
    )
    hass.states.async_set(
        entity_id,
        "on",
        {
            "tags": [DOMAIN, scheduler.alarm_tag(alarm_id)],
            "next_trigger": "2099-09-30T06:30:00-04:00",
        },
    )

    next_sensor = NextAlarmSensor(hass, entry)
    count_sensor = AlarmCountSensor(hass, entry)

    assert isinstance(next_sensor.native_value, datetime)
    assert next_sensor.native_value == dt_util.parse_datetime(
        "2099-09-30T06:30:00-04:00"
    )
    assert next_sensor.extra_state_attributes["alarm_id"] == alarm_id
    assert next_sensor.extra_state_attributes["name"] == "Work"
    assert next_sensor.extra_state_attributes["recurrence"] == RECURRENCE_DAILY
    assert count_sensor.native_value == 1
    assert count_sensor.extra_state_attributes["enabled_count"] == 1
    assert count_sensor.extra_state_attributes["disabled_count"] == 0


async def test_active_and_ringing_entities(hass: HomeAssistant) -> None:
    """Active alarm entities should reflect room-local playback runtime state."""
    entry, registry, _manager, playback, _scheduler = await _setup_runtime(hass)
    await registry.async_upsert(
        AlarmRecord(
            alarm_id="alarm-1",
            endpoint_entry_id=entry.entry_id,
            name="Wake up",
            metadata={META_TIME: "07:00:00", META_RECURRENCE: RECURRENCE_DAILY},
        )
    )
    playback._active_by_endpoint[entry.entry_id] = ActiveAlarm(
        alarm_id="alarm-1",
        endpoint_entry_id=entry.entry_id,
        playback_mode=PLAYBACK_MODE_ALL,
        targets=[
            ActivePlaybackTarget(
                assist_satellite_entity_id="assist_satellite.bedroom",
                media_player_entity_id="media_player.bedroom",
                previous_volume=0.35,
                touched=True,
            )
        ],
        started_at=dt_util.now(),
    )

    active_sensor = ActiveAlarmSensor(hass, entry)
    ringing_sensor = AlarmRingingBinarySensor(hass, entry)

    assert active_sensor.native_value == "Wake up"
    assert active_sensor.extra_state_attributes["alarm_id"] == "alarm-1"
    assert active_sensor.extra_state_attributes["playback_mode"] == PLAYBACK_MODE_ALL
    assert ringing_sensor.is_on is True
    assert ringing_sensor.extra_state_attributes["active_alarm_id"] == "alarm-1"
