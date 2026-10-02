"""Tests for Satellite Alarms repair issue monitoring."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
    META_RECURRENCE,
    META_TIME,
    RECURRENCE_DAILY,
)
from custom_components.assist_satellite_alarms.models import AlarmRecord
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.repairs import RoomHealthMonitor
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a Bedroom room endpoint."""
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
    return entry


async def test_missing_room_target_issue_clears_when_entity_returns(
    hass: HomeAssistant,
) -> None:
    """A missing configured target should create and then clear a repair issue."""
    entry = _entry(hass)
    registry = AlarmRegistry(hass)
    await registry.async_load()
    monitor = RoomHealthMonitor(hass, entry, registry, SchedulerAdapter(hass))
    issue_registry = ir.async_get(hass)
    issue_id = "bedroom-entry_missing_target_assist_satellite_bedroom"

    monitor.start()
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(domain=DOMAIN, issue_id=issue_id) is not None

    hass.states.async_set("assist_satellite.bedroom", "idle")
    hass.states.async_set("media_player.bedroom", "idle")
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(domain=DOMAIN, issue_id=issue_id) is None
    monitor.stop()


async def test_missing_schedule_issue_clears_when_scheduler_entity_returns(
    hass: HomeAssistant,
) -> None:
    """Alarm metadata without a Scheduler switch should surface as a repair."""
    entry = _entry(hass)
    hass.states.async_set("assist_satellite.bedroom", "idle")
    hass.states.async_set("media_player.bedroom", "idle")

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    alarm_id = "alarm-123"
    await registry.async_upsert(
        AlarmRecord(
            alarm_id=alarm_id,
            endpoint_entry_id=entry.entry_id,
            scheduler_entity_id=scheduler.expected_entity_id(alarm_id),
            name="Work",
            metadata={
                META_TIME: "06:30:00",
                META_RECURRENCE: RECURRENCE_DAILY,
            },
        )
    )

    monitor = RoomHealthMonitor(hass, entry, registry, scheduler)
    issue_registry = ir.async_get(hass)
    issue_id = f"bedroom-entry_missing_schedule_{alarm_id}"
    monitor.start()

    assert issue_registry.async_get_issue(domain=DOMAIN, issue_id=issue_id) is not None

    hass.states.async_set(
        scheduler.expected_entity_id(alarm_id),
        "on",
        {"tags": [DOMAIN, scheduler.alarm_tag(alarm_id)]},
    )
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(domain=DOMAIN, issue_id=issue_id) is None
    monitor.stop()
