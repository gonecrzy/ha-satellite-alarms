"""Tests for the Scheduler Component adapter."""

from datetime import datetime

import pytest
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.assist_satellite_alarms.const import (
    DOMAIN,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_SELECTED_DAYS,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKENDS,
    SCHEDULER_DOMAIN,
)
from custom_components.assist_satellite_alarms.scheduler_adapter import (
    SchedulerAdapter,
    SchedulerNotReadyError,
)


async def _noop_service(call: ServiceCall) -> None:
    """Handle a test service call."""


async def test_scheduler_adapter_requires_services(hass: HomeAssistant) -> None:
    """The adapter should reject an incomplete Scheduler service API."""
    adapter = SchedulerAdapter(hass)

    assert adapter.is_ready is False

    with pytest.raises(SchedulerNotReadyError):
        adapter.ensure_ready()

    hass.services.async_register(SCHEDULER_DOMAIN, "add", _noop_service)
    hass.services.async_register(SCHEDULER_DOMAIN, "edit", _noop_service)

    assert adapter.is_ready is False

    hass.services.async_register(SCHEDULER_DOMAIN, "remove", _noop_service)

    assert adapter.is_ready is True
    adapter.ensure_ready()


@pytest.mark.parametrize(
    ("recurrence", "date", "weekdays", "repeat_type"),
    [
        (RECURRENCE_ONCE, "2026-09-30", ["daily"], "single"),
        (RECURRENCE_DAILY, None, ["daily"], "repeat"),
        (RECURRENCE_WEEKDAYS, None, ["workday"], "repeat"),
        (RECURRENCE_WEEKENDS, None, ["weekend"], "repeat"),
    ],
)
def test_build_schedule_payload(
    recurrence: str,
    date: str | None,
    weekdays: list[str],
    repeat_type: str,
) -> None:
    """Recurrence values should translate to Scheduler Component correctly."""
    payload = SchedulerAdapter.build_schedule_payload(
        alarm_id="abc123",
        time="06:30:00",
        recurrence=recurrence,
        date=date,
    )

    assert payload["weekdays"] == weekdays
    assert payload["repeat_type"] == repeat_type
    assert payload["start_date"] == date
    assert payload["end_date"] == date
    assert payload["tags"] == [DOMAIN, f"{DOMAIN}:abc123"]
    assert payload["timeslots"] == [
        {
            "start": "06:30:00",
            "actions": [
                {
                    "service": f"{DOMAIN}.fire",
                    "service_data": {"alarm_id": "abc123"},
                }
            ],
        }
    ]
    assert payload["name"] == "Assist Satellite Alarm abc123"


def test_build_snooze_payload() -> None:
    """Snooze should create a transient single schedule tied to its parent."""
    payload = SchedulerAdapter.build_snooze_payload(
        alarm_id="abc123",
        occurrence_id="snooze456",
        trigger_at=datetime.fromisoformat("2099-09-30T06:40:00-04:00"),
    )

    assert payload["repeat_type"] == "single"
    assert payload["start_date"] == "2099-09-30"
    assert payload["end_date"] == "2099-09-30"
    assert payload["timeslots"][0]["start"] == "06:40:00"
    assert payload["timeslots"][0]["actions"][0] == {
        "service": f"{DOMAIN}.fire",
        "service_data": {"alarm_id": "abc123"},
    }
    assert f"{DOMAIN}:snooze:snooze456" in payload["tags"]
    assert f"{DOMAIN}:parent:abc123" in payload["tags"]


def test_one_time_schedule_requires_date() -> None:
    """One-time Scheduler payloads require an explicit resolved date."""
    with pytest.raises(ValueError):
        SchedulerAdapter.build_schedule_payload(
            alarm_id="abc123",
            time="06:30:00",
            recurrence=RECURRENCE_ONCE,
            date=None,
        )


async def test_scheduler_service_calls(hass: HomeAssistant) -> None:
    """The adapter should call Scheduler and switch services with stable IDs."""
    calls: list[tuple[str, dict]] = []

    async def capture_scheduler(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    async def capture_switch(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, capture_scheduler)
    hass.services.async_register("switch", SERVICE_TURN_ON, capture_switch)
    hass.services.async_register("switch", SERVICE_TURN_OFF, capture_switch)

    adapter = SchedulerAdapter(hass)
    entity_id = await adapter.async_create_schedule(
        alarm_id="abc123",
        time="07:00:00",
        recurrence=RECURRENCE_DAILY,
        date=None,
    )

    assert entity_id == "switch.schedule_assist_satellite_alarm_abc123"
    assert calls[0][0] == "add"
    assert calls[0][1]["repeat_type"] == "repeat"

    await adapter.async_update_schedule(
        entity_id=entity_id,
        alarm_id="abc123",
        time="08:15:00",
        recurrence=RECURRENCE_WEEKDAYS,
        date=None,
    )
    assert calls[1][0] == "edit"
    assert calls[1][1]["entity_id"] == entity_id
    assert "name" not in calls[1][1]

    await adapter.async_set_enabled(entity_id, False)
    await adapter.async_set_enabled(entity_id, True)
    assert calls[2] == (SERVICE_TURN_OFF, {"entity_id": entity_id})
    assert calls[3] == (SERVICE_TURN_ON, {"entity_id": entity_id})

    await adapter.async_remove_schedule(entity_id)
    assert calls[4] == ("remove", {"entity_id": entity_id})


def test_scheduler_entity_lookup_and_next_trigger(hass: HomeAssistant) -> None:
    """Stable tags should recover Scheduler entities and next trigger data."""
    adapter = SchedulerAdapter(hass)
    entity_id = "switch.schedule_test"
    hass.states.async_set(
        entity_id,
        "on",
        {
            "tags": [DOMAIN, adapter.alarm_tag("abc123")],
            "next_trigger": "2026-09-30T06:30:00-04:00",
        },
    )

    assert adapter.find_entity_id("abc123") == entity_id
    assert adapter.find_entity_id("missing") is None
    assert adapter.next_trigger(entity_id) == "2026-09-30T06:30:00-04:00"
    assert adapter.next_trigger("switch.missing") is None


def test_build_selected_days_schedule_payload() -> None:
    """Selected weekdays should pass through to Scheduler in canonical order."""
    payload = SchedulerAdapter.build_schedule_payload(
        alarm_id="abc123",
        time="06:30:00",
        recurrence=RECURRENCE_SELECTED_DAYS,
        date=None,
        days=["fri", "mon", "wed"],
    )

    assert payload["weekdays"] == ["mon", "wed", "fri"]
    assert payload["repeat_type"] == "repeat"


def test_selected_days_schedule_requires_valid_days() -> None:
    """Selected-day recurrence should reject empty and invalid weekday lists."""
    with pytest.raises(ValueError, match="at least one weekday"):
        SchedulerAdapter.build_schedule_payload(
            alarm_id="abc123",
            time="06:30:00",
            recurrence=RECURRENCE_SELECTED_DAYS,
            date=None,
            days=[],
        )

    with pytest.raises(ValueError, match="invalid weekday"):
        SchedulerAdapter.build_schedule_payload(
            alarm_id="abc123",
            time="06:30:00",
            recurrence=RECURRENCE_SELECTED_DAYS,
            date=None,
            days=["mon", "noday"],
        )
