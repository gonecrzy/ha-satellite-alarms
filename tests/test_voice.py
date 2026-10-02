"""Tests for deterministic Assist voice alarm commands."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.conversation import ConversationInput
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.alarm_manager import AlarmManager
from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    SCHEDULER_DOMAIN,
)
from custom_components.assist_satellite_alarms.models import AlarmRecord
from custom_components.assist_satellite_alarms.playback import PlaybackManager
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter
from custom_components.assist_satellite_alarms.voice import (
    VoiceController,
    format_clock_time,
    parse_alarm_time,
    parse_snooze_minutes,
)


def _add_endpoint(hass: HomeAssistant) -> MockConfigEntry:
    """Add a configured Bedroom endpoint."""
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


def _input(
    *,
    satellite_id: str | None = "assist_satellite.bedroom",
    device_id: str | None = None,
) -> ConversationInput:
    """Create a conversation input matching a voice-satellite request."""
    return ConversationInput(
        text="test",
        context=Context(),
        conversation_id=None,
        device_id=device_id,
        satellite_id=satellite_id,
        language="en",
        agent_id="conversation.home_assistant",
    )


def _result(**slots: str):
    """Create the small RecognizeResult surface used by VoiceController."""
    return SimpleNamespace(
        entities={name: SimpleNamespace(value=value, text=value) for name, value in slots.items()}
    )


async def _manager(
    hass: HomeAssistant,
) -> tuple[AlarmManager, PlaybackManager, list[tuple[str, dict]]]:
    """Create real alarm/playback managers with captured Scheduler actions."""
    calls: list[tuple[str, dict]] = []

    async def capture(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, capture)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    return (
        AlarmManager(hass, registry, scheduler),
        PlaybackManager(hass, registry, scheduler),
        calls,
    )


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("6 AM", "06:00:00"),
        ("6:30 p.m.", "18:30:00"),
        ("six thirty", "06:30:00"),
        ("six oh five am", "06:05:00"),
        ("18:45", "18:45:00"),
        ("noon", "12:00:00"),
        ("midnight", "00:00:00"),
        ("six thirty in the morning", "06:30:00"),
        ("seven in the evening", "19:00:00"),
    ],
)
def test_parse_alarm_time(spoken: str, expected: str) -> None:
    """Common voice time forms should normalize deterministically."""
    assert parse_alarm_time(spoken) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("10 minutes", 10),
        ("ten", 10),
        ("half an hour", 30),
        ("an hour", 60),
        ("1 hour 30 minutes", 90),
        ("one hour and ten minutes", 70),
    ],
)
def test_parse_snooze_minutes(spoken: str, expected: int) -> None:
    """Common snooze durations should normalize to minutes."""
    assert parse_snooze_minutes(spoken) == expected


def test_format_clock_time() -> None:
    """Clock times should produce concise spoken confirmations."""
    assert format_clock_time("06:00:00") == "6 AM"
    assert format_clock_time("18:30:00") == "6:30 PM"


async def test_voice_create_uses_originating_satellite(hass: HomeAssistant) -> None:
    """A spoken alarm should belong to the endpoint for the originating satellite."""
    entry = _add_endpoint(hass)
    manager, playback, calls = await _manager(hass)
    voice = VoiceController(hass, manager, playback)

    response = await voice.async_create_alarm(
        _input(),
        _result(time="6:30 am"),
        recurrence=RECURRENCE_ONCE,
        date_offset=1,
    )

    assert response == "Alarm set for 6:30 AM."
    records = manager.registry.for_endpoint(entry.entry_id)
    assert len(records) == 1
    assert calls[0][0] == "add"
    assert calls[0][1]["start_date"] == (dt_util.now().date() + timedelta(days=1)).isoformat()
    assert calls[0][1]["timeslots"][0]["start"] == "06:30:00"


async def test_voice_create_recurring_alarm(hass: HomeAssistant) -> None:
    """Recurring voice commands should map directly to Scheduler recurrence."""
    _add_endpoint(hass)
    manager, playback, calls = await _manager(hass)
    voice = VoiceController(hass, manager, playback)

    response = await voice.async_create_alarm(
        _input(),
        _result(time="six thirty"),
        recurrence=RECURRENCE_DAILY,
        date_offset=None,
    )

    assert response == "Alarm set for 6:30 AM every day."
    assert calls[0][1]["repeat_type"] == "repeat"
    assert calls[0][1]["weekdays"] == ["daily"]


async def test_voice_refuses_unmapped_satellite(hass: HomeAssistant) -> None:
    """Voice routing must not guess when the originating satellite is unknown."""
    _add_endpoint(hass)
    manager, playback, calls = await _manager(hass)
    voice = VoiceController(hass, manager, playback)

    response = await voice.async_create_alarm(
        _input(satellite_id="assist_satellite.unknown"),
        _result(time="6 am"),
        recurrence=RECURRENCE_ONCE,
        date_offset=1,
    )

    assert response == ("I couldn't match this voice satellite to a Satellite Alarms room.")
    assert calls == []
    assert manager.registry.all() == ()


async def test_voice_stop_and_snooze_are_endpoint_local(hass: HomeAssistant) -> None:
    """Stop and snooze should resolve the originating endpoint, not global state."""
    entry = _add_endpoint(hass)
    playback = MagicMock()
    playback.async_stop = AsyncMock()
    playback.async_snooze = AsyncMock(
        return_value=(SimpleNamespace(alarm_id="abc"), 15, "switch.snooze")
    )
    voice = VoiceController(hass, MagicMock(), playback)

    assert await voice.async_stop(_input(), _result()) == "Alarm stopped."
    playback.async_stop.assert_awaited_once_with(endpoint_id=entry.entry_id)

    assert (
        await voice.async_snooze_for(_input(), _result(duration="15 minutes"))
        == "Snoozed for 15 minutes."
    )
    playback.async_snooze.assert_awaited_once_with(
        endpoint_id=entry.entry_id,
        minutes=15,
    )


async def test_voice_next_and_cancel_next(hass: HomeAssistant) -> None:
    """Next/cancel commands should operate only on the originating endpoint."""
    entry = _add_endpoint(hass)
    trigger = dt_util.now() + timedelta(days=1, hours=1)
    record = AlarmRecord(
        alarm_id="abc123",
        endpoint_entry_id=entry.entry_id,
        name="Bedroom alarm",
    )
    manager = MagicMock()
    manager.next_alarm_for_endpoint.return_value = (record, trigger)
    manager.async_delete = AsyncMock()
    voice = VoiceController(hass, manager, MagicMock())

    response = await voice.async_next_alarm(_input(), _result())
    assert response.startswith("Your next alarm is at ")

    response = await voice.async_cancel_next(_input(), _result())
    assert response.startswith("Canceled the alarm at ")
    manager.async_delete.assert_awaited_once_with("abc123")


def test_voice_registers_and_unregisters_sentence_groups(hass: HomeAssistant, monkeypatch) -> None:
    """Voice controller should own and clean up its sentence registrations."""
    unregister_callbacks = [MagicMock() for _ in range(11)]
    agent_manager = MagicMock()
    agent_manager.register_trigger.side_effect = unregister_callbacks

    monkeypatch.setattr(
        "custom_components.assist_satellite_alarms.voice.get_agent_manager",
        lambda _hass: agent_manager,
    )

    voice = VoiceController(hass, MagicMock(), MagicMock())
    voice.register()

    assert agent_manager.register_trigger.call_count == 11

    voice.unregister()
    for unregister in unregister_callbacks:
        unregister.assert_called_once_with()
