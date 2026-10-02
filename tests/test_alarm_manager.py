"""Tests for the Satellite Alarms manager."""

import pytest
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.alarm_manager import (
    AlarmManager,
    AlarmNotFoundError,
    EndpointNotFoundError,
)
from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
    META_DATE,
    META_RECURRENCE,
    META_TIME,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_WEEKDAYS,
    SCHEDULER_DOMAIN,
)
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter


def _add_endpoint(hass: HomeAssistant) -> MockConfigEntry:
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


async def _manager(hass: HomeAssistant) -> tuple[AlarmManager, list[tuple[str, dict]]]:
    calls: list[tuple[str, dict]] = []

    async def capture_scheduler(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    async def capture_switch(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, capture_scheduler)
    hass.services.async_register("switch", SERVICE_TURN_ON, capture_switch)
    hass.services.async_register("switch", SERVICE_TURN_OFF, capture_switch)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    return AlarmManager(hass, registry, SchedulerAdapter(hass)), calls


async def test_create_alarm(hass: HomeAssistant) -> None:
    """Creating an alarm should persist metadata and create a Scheduler schedule."""
    entry = _add_endpoint(hass)
    manager, calls = await _manager(hass)

    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="06:30:00",
        recurrence=RECURRENCE_ONCE,
        date_value="2099-09-30",
        name="Work",
    )

    assert manager.registry.get(record.alarm_id) == record
    assert record.endpoint_entry_id == entry.entry_id
    assert record.name == "Work"
    assert record.metadata == {
        META_TIME: "06:30:00",
        META_RECURRENCE: RECURRENCE_ONCE,
        META_DATE: "2099-09-30",
    }
    assert calls[0][0] == "add"
    assert calls[0][1]["start_date"] == "2099-09-30"
    assert calls[0][1]["timeslots"][0]["actions"][0]["service"] == f"{DOMAIN}.fire"


async def test_create_alarm_uses_endpoint_default_name(hass: HomeAssistant) -> None:
    """Unnamed alarms should use the endpoint name."""
    entry = _add_endpoint(hass)
    manager, _ = await _manager(hass)

    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="08:00:00",
        recurrence=RECURRENCE_DAILY,
    )

    assert record.name == "Bedroom alarm"
    assert record.metadata[META_DATE] is None


async def test_create_rolls_back_registry_on_scheduler_failure(hass: HomeAssistant) -> None:
    """A failed Scheduler create must not leave alarm metadata behind."""
    entry = _add_endpoint(hass)

    async def fail_add(call: ServiceCall) -> None:
        raise HomeAssistantError("scheduler failed")

    hass.services.async_register(SCHEDULER_DOMAIN, "add", fail_add)
    hass.services.async_register(SCHEDULER_DOMAIN, "edit", _noop)
    hass.services.async_register(SCHEDULER_DOMAIN, "remove", _noop)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    manager = AlarmManager(hass, registry, SchedulerAdapter(hass))

    with pytest.raises(HomeAssistantError):
        await manager.async_create(
            endpoint_id=entry.entry_id,
            time_value="08:00:00",
            recurrence=RECURRENCE_DAILY,
        )

    assert registry.all() == ()


async def _noop(call: ServiceCall) -> None:
    """No-op service."""


async def test_update_delete_enable_disable(hass: HomeAssistant) -> None:
    """Alarm management should delegate changes to Scheduler Component."""
    entry = _add_endpoint(hass)
    manager, calls = await _manager(hass)
    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="07:00:00",
        recurrence=RECURRENCE_DAILY,
    )
    calls.clear()

    updated = await manager.async_update(
        alarm_id=record.alarm_id,
        time_value="07:30:00",
        recurrence=RECURRENCE_WEEKDAYS,
        name="Weekday work",
    )

    assert updated.name == "Weekday work"
    assert updated.metadata[META_TIME] == "07:30:00"
    assert updated.metadata[META_RECURRENCE] == RECURRENCE_WEEKDAYS
    assert calls[0][0] == "edit"
    assert calls[0][1]["weekdays"] == ["workday"]

    await manager.async_set_enabled(record.alarm_id, False)
    await manager.async_set_enabled(record.alarm_id, True)
    assert calls[1][0] == SERVICE_TURN_OFF
    assert calls[2][0] == SERVICE_TURN_ON

    await manager.async_delete(record.alarm_id)
    assert calls[3][0] == "remove"
    assert manager.registry.get(record.alarm_id) is None


