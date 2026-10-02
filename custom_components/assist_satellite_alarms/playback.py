"""Alarm playback, ringing state, stop, and snooze handling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    ALARM_REPLAY_INTERVAL_SECONDS,
    CONF_DEFAULT_ALARM_MEDIA,
    CONF_DEFAULT_ALARM_MESSAGE,
    CONF_DEFAULT_SNOOZE_MINUTES,
    CONF_DEFAULT_VOLUME,
    CONF_MAX_RING_MINUTES,
    CONF_PLAYBACK_MODE,
    CONF_VOLUME_RAMP_ENABLED,
    CONF_VOLUME_RAMP_SECONDS,
    CONF_VOLUME_RAMP_START,
    DEFAULT_ALARM_MEDIA,
    DEFAULT_ALARM_MESSAGE,
    DEFAULT_MAX_RING_MINUTES,
    DEFAULT_PLAYBACK_MODE,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_VOLUME,
    DEFAULT_VOLUME_RAMP_ENABLED,
    DEFAULT_VOLUME_RAMP_SECONDS,
    DEFAULT_VOLUME_RAMP_START,
    DOMAIN,
    EVENT_ALARM_FAILED,
    META_ALARM_MEDIA,
    META_ALARM_VOLUME,
    META_FAILURE_ACTIONS,
    META_POST_ACTIONS,
    META_PRE_ACTIONS,
    META_RECURRENCE,
    META_SNOOZE_MINUTES,
    PLAYBACK_MODE_ALL,
    PLAYBACK_MODE_FALLBACK,
    PLAYBACK_MODE_PRIMARY,
    RECURRENCE_ONCE,
    VOLUME_RAMP_STEP_SECONDS,
)
from .models import AlarmEndpoint, AlarmRecord, PlaybackTarget
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter

_LOGGER = logging.getLogger(__name__)

ASSIST_SATELLITE_DOMAIN = "assist_satellite"
ASSIST_SATELLITE_ANNOUNCE = "announce"
MEDIA_PLAYER_DOMAIN = "media_player"
MEDIA_PLAYER_VOLUME_SET = "volume_set"
MEDIA_PLAYER_STOP = "media_stop"
ATTR_VOLUME_LEVEL = "volume_level"


class PlaybackError(RuntimeError):
    """Base error for ringing/playback operations."""


class AlarmAlreadyRingingError(PlaybackError):
    """Raised when an endpoint already has an active ringing alarm."""


class ActiveAlarmNotFoundError(PlaybackError):
    """Raised when no active ringing alarm matches the request."""


@dataclass(slots=True)
class ActivePlaybackTarget:
    """Runtime state for one room playback target."""

    assist_satellite_entity_id: str
    media_player_entity_id: str
    previous_volume: float | None
    touched: bool = False


@dataclass(slots=True)
class ActiveAlarm:
    """Runtime state for one ringing alarm."""

    alarm_id: str
    endpoint_entry_id: str
    playback_mode: str
    targets: list[ActivePlaybackTarget]
    started_at: datetime
    current_target_index: int = 0
    task: asyncio.Task[None] | None = None
    ramp_task: asyncio.Task[None] | None = None
    finish_reason: str | None = None

    @property
    def assist_satellite_entity_id(self) -> str:
        """Return the current/primary Assist satellite for compatibility."""
        return self.targets[self.current_target_index].assist_satellite_entity_id

    @property
    def media_player_entity_id(self) -> str:
        """Return the current/primary media player for compatibility."""
        return self.targets[self.current_target_index].media_player_entity_id

    @property
    def previous_volume(self) -> float | None:
        """Return the current/primary previous volume for compatibility."""
        return self.targets[self.current_target_index].previous_volume


class PlaybackManager:
    """Manage active alarms independently per configured endpoint."""

    def __init__(
        self,
        hass: HomeAssistant,
        registry: AlarmRegistry,
        scheduler: SchedulerAdapter,
    ) -> None:
        """Initialize playback state."""
        self.hass = hass
        self.registry = registry
        self.scheduler = scheduler
        self._active_by_endpoint: dict[str, ActiveAlarm] = {}
        self._queued_by_endpoint: dict[str, list[str]] = {}
        self._shutting_down = False
        self._lock = asyncio.Lock()

    def active_for_endpoint(self, endpoint_id: str) -> ActiveAlarm | None:
        """Return the active alarm for one endpoint."""
        return self._active_by_endpoint.get(endpoint_id)

    def active_for_alarm(self, alarm_id: str) -> ActiveAlarm | None:
        """Return an active alarm by stable alarm ID."""
        return next(
            (active for active in self._active_by_endpoint.values() if active.alarm_id == alarm_id),
            None,
        )

    def queued_for_endpoint(self, endpoint_id: str) -> tuple[str, ...]:
        """Return alarms waiting to ring on an endpoint."""
        return tuple(self._queued_by_endpoint.get(endpoint_id, ()))

    def clear_queue(self, endpoint_id: str) -> None:
        """Drop queued alarms for an endpoint without touching schedules."""
        self._queued_by_endpoint.pop(endpoint_id, None)

    def _record(self, alarm_id: str) -> AlarmRecord:
        """Return an alarm record or raise."""
        record = self.registry.get(alarm_id)
        if record is None:
            raise PlaybackError(f"Unknown alarm: {alarm_id}")
        return record

    def _entry(self, endpoint_id: str) -> ConfigEntry:
        """Return the endpoint config entry."""
        entry = self.hass.config_entries.async_get_entry(endpoint_id)
        if entry is None or entry.domain != DOMAIN:
            raise PlaybackError(f"Unknown Satellite Alarms endpoint: {endpoint_id}")
        return entry

    def _endpoint(self, endpoint_id: str) -> AlarmEndpoint:
        """Return an endpoint model."""
        return AlarmEndpoint.from_config_entry(self._entry(endpoint_id))

    @staticmethod
    def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
        """Return a configured option or its default."""
        return entry.options.get(key, default)

    def _runtime_target(self, target: PlaybackTarget) -> ActivePlaybackTarget | None:
        """Build runtime target state when both satellite and player are available."""
        satellite_state = self.hass.states.get(target.assist_satellite_entity_id)
        player_state = self.hass.states.get(target.media_player_entity_id)
        unavailable = {STATE_UNAVAILABLE, STATE_UNKNOWN}

        if (
            satellite_state is None
            or satellite_state.state in unavailable
            or player_state is None
            or player_state.state in unavailable
        ):
            return None

        previous_volume_raw = player_state.attributes.get(ATTR_VOLUME_LEVEL)
        previous_volume = (
            float(previous_volume_raw)
            if isinstance(previous_volume_raw, int | float)
            else None
        )
        return ActivePlaybackTarget(
            assist_satellite_entity_id=target.assist_satellite_entity_id,
            media_player_entity_id=target.media_player_entity_id,
            previous_volume=previous_volume,
        )

    def _selected_targets(self, active: ActiveAlarm) -> list[ActivePlaybackTarget]:
        """Return targets that should currently receive playback."""
        if active.playback_mode == PLAYBACK_MODE_ALL:
            return active.targets
        return [active.targets[active.current_target_index]]

    async def _async_set_mode_volume(self, active: ActiveAlarm, volume: float) -> None:
        """Set alarm volume for the active playback mode."""
        if active.playback_mode == PLAYBACK_MODE_ALL:
            successes = 0
            for target in active.targets:
                try:
                    await self._async_set_volume(target.media_player_entity_id, volume)
                    target.touched = True
                    successes += 1
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Could not set alarm volume for %s",
                        target.media_player_entity_id,
                        exc_info=True,
                    )
            if successes == 0:
                raise PlaybackError("No room media player accepted the alarm volume")
            return

        if active.playback_mode == PLAYBACK_MODE_FALLBACK:
            for index in range(active.current_target_index, len(active.targets)):
                target = active.targets[index]
                try:
                    await self._async_set_volume(target.media_player_entity_id, volume)
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Fallback alarm media player %s rejected volume; trying next",
                        target.media_player_entity_id,
                        exc_info=True,
                    )
                    continue
                target.touched = True
                active.current_target_index = index
                return
            raise PlaybackError("No fallback media player accepted the alarm volume")

        target = active.targets[active.current_target_index]
        await self._async_set_volume(target.media_player_entity_id, volume)
        target.touched = True

    async def _async_set_volume(self, entity_id: str, volume: float) -> None:
        """Set media-player volume."""
        await self.hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            MEDIA_PLAYER_VOLUME_SET,
            {
                ATTR_ENTITY_ID: entity_id,
                ATTR_VOLUME_LEVEL: max(0.0, min(1.0, float(volume))),
            },
            blocking=True,
        )

    async def _async_stop_media(self, entity_id: str) -> None:
        """Best-effort stop of alarm playback on the media player."""
        if not self.hass.services.has_service(MEDIA_PLAYER_DOMAIN, MEDIA_PLAYER_STOP):
            return
        try:
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                MEDIA_PLAYER_STOP,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )
        except HomeAssistantError:
            _LOGGER.debug("Media stop failed for %s", entity_id, exc_info=True)

    async def _async_announce_target(
        self,
        target: ActivePlaybackTarget,
        *,
        media_id: str,
        message: str,
    ) -> None:
        """Play one alarm announcement on one room satellite."""
        service_data: dict[str, Any] = {
            ATTR_ENTITY_ID: target.assist_satellite_entity_id,
            "preannounce": not bool(media_id),
        }
        if media_id:
            service_data["media_id"] = media_id
        else:
            service_data["message"] = message or DEFAULT_ALARM_MESSAGE

        await self.hass.services.async_call(
            ASSIST_SATELLITE_DOMAIN,
            ASSIST_SATELLITE_ANNOUNCE,
            service_data,
            blocking=True,
        )

    async def _async_announce(
        self,
        active: ActiveAlarm,
        entry: ConfigEntry,
        record: AlarmRecord,
        *,
        target_volume: float,
    ) -> None:
        """Play one alarm announcement according to the room playback mode."""
        configured_media = record.metadata.get(META_ALARM_MEDIA)
        media_id = str(
            configured_media
            if configured_media is not None
            else self._option(entry, CONF_DEFAULT_ALARM_MEDIA, DEFAULT_ALARM_MEDIA) or ""
        ).strip()
        message = str(
            self._option(entry, CONF_DEFAULT_ALARM_MESSAGE, DEFAULT_ALARM_MESSAGE)
            or DEFAULT_ALARM_MESSAGE
        ).strip()

        if active.playback_mode == PLAYBACK_MODE_ALL:
            successes = 0
            for target in active.targets:
                try:
                    await self._async_announce_target(
                        target,
                        media_id=media_id,
                        message=message,
                    )
                    successes += 1
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Alarm announcement failed for room target %s",
                        target.assist_satellite_entity_id,
                        exc_info=True,
                    )
            if successes == 0:
                raise HomeAssistantError("Alarm announcement failed on every room target")
            return

        if active.playback_mode == PLAYBACK_MODE_FALLBACK:
            start_index = active.current_target_index
            for index in range(start_index, len(active.targets)):
                target = active.targets[index]
                if index != active.current_target_index:
                    try:
                        await self._async_set_volume(
                            target.media_player_entity_id,
                            target_volume,
                        )
                    except HomeAssistantError:
                        continue
                    target.touched = True
                    active.current_target_index = index

                try:
                    await self._async_announce_target(
                        target,
                        media_id=media_id,
                        message=message,
                    )
                    return
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Alarm announcement failed for fallback target %s; trying next",
                        target.assist_satellite_entity_id,
                        exc_info=True,
                    )
            raise HomeAssistantError("Alarm announcement failed on every fallback target")

        await self._async_announce_target(
            active.targets[active.current_target_index],
            media_id=media_id,
            message=message,
        )

    async def _async_run_actions(
        self,
        record: AlarmRecord,
        metadata_key: str,
        *,
        reason: str,
    ) -> None:
        """Run simple persisted Home Assistant service actions sequentially."""
        actions = record.metadata.get(metadata_key) or []
        if not isinstance(actions, list):
            return

        for item in actions:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or item.get("service") or "")
            if "." not in action:
                continue
            domain, service = action.split(".", 1)
            data = item.get("data")
            target = item.get("target")
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    dict(data) if isinstance(data, dict) else {},
                    blocking=True,
                    target=dict(target) if isinstance(target, dict) else None,
                )
            except HomeAssistantError:
                _LOGGER.warning(
                    "Alarm %s %s action %s failed",
                    record.alarm_id,
                    reason,
                    action,
                    exc_info=True,
                )

    async def async_handle_failure(self, alarm_id: str, reason: str) -> None:
        """Run failure hooks and emit an alarm failure event."""
        record = self._record(alarm_id)
        await self._async_run_actions(record, META_FAILURE_ACTIONS, reason="failure")
        self.hass.bus.async_fire(
            EVENT_ALARM_FAILED,
            {
                "alarm_id": record.alarm_id,
                "endpoint_id": record.endpoint_entry_id,
                "name": record.name,
                "reason": reason,
            },
        )

    async def _async_ramp_volume(
        self,
        active: ActiveAlarm,
        *,
        start_volume: float,
        target_volume: float,
        duration_seconds: float,
    ) -> None:
        """Ramp alarm volume for all targets selected by the playback mode."""
        if duration_seconds <= 0 or target_volume <= start_volume:
            await self._async_set_mode_volume(active, target_volume)
            return

        steps = max(
            1,
            min(
                20,
                int(duration_seconds / VOLUME_RAMP_STEP_SECONDS) or 1,
            ),
        )
        delay = duration_seconds / steps

        for step in range(1, steps + 1):
            await asyncio.sleep(delay)
            level = start_volume + ((target_volume - start_volume) * step / steps)
            await self._async_set_mode_volume(active, level)

    async def _async_finalize(self, active: ActiveAlarm) -> None:
        """Restore volume, run final actions, and clear runtime state."""
        record = self.registry.get(active.alarm_id)
        if active.ramp_task and not active.ramp_task.done():
            active.ramp_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active.ramp_task

        for target in active.targets:
            if not target.touched:
                continue
            await self._async_stop_media(target.media_player_entity_id)
            if target.previous_volume is None:
                continue
            try:
                await self._async_set_volume(
                    target.media_player_entity_id,
                    target.previous_volume,
                )
            except HomeAssistantError:
                _LOGGER.warning(
                    "Could not restore volume for %s",
                    target.media_player_entity_id,
                    exc_info=True,
                )

        next_alarm_id: str | None = None
        async with self._lock:
            if self._active_by_endpoint.get(active.endpoint_entry_id) is active:
                self._active_by_endpoint.pop(active.endpoint_entry_id, None)

            if active.finish_reason in {"shutdown", "unload"} or self._shutting_down:
                self._queued_by_endpoint.pop(active.endpoint_entry_id, None)
            else:
                queue = self._queued_by_endpoint.get(active.endpoint_entry_id, [])
                while queue:
                    candidate = queue.pop(0)
                    if self.registry.get(candidate) is not None:
                        next_alarm_id = candidate
                        break
                if not queue:
                    self._queued_by_endpoint.pop(active.endpoint_entry_id, None)

        if record and active.finish_reason in {"stop", "timeout"}:
            await self._async_run_actions(record, META_POST_ACTIONS, reason="post")
            if record.metadata.get(META_RECURRENCE) == RECURRENCE_ONCE:
                await self.registry.async_remove(active.alarm_id)

        if next_alarm_id is not None:
            self.hass.async_create_task(
                self._async_start_queued(next_alarm_id),
                f"{DOMAIN} queued alarm {next_alarm_id}",
            )

    async def _async_run(
        self, active: ActiveAlarm, entry: ConfigEntry, record: AlarmRecord
    ) -> None:
        """Run the repeating alarm loop until stopped or timed out."""
        configured_volume = record.metadata.get(META_ALARM_VOLUME)
        target_volume = float(
            configured_volume
            if configured_volume is not None
            else self._option(entry, CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)
        )
        ramp_enabled = bool(
            self._option(
                entry,
                CONF_VOLUME_RAMP_ENABLED,
                DEFAULT_VOLUME_RAMP_ENABLED,
            )
        )
        ramp_start = float(self._option(entry, CONF_VOLUME_RAMP_START, DEFAULT_VOLUME_RAMP_START))
        ramp_seconds = float(
            self._option(
                entry,
                CONF_VOLUME_RAMP_SECONDS,
                DEFAULT_VOLUME_RAMP_SECONDS,
            )
        )
        max_ring_minutes = float(
            self._option(entry, CONF_MAX_RING_MINUTES, DEFAULT_MAX_RING_MINUTES)
        )
        deadline = asyncio.get_running_loop().time() + (max_ring_minutes * 60)

        try:
            await self._async_run_actions(record, META_PRE_ACTIONS, reason="pre")
            if ramp_enabled:
                start_volume = min(ramp_start, target_volume)
                await self._async_set_mode_volume(active, start_volume)
                active.ramp_task = self.hass.async_create_task(
                    self._async_ramp_volume(
                        active,
                        start_volume=start_volume,
                        target_volume=target_volume,
                        duration_seconds=ramp_seconds,
                    ),
                    f"{DOMAIN} volume ramp {active.alarm_id}",
                )
            else:
                await self._async_set_mode_volume(active, target_volume)

            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    active.finish_reason = "timeout"
                    break

                try:
                    async with asyncio.timeout(remaining):
                        await self._async_announce(
                            active,
                            entry,
                            record,
                            target_volume=target_volume,
                        )
                except TimeoutError:
                    active.finish_reason = "timeout"
                    break
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Alarm announcement failed for room %s; retrying",
                        active.endpoint_entry_id,
                        exc_info=True,
                    )

                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    active.finish_reason = "timeout"
                    break
                await asyncio.sleep(min(ALARM_REPLAY_INTERVAL_SECONDS, remaining))
        except asyncio.CancelledError:
            raise
        except Exception as err:
            active.finish_reason = "error"
            _LOGGER.exception("Alarm playback failed for %s", active.alarm_id)
            await self.async_handle_failure(active.alarm_id, str(err))
        finally:
            await self._async_finalize(active)

    async def async_start(self, alarm_id: str) -> ActiveAlarm:
        """Start ringing an alarm."""
        record = self._record(alarm_id)
        entry = self._entry(record.endpoint_entry_id)
        endpoint = AlarmEndpoint.from_config_entry(entry)

        if not self.hass.services.has_service(ASSIST_SATELLITE_DOMAIN, ASSIST_SATELLITE_ANNOUNCE):
            raise PlaybackError("assist_satellite.announce is not available")
        if not self.hass.services.has_service(MEDIA_PLAYER_DOMAIN, MEDIA_PLAYER_VOLUME_SET):
            raise PlaybackError("media_player.volume_set is not available")

        playback_mode = str(
            self._option(entry, CONF_PLAYBACK_MODE, DEFAULT_PLAYBACK_MODE)
        )
        if playback_mode not in {
            PLAYBACK_MODE_PRIMARY,
            PLAYBACK_MODE_ALL,
            PLAYBACK_MODE_FALLBACK,
        }:
            playback_mode = DEFAULT_PLAYBACK_MODE

        configured_targets = endpoint.playback_targets
        if playback_mode == PLAYBACK_MODE_PRIMARY:
            runtime_target = self._runtime_target(configured_targets[0])
            if runtime_target is None:
                raise PlaybackError(
                    "Primary alarm satellite/media player is unavailable: "
                    f"{configured_targets[0].assist_satellite_entity_id} / "
                    f"{configured_targets[0].media_player_entity_id}"
                )
            targets = [runtime_target]
        else:
            targets = [
                runtime_target
                for target in configured_targets
                if (runtime_target := self._runtime_target(target)) is not None
            ]
            if not targets:
                raise PlaybackError("No configured room alarm target is available")

        async with self._lock:
            if record.endpoint_entry_id in self._active_by_endpoint:
                current = self._active_by_endpoint[record.endpoint_entry_id]
                raise AlarmAlreadyRingingError(
                    f"Endpoint already has ringing alarm {current.alarm_id}"
                )

            active = ActiveAlarm(
                alarm_id=alarm_id,
                endpoint_entry_id=record.endpoint_entry_id,
                playback_mode=playback_mode,
                targets=targets,
                started_at=dt_util.now(),
            )
            self._active_by_endpoint[record.endpoint_entry_id] = active
            active.task = self.hass.async_create_task(
                self._async_run(active, entry, record),
                f"{DOMAIN} alarm {alarm_id}",
            )
            return active

    async def async_start_or_queue(self, alarm_id: str) -> tuple[ActiveAlarm | None, bool]:
        """Start an alarm or queue it if another alarm owns the endpoint."""
        try:
            return await self.async_start(alarm_id), False
        except AlarmAlreadyRingingError:
            record = self._record(alarm_id)
            async with self._lock:
                current = self._active_by_endpoint.get(record.endpoint_entry_id)
                if current is not None and current.alarm_id == alarm_id:
                    return current, False

                queue = self._queued_by_endpoint.setdefault(record.endpoint_entry_id, [])
                if alarm_id not in queue:
                    queue.append(alarm_id)
            return None, True

    async def _async_start_queued(self, alarm_id: str) -> None:
        """Start a queued alarm after the previous endpoint alarm finishes."""
        if self._shutting_down:
            return
        try:
            await self.async_start_or_queue(alarm_id)
        except PlaybackError as err:
            _LOGGER.exception("Could not start queued alarm %s", alarm_id)
            if self.registry.get(alarm_id) is not None:
                await self.async_handle_failure(alarm_id, str(err))

    def _resolve_active(
        self,
        *,
        alarm_id: str | None = None,
        endpoint_id: str | None = None,
    ) -> ActiveAlarm:
        """Resolve exactly one active alarm."""
        if alarm_id:
            active = self.active_for_alarm(alarm_id)
        elif endpoint_id:
            active = self.active_for_endpoint(endpoint_id)
        else:
            active = None

        if active is None:
            raise ActiveAlarmNotFoundError("No matching alarm is currently ringing")
        return active

    async def async_stop(
        self,
        *,
        alarm_id: str | None = None,
        endpoint_id: str | None = None,
        reason: str = "stop",
    ) -> ActiveAlarm:
        """Stop one active alarm and restore its previous volume."""
        active = self._resolve_active(alarm_id=alarm_id, endpoint_id=endpoint_id)
        active.finish_reason = reason

        for target in active.targets:
            if target.touched:
                await self._async_stop_media(target.media_player_entity_id)

        if active.task and not active.task.done():
            active.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active.task

        if self._active_by_endpoint.get(active.endpoint_entry_id) is active:
            await self._async_finalize(active)

        return active

    async def async_snooze(
        self,
        *,
        alarm_id: str | None = None,
        endpoint_id: str | None = None,
        minutes: int | None = None,
    ) -> tuple[ActiveAlarm, int, str]:
        """Snooze an active alarm with a transient Scheduler occurrence."""
        active = self._resolve_active(alarm_id=alarm_id, endpoint_id=endpoint_id)
        entry = self._entry(active.endpoint_entry_id)

        record = self._record(active.alarm_id)
        configured_snooze = record.metadata.get(META_SNOOZE_MINUTES)
        snooze_minutes = int(
            minutes
            if minutes is not None
            else (
                configured_snooze
                if configured_snooze is not None
                else self._option(
                    entry,
                    CONF_DEFAULT_SNOOZE_MINUTES,
                    DEFAULT_SNOOZE_MINUTES,
                )
            )
        )
        if snooze_minutes < 1:
            raise PlaybackError("Snooze duration must be at least one minute")

        snooze_entity_id = await self.scheduler.async_create_snooze_schedule(
            alarm_id=active.alarm_id,
            minutes=snooze_minutes,
        )
        await self.async_stop(alarm_id=active.alarm_id, reason="snooze")
        return active, snooze_minutes, snooze_entity_id

    async def async_shutdown(self) -> None:
        """Stop all ringing alarms during Home Assistant shutdown."""
        self._shutting_down = True
        self._queued_by_endpoint.clear()
        active = tuple(self._active_by_endpoint.values())
        for item in active:
            with contextlib.suppress(PlaybackError, HomeAssistantError):
                await self.async_stop(alarm_id=item.alarm_id, reason="shutdown")
