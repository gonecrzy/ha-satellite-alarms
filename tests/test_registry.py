"""Tests for the Satellite Alarms metadata registry."""

from homeassistant.core import HomeAssistant

from custom_components.satellite_alarms.models import AlarmRecord
from custom_components.satellite_alarms.registry import AlarmRegistry


async def test_registry_persists_alarm_records(hass: HomeAssistant) -> None:
    """Alarm metadata should survive a registry reload."""
    registry = AlarmRegistry(hass)
    await registry.async_load()

    record = AlarmRecord(
        alarm_id="alarm-123",
        endpoint_entry_id="entry-456",
        scheduler_entity_id="switch.schedule_bedroom",
        name="Bedroom wakeup",
        metadata={"volume": 0.65},
    )

    await registry.async_upsert(record)

    reloaded = AlarmRegistry(hass)
    await reloaded.async_load()

    assert reloaded.get("alarm-123") == record
    assert reloaded.for_endpoint("entry-456") == (record,)

    assert await reloaded.async_remove("alarm-123") is True
    assert await reloaded.async_remove("alarm-123") is False
