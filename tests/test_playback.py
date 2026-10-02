"""Tests for alarm playback, stop, and snooze behavior."""

import asyncio

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.const import (
    BUILTIN_ALARM_MEDIA_URL,
    CONF_ADDITIONAL_PLAYBACK_TARGETS,
    CONF_ASSIST_SATELLITE,
    CONF_DEFAULT_ALARM_MEDIA,
    CONF_DEFAULT_SNOOZE_MINUTES,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    CONF_PLAYBACK_MODE,
    CONF_VOLUME_RAMP_ENABLED,
    DOMAIN,
    META_ALARM_MEDIA,
    META_ALARM_VOLUME,
    META_DATE,
    META_FAILURE_ACTIONS,
    META_POST_ACTIONS,
    META_PRE_ACTIONS,
    META_RECURRENCE,
    META_SNOOZE_MINUTES,
    META_TIME,
    PLAYBACK_MODE_ALL,
    PLAYBACK_MODE_FALLBACK,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    SCHEDULER_DOMAIN,
)
from custom_components.assist_satellite_alarms.models import AlarmRecord
from custom_components.assist_satellite_alarms.playback import (
    AlarmAlreadyRingingError,
    PlaybackError,
    PlaybackManager,
)
from custom_components.assist_satellite_alarms.registry import AlarmRegistry
from custom_components.assist_satellite_alarms.scheduler_adapter import SchedulerAdapter


def _add_endpoint(
    hass: HomeAssistant,
    *,
    entry_id: str = "bedroom-entry",
    satellite: str = "assist_satellite.bedroom",
    player: str = "media_player.bedroom",
    options: dict | None = None,
    additional_targets: list[dict] | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=entry_id,
        data={
            CONF_NAME: entry_id,
            CONF_ASSIST_SATELLITE: satellite,
            CONF_MEDIA_PLAYER: player,
            CONF_ADDITIONAL_PLAYBACK_TARGETS: additional_targets or [],
        },
        options=options or {},
        entry_id=entry_id,
    )
    entry.add_to_hass(hass)
    return entry


async def _registry_with_alarm(
    hass: HomeAssistant,
    *,
    alarm_id: str,
    endpoint_id: str,
    recurrence: str = RECURRENCE_DAILY,
) -> AlarmRegistry:
    registry = AlarmRegistry(hass)
    await registry.async_load()
    await registry.async_upsert(
        AlarmRecord(
            alarm_id=alarm_id,
            endpoint_entry_id=endpoint_id,
            scheduler_entity_id=f"switch.schedule_{alarm_id}",
            name="Test",
            metadata={
                META_TIME: "07:00:00",
                META_RECURRENCE: recurrence,
                META_DATE: "2099-09-30" if recurrence == RECURRENCE_ONCE else None,
            },
        )
    )
    return registry


def _register_playback_services(
    hass: HomeAssistant,
) -> list[tuple[str, str, dict]]:
    calls: list[tuple[str, str, dict]] = []

    async def capture_media(call: ServiceCall) -> None:
        calls.append(("media_player", call.service, dict(call.data)))

    async def capture_announce(call: ServiceCall) -> None:
        calls.append(("assist_satellite", call.service, dict(call.data)))

    async def capture_scheduler(call: ServiceCall) -> None:
        calls.append(("scheduler", call.service, dict(call.data)))

    hass.services.async_register("media_player", "volume_set", capture_media)
    hass.services.async_register("media_player", "media_stop", capture_media)
    hass.services.async_register("assist_satellite", "announce", capture_announce)
    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, capture_scheduler)

    return calls