async def test_update_repeating_alarm_to_once_resolves_date(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Switching recurrence to once should resolve the next local date."""
    entry = _add_endpoint(hass)
    manager, calls = await _manager(hass)
    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="07:00:00",
        recurrence=RECURRENCE_DAILY,
    )
    calls.clear()
    monkeypatch.setattr(AlarmManager, "_next_date", staticmethod(lambda _time: "2099-10-01"))

    updated = await manager.async_update(
        alarm_id=record.alarm_id,
        recurrence=RECURRENCE_ONCE,
    )

    assert updated.metadata[META_DATE] == "2099-10-01"
    assert calls[0][1]["repeat_type"] == "single"
    assert calls[0][1]["start_date"] == "2099-10-01"


async def test_manager_validation_errors(hass: HomeAssistant) -> None:
    """Unknown endpoints and alarms should fail clearly."""
    manager, _ = await _manager(hass)

    with pytest.raises(EndpointNotFoundError):
        await manager.async_create(
            endpoint_id="missing",
            time_value="07:00:00",
            recurrence=RECURRENCE_DAILY,
        )

    with pytest.raises(AlarmNotFoundError):
        await manager.async_delete("missing")


async def test_reconcile_scheduler_entity_mapping(hass: HomeAssistant) -> None:
    """Stable Scheduler tags should repair cached entity IDs after restart."""
    entry = _add_endpoint(hass)
    manager, _ = await _manager(hass)
    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="07:00:00",
        recurrence=RECURRENCE_DAILY,
    )
    record.scheduler_entity_id = "switch.stale"
    await manager.registry.async_upsert(record)

    actual_entity_id = "switch.schedule_recreated"
    hass.states.async_set(
        actual_entity_id,
        "on",
        {
            "tags": [DOMAIN, manager.scheduler.alarm_tag(record.alarm_id)],
            "next_trigger": "2099-09-30T07:00:00-04:00",
        },
    )

    matched, missing = await manager.async_reconcile()

    assert (matched, missing) == (1, 0)
    assert manager.registry.get(record.alarm_id).scheduler_entity_id == actual_entity_id


async def test_reconcile_reports_missing_scheduler_schedule(hass: HomeAssistant) -> None:
    """Reconciliation should report missing Scheduler schedules without deleting metadata."""
    entry = _add_endpoint(hass)
    manager, _ = await _manager(hass)
    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="07:00:00",
        recurrence=RECURRENCE_DAILY,
    )

    matched, missing = await manager.async_reconcile()

    assert (matched, missing) == (0, 1)
    assert manager.registry.get(record.alarm_id) == record


async def test_create_rejects_past_one_time_alarm(hass: HomeAssistant) -> None:
    """Explicit one-time alarm dates in the past should be rejected."""
    entry = _add_endpoint(hass)
    manager, calls = await _manager(hass)

    with pytest.raises(ValueError, match="future"):
        await manager.async_create(
            endpoint_id=entry.entry_id,
            time_value="07:00:00",
            recurrence=RECURRENCE_ONCE,
            date_value="2000-01-01",
        )

    assert calls == []
    assert manager.registry.all() == ()


async def test_runtime_scheduler_rename_is_resolved_by_tag(hass: HomeAssistant) -> None:
    """Operations should use the stable tag if the Scheduler entity ID changes."""
    entry = _add_endpoint(hass)
    manager, calls = await _manager(hass)
    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="07:00:00",
        recurrence=RECURRENCE_DAILY,
    )
    calls.clear()

    renamed_entity_id = "switch.user_renamed_schedule"
    hass.states.async_set(
        renamed_entity_id,
        "on",
        {"tags": [DOMAIN, manager.scheduler.alarm_tag(record.alarm_id)]},
    )

    await manager.async_update(alarm_id=record.alarm_id, time_value="07:15:00")

    assert calls[0][0] == "edit"
    assert calls[0][1]["entity_id"] == renamed_entity_id


async def test_next_alarm_for_endpoint_uses_scheduler_next_trigger(
    hass: HomeAssistant,
) -> None:
    """Next-alarm lookup should use Scheduler Component as its source of truth."""
    entry = _add_endpoint(hass)
    manager, _ = await _manager(hass)
    record = await manager.async_create(
        endpoint_id=entry.entry_id,
        time_value="07:00:00",
        recurrence=RECURRENCE_DAILY,
    )

    entity_id = manager.scheduler.expected_entity_id(record.alarm_id)
    hass.states.async_set(
        entity_id,
        "on",
        {
            "tags": [DOMAIN, manager.scheduler.alarm_tag(record.alarm_id)],
            "next_trigger": "2099-09-30T07:00:00-04:00",
        },
    )

    next_alarm = manager.next_alarm_for_endpoint(entry.entry_id)

    assert next_alarm is not None
    next_record, trigger = next_alarm
    assert next_record.alarm_id == record.alarm_id
    assert trigger.isoformat() == "2099-09-30T07:00:00-04:00"
