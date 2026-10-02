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
    EVENT_ALARM_SKIPPED,
    EVENT_ALARM_STOPPED,
    EVENT_ALARM_TRIGGERED,
    SCHEDULER_DOMAIN,
    SERVICE_CREATE,
    SERVICE_FIRE,
    SERVICE_LIST,
    SERVICE_OVERRIDE_NEXT,
    SERVICE_SKIP_NEXT,
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
    unsub_triggered = hass.bus.async_listen(EVENT_ALARM_TRIGGERED, triggered_events.append)
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
    assert triggered_events[0].data["assist_satellite_entity_id"] == ("assist_satellite.bedroom")
    assert len(stopped_events) == 1


async def test_selected_days_and_list_service(hass: HomeAssistant) -> None:
    """Create/list should expose selected weekdays and multiple alarm metadata."""
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

    async def capture_scheduler(call: ServiceCall) -> None:
        if call.service == "add":
            name = call.data["name"]
            entity_id = "switch.schedule_" + name.lower().replace(" ", "_")
            hass.states.async_set(
                entity_id,
                "on",
                {
                    "tags": call.data.get("tags", []),
                    "next_trigger": "2099-09-30T06:30:00-04:00",
                },
            )

    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, capture_scheduler)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    manager = AlarmManager(hass, registry, scheduler)
    playback = PlaybackManager(hass, registry, scheduler)
    await async_register_services(hass, manager, playback)

    created = await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE,
        {
            "endpoint_id": entry.entry_id,
            "time": "06:30:00",
            "recurrence": "selected_days",
            "days": ["fri", "mon", "wed"],
            "name": "Work",
        },
        blocking=True,
        return_response=True,
    )

    assert created["days"] == ["mon", "wed", "fri"]

    listed = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST,
        {"endpoint_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )

    assert listed["count"] == 1
    assert listed["alarms"][0]["alarm_id"] == created["alarm_id"]
    assert listed["alarms"][0]["name"] == "Work"
    assert listed["alarms"][0]["days"] == ["mon", "wed", "fri"]


async def test_skip_next_service_suppresses_parent_fire(hass: HomeAssistant) -> None:
    """A skipped parent occurrence should not start playback."""
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

    created = await hass.services.async_call(
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

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SKIP_NEXT,
        {"alarm_id": created["alarm_id"]},
        blocking=True,
        return_response=True,
    )

    events = []
    unsub = hass.bus.async_listen(EVENT_ALARM_SKIPPED, events.append)
    try:
        fired = await hass.services.async_call(
            DOMAIN,
            SERVICE_FIRE,
            {"alarm_id": created["alarm_id"]},
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()
    finally:
        unsub()

    assert fired["skipped"] is True
    assert fired["ringing"] is False
    assert playback.active_for_endpoint(entry.entry_id) is None
    assert len(events) == 1


async def test_override_next_service_creates_temporary_occurrence(
    hass: HomeAssistant,
) -> None:
    """Override service should create a transient schedule and preserve the parent."""
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

    calls = []

    async def capture(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, capture)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    manager = AlarmManager(hass, registry, scheduler)
    playback = PlaybackManager(hass, registry, scheduler)
    await async_register_services(hass, manager, playback)

    created = await hass.services.async_call(
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
    parent_entity = scheduler.expected_entity_id(created["alarm_id"])
    hass.states.async_set(
        parent_entity,
        "on",
        {
            "tags": [DOMAIN, scheduler.alarm_tag(created["alarm_id"])],
            "next_trigger": "2099-09-30T06:30:00-04:00",
        },
    )
    calls.clear()

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_OVERRIDE_NEXT,
        {
            "alarm_id": created["alarm_id"],
            "time": "07:00:00",
            "date": "2099-09-30",
        },
        blocking=True,
        return_response=True,
    )

    assert response["skip_next"] is True
    assert response["override_occurrence_id"]
    assert response["override_scheduler_entity_id"].startswith(
        "switch.schedule_assist_satellite_alarm_override_"
    )
    assert calls[0][0] == "add"
    assert calls[0][1]["timeslots"][0]["start"] == "07:00:00"


async def test_snooze_occurrence_bypasses_parent_skip_marker(
    hass: HomeAssistant,
) -> None:
    """Transient snooze callbacks must ring even when the parent next occurrence is skipped."""
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

    created = await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE,
        {
            "endpoint_id": entry.entry_id,
            "time": "06:30:00",
            "recurrence": "daily",
        },
        blocking=True,
        return_response=True,
    )
    await manager.async_set_skip_next(created["alarm_id"])

    fired = await hass.services.async_call(
        DOMAIN,
        SERVICE_FIRE,
        {
            "alarm_id": created["alarm_id"],
            "occurrence": "snooze",
            "occurrence_id": "snooze-1",
        },
        blocking=True,
        return_response=True,
    )
    await asyncio.sleep(0)

    assert fired["ringing"] is True
    assert fired["skipped"] is False
    assert manager.registry.get(created["alarm_id"]).metadata["skip_next"] is True

    await playback.async_stop(alarm_id=created["alarm_id"])