async def test_start_and_stop_restores_volume(hass: HomeAssistant) -> None:
    """Stopping an alarm should restore the previous media-player volume."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.35})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    active = await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")

    assert active.previous_volume == 0.35
    assert playback.active_for_endpoint(entry.entry_id) is None

    volume_levels = [
        call[2]["volume_level"] for call in calls if call[:2] == ("media_player", "volume_set")
    ]
    assert volume_levels[0] == 0.2
    assert volume_levels[-1] == 0.35
    assert any(call[:2] == ("media_player", "media_stop") for call in calls)


async def test_default_alarm_uses_bundled_media(hass: HomeAssistant) -> None:
    """The default endpoint should use the bundled alarm media."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")

    announce = next(call for call in calls if call[:2] == ("assist_satellite", "announce"))
    assert announce[2]["entity_id"] == "assist_satellite.bedroom"
    assert announce[2]["media_id"] == BUILTIN_ALARM_MEDIA_URL
    assert announce[2]["preannounce"] is False
    assert "message" not in announce[2]


async def test_empty_alarm_media_uses_spoken_fallback(hass: HomeAssistant) -> None:
    """Explicitly empty media should fall back to the configured spoken message."""
    entry = _add_endpoint(hass, options={CONF_DEFAULT_ALARM_MEDIA: ""})
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")

    announce = next(call for call in calls if call[:2] == ("assist_satellite", "announce"))
    assert announce[2]["message"] == "Alarm"
    assert announce[2]["preannounce"] is True


async def test_configured_alarm_media_is_announced_without_preannounce(
    hass: HomeAssistant,
) -> None:
    """Configured alarm media should be used instead of the spoken fallback."""
    entry = _add_endpoint(
        hass,
        options={CONF_DEFAULT_ALARM_MEDIA: "media-source://media_source/local/alarm.mp3"},
    )
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")

    announce = next(call for call in calls if call[:2] == ("assist_satellite", "announce"))
    assert announce[2]["media_id"] == "media-source://media_source/local/alarm.mp3"
    assert announce[2]["preannounce"] is False
    assert "message" not in announce[2]


async def test_snooze_creates_transient_schedule_and_preserves_one_time_alarm(
    hass: HomeAssistant,
) -> None:
    """Snooze should use Scheduler Component without creating another alarm record."""
    entry = _add_endpoint(
        hass,
        options={CONF_DEFAULT_SNOOZE_MINUTES: 7},
    )
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(
        hass,
        alarm_id="alarm-1",
        endpoint_id=entry.entry_id,
        recurrence=RECURRENCE_ONCE,
    )
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    active, minutes, snooze_entity_id = await playback.async_snooze(alarm_id="alarm-1")

    assert active.finish_reason == "snooze"
    assert minutes == 7
    assert snooze_entity_id.startswith("switch.schedule_assist_satellite_alarm_snooze_")
    assert registry.get("alarm-1") is not None
    assert len(registry.all()) == 1

    add_call = next(
        call
        for call in calls
        if call[:2] == ("scheduler", "add")
        and any(":snooze:" in tag for tag in call[2].get("tags", []))
    )
    action = add_call[2]["timeslots"][0]["actions"][0]
    assert action["service"] == f"{DOMAIN}.fire"
    assert action["service_data"]["alarm_id"] == "alarm-1"
    assert f"{DOMAIN}:parent:alarm-1" in add_call[2]["tags"]


