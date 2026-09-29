"""Tests for Satellite Alarms Home Assistant services."""

import asyncio

from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.alarm_manager import AlarmManager
from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
    EVENT_ALARM_STOPPED,
    EVENT_ALARM_TRIGGERED,
    SCHEDULER_DOMAIN,
    SERVICE_CREATE,
    SERVICE_FIRE,
    SERVICE_STOP,
)
from custom_components.assist_satellite_alarms.playback import PlaybackManager
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter
from custom_components.assist_satellite_alarms.services import (
    ACTIVE_ALARM_SCHEMA,
    CREATE_SCHEMA,
    async_register_services,
)


async def _noop(call: ServiceCall) -> None:
    """No-op service."""


def test_create_schema_normalizes_time_and_date() -> None:
    """Service input should be normalized before it reaches the manager."""
    result = CREATE_SCHEMA(
        {
            "endpoint_id": "bedroom-entry",
            "time": "6:30",
            "date": "2099-09-30",
        }
    )

    assert result["time"] == "06:30:00"
    assert result["date"] == "2099-09-30"
    assert result["recurrence"] == "once"


def test_active_alarm_schema_requires_one_selector() -> None:
    """Stop/snooze selectors must be unambiguous."""
    assert ACTIVE_ALARM_SCHEMA({"alarm_id": "abc"})["alarm_id"] == "abc"
    assert ACTIVE_ALARM_SCHEMA({"endpoint_id": "room"})["endpoint_id"] == "room"


async def test_create_fire_and_stop_services(hass: HomeAssistant) -> None:
    """Services should create, ring, route, and stop an alarm."""
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

    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, _noop)
    hass.services.async_register("media_player", "volume_set", _noop)
    hass.services.async_register("media_player", "media_stop", _noop)
    hass.services.async_register("assist_satellite", "announce", _noop)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    manager = AlarmManager(hass, registry, scheduler)
    playback = PlaybackManager(hass, registry, scheduler)
    await async_register_services(hass, manager, playback)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE,
        {
            "endpoint_id": entry.entry_id,
            "time": "06:30:00",
            "recurrence": "daily",
            "name": "Work",
        },
        blocking=True,
        return_response=True,
    )

    triggered_events = []
    stopped_events = []
    unsub_triggered = hass.bus.async_listen(
        EVENT_ALARM_TRIGGERED, triggered_events.append
    )
    unsub_stopped = hass.bus.async_listen(EVENT_ALARM_STOPPED, stopped_events.append)
    try:
        fire_response = await hass.services.async_call(
            DOMAIN,
            SERVICE_FIRE,
            {"alarm_id": response["alarm_id"]},
            blocking=True,
            return_response=True,
        )
        await asyncio.sleep(0)

        stop_response = await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP,
            {"alarm_id": response["alarm_id"]},
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()
    finally:
        unsub_triggered()
        unsub_stopped()

    assert fire_response["media_player_entity_id"] == "media_player.bedroom"
    assert fire_response["ringing"] is True
    assert stop_response["stopped"] is True
    assert len(triggered_events) == 1
    assert triggered_events[0].data["assist_satellite_entity_id"] == (
        "assist_satellite.bedroom"
    )
    assert len(stopped_events) == 1
