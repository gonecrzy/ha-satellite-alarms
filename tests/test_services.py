"""Tests for Satellite Alarms Home Assistant services."""

from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.alarm_manager import AlarmManager
from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
    EVENT_ALARM_TRIGGERED,
    SCHEDULER_DOMAIN,
    SERVICE_CREATE,
    SERVICE_FIRE,
)
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter
from custom_components.assist_satellite_alarms.services import (
    CREATE_SCHEMA,
    async_register_services,
)


async def _noop(call: ServiceCall) -> None:
    """No-op Scheduler service."""


def test_create_schema_normalizes_time_and_date() -> None:
    """Service input should be normalized before it reaches the manager."""
    result = CREATE_SCHEMA(
        {
            "endpoint_id": "bedroom-entry",
            "time": "6:30",
            "date": "2026-09-30",
        }
    )

    assert result["time"] == "06:30:00"
    assert result["date"] == "2026-09-30"
    assert result["recurrence"] == "once"


async def test_create_service_and_fire_event(hass: HomeAssistant) -> None:
    """Services should create an alarm and route Scheduler fire events."""
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

    registry = AlarmRegistry(hass)
    await registry.async_load()
    manager = AlarmManager(hass, registry, SchedulerAdapter(hass))
    await async_register_services(hass, manager)

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

    assert response["alarm_id"]
    assert response["name"] == "Work"

    events = []
    unsub = hass.bus.async_listen(EVENT_ALARM_TRIGGERED, events.append)
    try:
        fire_response = await hass.services.async_call(
            DOMAIN,
            SERVICE_FIRE,
            {"alarm_id": response["alarm_id"]},
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()
    finally:
        unsub()

    assert fire_response["media_player_entity_id"] == "media_player.bedroom"
    assert len(events) == 1
    assert events[0].data["assist_satellite_entity_id"] == "assist_satellite.bedroom"