async def test_stop_completes_one_time_alarm_record(hass: HomeAssistant) -> None:
    """Stopping a completed one-time alarm should remove its metadata record."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    _register_playback_services(hass)
    registry = await _registry_with_alarm(
        hass,
        alarm_id="alarm-1",
        endpoint_id=entry.entry_id,
        recurrence=RECURRENCE_ONCE,
    )
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")

    assert registry.get("alarm-1") is None


async def test_two_rooms_ring_independently(hass: HomeAssistant) -> None:
    """Stopping one endpoint must not affect another active endpoint."""
    first = _add_endpoint(hass)
    second = _add_endpoint(
        hass,
        entry_id="office-entry",
        satellite="assist_satellite.office",
        player="media_player.office",
    )
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    hass.states.async_set("media_player.office", "idle", {"volume_level": 0.5})
    _register_playback_services(hass)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    for alarm_id, endpoint_id in (
        ("bedroom-alarm", first.entry_id),
        ("office-alarm", second.entry_id),
    ):
        await registry.async_upsert(
            AlarmRecord(
                alarm_id=alarm_id,
                endpoint_entry_id=endpoint_id,
                name=alarm_id,
                metadata={
                    META_TIME: "07:00:00",
                    META_RECURRENCE: RECURRENCE_DAILY,
                    META_DATE: None,
                },
            )
        )

    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    await playback.async_start("bedroom-alarm")
    await playback.async_start("office-alarm")
    await asyncio.sleep(0)

    await playback.async_stop(endpoint_id=first.entry_id)

    assert playback.active_for_endpoint(first.entry_id) is None
    assert playback.active_for_endpoint(second.entry_id) is not None

    await playback.async_stop(endpoint_id=second.entry_id)


async def test_same_endpoint_rejects_second_ringing_alarm(hass: HomeAssistant) -> None:
    """Only one alarm may ring on an endpoint at a time in v0.3."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    _register_playback_services(hass)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    for alarm_id in ("alarm-1", "alarm-2"):
        await registry.async_upsert(
            AlarmRecord(
                alarm_id=alarm_id,
                endpoint_entry_id=entry.entry_id,
                name=alarm_id,
                metadata={
                    META_TIME: "07:00:00",
                    META_RECURRENCE: RECURRENCE_DAILY,
                    META_DATE: None,
                },
            )
        )

    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    await playback.async_start("alarm-1")

    with pytest.raises(AlarmAlreadyRingingError):
        await playback.async_start("alarm-2")

    await playback.async_stop(alarm_id="alarm-1")


async def test_unavailable_media_player_rejects_start(hass: HomeAssistant) -> None:
    """An unavailable alarm player should fail before creating active state."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "unavailable")
    _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    with pytest.raises(PlaybackError, match="unavailable"):
        await playback.async_start("alarm-1")

    assert playback.active_for_endpoint(entry.entry_id) is None


async def test_start_or_queue_runs_same_room_alarms_in_order(hass: HomeAssistant) -> None:
    """A second due alarm should wait for the active alarm instead of being lost."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    _register_playback_services(hass)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    for alarm_id in ("alarm-1", "alarm-2"):
        await registry.async_upsert(
            AlarmRecord(
                alarm_id=alarm_id,
                endpoint_entry_id=entry.entry_id,
                name=alarm_id,
                metadata={
                    META_TIME: "07:00:00",
                    META_RECURRENCE: RECURRENCE_DAILY,
                    META_DATE: None,
                },
            )
        )

    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    first, queued = await playback.async_start_or_queue("alarm-1")
    assert first is not None
    assert queued is False

    second, queued = await playback.async_start_or_queue("alarm-2")
    assert second is None
    assert queued is True
    assert playback.queued_for_endpoint(entry.entry_id) == ("alarm-2",)

    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    active = playback.active_for_endpoint(entry.entry_id)
    assert active is not None
    assert active.alarm_id == "alarm-2"
    assert playback.queued_for_endpoint(entry.entry_id) == ()

    await playback.async_stop(alarm_id="alarm-2")


async def test_shutdown_drops_queued_alarms(hass: HomeAssistant) -> None:
    """Shutdown should not start alarms that were waiting in an endpoint queue."""
    entry = _add_endpoint(hass)
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    _register_playback_services(hass)

    registry = AlarmRegistry(hass)
    await registry.async_load()
    for alarm_id in ("alarm-1", "alarm-2"):
        await registry.async_upsert(
            AlarmRecord(
                alarm_id=alarm_id,
                endpoint_entry_id=entry.entry_id,
                name=alarm_id,
                metadata={
                    META_TIME: "07:00:00",
                    META_RECURRENCE: RECURRENCE_DAILY,
                    META_DATE: None,
                },
            )
        )

    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    await playback.async_start_or_queue("alarm-1")
    await playback.async_start_or_queue("alarm-2")

    await playback.async_shutdown()
    await asyncio.sleep(0)

    assert playback.active_for_endpoint(entry.entry_id) is None
    assert playback.queued_for_endpoint(entry.entry_id) == ()


async def test_per_alarm_media_volume_and_actions(hass: HomeAssistant) -> None:
    """Per-alarm playback overrides and pre/post service actions should be honored."""
    entry = _add_endpoint(hass, options={CONF_VOLUME_RAMP_ENABLED: False})
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.25})
    calls = _register_playback_services(hass)

    async def capture_light(call: ServiceCall) -> None:
        calls.append(("light", call.service, dict(call.data)))

    hass.services.async_register("light", "turn_on", capture_light)
    hass.services.async_register("light", "turn_off", capture_light)

    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    record = registry.get("alarm-1")
    assert record is not None
    record.metadata[META_ALARM_MEDIA] = "media-source://media_source/local/work.mp3"
    record.metadata[META_ALARM_VOLUME] = 0.55
    record.metadata[META_PRE_ACTIONS] = [
        {"action": "light.turn_on", "data": {"brightness_pct": 20}}
    ]
    record.metadata[META_POST_ACTIONS] = [{"action": "light.turn_off", "data": {}}]
    await registry.async_upsert(record)

    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-1")

    assert any(call[:2] == ("light", "turn_on") for call in calls)
    assert any(call[:2] == ("light", "turn_off") for call in calls)

    announce = next(call for call in calls if call[:2] == ("assist_satellite", "announce"))
    assert announce[2]["media_id"] == "media-source://media_source/local/work.mp3"

    volume_levels = [
        call[2]["volume_level"] for call in calls if call[:2] == ("media_player", "volume_set")
    ]
    assert 0.55 in volume_levels
    assert volume_levels[-1] == 0.25


async def test_per_alarm_default_snooze_overrides_endpoint(hass: HomeAssistant) -> None:
    """Per-alarm snooze should override the endpoint default."""
    entry = _add_endpoint(
        hass,
        options={CONF_DEFAULT_SNOOZE_MINUTES: 10},
    )
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.4})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    record = registry.get("alarm-1")
    assert record is not None
    record.metadata[META_SNOOZE_MINUTES] = 17
    await registry.async_upsert(record)

    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    await playback.async_start("alarm-1")
    await asyncio.sleep(0)
    _active, minutes, _entity_id = await playback.async_snooze(alarm_id="alarm-1")

    assert minutes == 17
    snooze_add = next(
        call
        for call in calls
        if call[:2] == ("scheduler", "add")
        and any(":snooze:" in tag for tag in call[2].get("tags", []))
    )
    assert snooze_add[2]["repeat_type"] == "single"


async def test_failure_hook_runs_service_action_and_emits_event(
    hass: HomeAssistant,
) -> None:
    """Playback failure hooks should run once and publish a failure event."""
    entry = _add_endpoint(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-1", endpoint_id=entry.entry_id)
    record = registry.get("alarm-1")
    assert record is not None
    record.metadata[META_FAILURE_ACTIONS] = [
        {"action": "notify.notify", "data": {"message": "Alarm failed"}}
    ]
    await registry.async_upsert(record)

    calls: list[dict] = []

    async def capture_notify(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("notify", "notify", capture_notify)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))
    events = []
    unsub = hass.bus.async_listen("assist_satellite_alarms_alarm_failed", events.append)
    try:
        await playback.async_handle_failure("alarm-1", "speaker unavailable")
        await hass.async_block_till_done()
    finally:
        unsub()

    assert calls == [{"message": "Alarm failed"}]
    assert len(events) == 1
    assert events[0].data["alarm_id"] == "alarm-1"
    assert events[0].data["reason"] == "speaker unavailable"


async def test_all_room_speakers_ring_and_restore_independently(
    hass: HomeAssistant,
) -> None:
    """All mode should ring every available room pair and restore each prior volume."""
    entry = _add_endpoint(
        hass,
        options={
            CONF_PLAYBACK_MODE: PLAYBACK_MODE_ALL,
            CONF_VOLUME_RAMP_ENABLED: False,
        },
        additional_targets=[
            {
                CONF_ASSIST_SATELLITE: "assist_satellite.bedroom_right",
                CONF_MEDIA_PLAYER: "media_player.bedroom_right",
            }
        ],
    )
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.25})
    hass.states.async_set("media_player.bedroom_right", "idle", {"volume_level": 0.45})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(hass, alarm_id="alarm-all", endpoint_id=entry.entry_id)
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    active = await playback.async_start("alarm-all")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-all")

    assert len(active.targets) == 2
    announce_targets = {
        call[2]["entity_id"] for call in calls if call[:2] == ("assist_satellite", "announce")
    }
    assert announce_targets == {
        "assist_satellite.bedroom",
        "assist_satellite.bedroom_right",
    }

    volume_calls = [call[2] for call in calls if call[:2] == ("media_player", "volume_set")]
    restored = {item["entity_id"]: item["volume_level"] for item in volume_calls[-2:]}
    assert restored == {
        "media_player.bedroom": 0.25,
        "media_player.bedroom_right": 0.45,
    }


async def test_fallback_mode_uses_next_available_room_target(
    hass: HomeAssistant,
) -> None:
    """Fallback mode should skip an unavailable primary pair."""
    entry = _add_endpoint(
        hass,
        options={
            CONF_PLAYBACK_MODE: PLAYBACK_MODE_FALLBACK,
            CONF_VOLUME_RAMP_ENABLED: False,
        },
        additional_targets=[
            {
                CONF_ASSIST_SATELLITE: "assist_satellite.bedroom_right",
                CONF_MEDIA_PLAYER: "media_player.bedroom_right",
            }
        ],
    )
    hass.states.async_set("media_player.bedroom", "unavailable", {"volume_level": 0.2})
    hass.states.async_set("media_player.bedroom_right", "idle", {"volume_level": 0.4})
    calls = _register_playback_services(hass)
    registry = await _registry_with_alarm(
        hass, alarm_id="alarm-fallback", endpoint_id=entry.entry_id
    )
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    active = await playback.async_start("alarm-fallback")
    await asyncio.sleep(0)
    await playback.async_stop(alarm_id="alarm-fallback")

    assert active.assist_satellite_entity_id == "assist_satellite.bedroom_right"
    announce = next(call for call in calls if call[:2] == ("assist_satellite", "announce"))
    assert announce[2]["entity_id"] == "assist_satellite.bedroom_right"


async def test_primary_mode_does_not_silently_use_secondary_target(
    hass: HomeAssistant,
) -> None:
    """Primary mode should fail when the primary pair is unavailable."""
    entry = _add_endpoint(
        hass,
        additional_targets=[
            {
                CONF_ASSIST_SATELLITE: "assist_satellite.bedroom_right",
                CONF_MEDIA_PLAYER: "media_player.bedroom_right",
            }
        ],
    )
    hass.states.async_set("media_player.bedroom", "unavailable", {"volume_level": 0.2})
    hass.states.async_set("media_player.bedroom_right", "idle", {"volume_level": 0.4})
    _register_playback_services(hass)
    registry = await _registry_with_alarm(
        hass, alarm_id="alarm-primary", endpoint_id=entry.entry_id
    )
    playback = PlaybackManager(hass, registry, SchedulerAdapter(hass))

    with pytest.raises(PlaybackError, match="Primary alarm satellite/media player"):
        await playback.async_start("alarm-primary")
