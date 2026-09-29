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
    CONF_VOLUME_RAMP_ENABLED,
    CONF_VOLUME_RAMP_SECONDS,
    CONF_VOLUME_RAMP_START,
    DEFAULT_ALARM_MEDIA,
    DEFAULT_ALARM_MESSAGE,
    DEFAULT_MAX_RING_MINUTES,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_VOLUME,
    DEFAULT_VOLUME_RAMP_ENABLED,
    DEFAULT_VOLUME_RAMP_SECONDS,
    DEFAULT_VOLUME_RAMP_START,
    DOMAIN,
    META_RECURRENCE,
    RECURRENCE_ONCE,
    VOLUME_RAMP_STEP_SECONDS,
)
from .models import AlarmEndpoint, AlarmRecord
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
class ActiveAlarm:
    """Runtime state for one ringing alarm."""

    alarm_id: str
    endpoint_entry_id: str
    assist_satellite_entity_id: str
    media_player_entity_id: str
    previous_volume: float | None
    started_at: datetime
    task: asyncio.Task[None] | None = None
    ramp_task: asyncio.Task[None] | None = None
    finish_reason: str | None = None


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

    async def _async_announce(self, active: ActiveAlarm, entry: ConfigEntry) -> None:
        """Play one alarm announcement on the Assist satellite."""
        media_id = str(
            self._option(entry, CONF_DEFAULT_ALARM_MEDIA, DEFAULT_ALARM_MEDIA) or ""
        ).strip()
        message = str(
            self._option(entry, CONF_DEFAULT_ALARM_MESSAGE, DEFAULT_ALARM_MESSAGE)
            or DEFAULT_ALARM_MESSAGE
        ).strip()

        service_data: dict[str, Any] = {
            ATTR_ENTITY_ID: active.assist_satellite_entity_id,
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

    async def _async_ramp_volume(
        self,
        active: ActiveAlarm,
        *,
        start_volume: float,
        target_volume: float,
        duration_seconds: float,
    ) -> None:
        """Ramp volume in bounded steps."""
        if duration_seconds <= 0 or target_volume <= start_volume:
            await self._async_set_volume(active.media_player_entity_id, target_volume)
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
            await self._async_set_volume(active.media_player_entity_id, level)

    async def _async_finalize(self, active: ActiveAlarm) -> None:
        """Restore volume and clear runtime state."""
        if active.ramp_task and not active.ramp_task.done():
            active.ramp_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active.ramp_task

        if active.previous_volume is not None:
            try:
                await self._async_set_volume(active.media_player_entity_id, active.previous_volume)
            except HomeAssistantError:
                _LOGGER.warning(
                    "Could not restore volume for %s",
                    active.media_player_entity_id,
                    exc_info=True,
                )

        async with self._lock:
            if self._active_by_endpoint.get(active.endpoint_entry_id) is active:
                self._active_by_endpoint.pop(active.endpoint_entry_id, None)

        if active.finish_reason in {"stop", "timeout"}:
            record = self.registry.get(active.alarm_id)
            if record and record.metadata.get(META_RECURRENCE) == RECURRENCE_ONCE:
                await self.registry.async_remove(active.alarm_id)

    async def _async_run(self, active: ActiveAlarm, entry: ConfigEntry) -> None:
        """Run the repeating alarm loop until stopped or timed out."""
        target_volume = float(self._option(entry, CONF_DEFAULT_VOLUME, DEFAULT_VOLUME))
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
            if ramp_enabled:
                start_volume = min(ramp_start, target_volume)
                await self._async_set_volume(active.media_player_entity_id, start_volume)
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
                await self._async_set_volume(active.media_player_entity_id, target_volume)

            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    active.finish_reason = "timeout"
                    break

                try:
                    async with asyncio.timeout(remaining):
                        await self._async_announce(active, entry)
                except TimeoutError:
                    active.finish_reason = "timeout"
                    break
                except HomeAssistantError:
                    _LOGGER.warning(
                        "Alarm announcement failed for %s; retrying",
                        active.assist_satellite_entity_id,
                        exc_info=True,
                    )

                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    active.finish_reason = "timeout"
                    break
                await asyncio.sleep(min(ALARM_REPLAY_INTERVAL_SECONDS, remaining))
        except asyncio.CancelledError:
            raise
        except Exception:
            active.finish_reason = "error"
            _LOGGER.exception("Alarm playback failed for %s", active.alarm_id)
        finally:
            await self._async_stop_media(active.media_player_entity_id)
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

        player_state = self.hass.states.get(endpoint.media_player_entity_id)
        if player_state is None or player_state.state in {
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        }:
            raise PlaybackError(
                f"Alarm media player is unavailable: {endpoint.media_player_entity_id}"
            )

        previous_volume_raw = player_state.attributes.get(ATTR_VOLUME_LEVEL)
        previous_volume = (
            float(previous_volume_raw) if isinstance(previous_volume_raw, int | float) else None
        )

        async with self._lock:
            if record.endpoint_entry_id in self._active_by_endpoint:
                current = self._active_by_endpoint[record.endpoint_entry_id]
                raise AlarmAlreadyRingingError(
                    f"Endpoint already has ringing alarm {current.alarm_id}"
                )

            active = ActiveAlarm(
                alarm_id=alarm_id,
                endpoint_entry_id=record.endpoint_entry_id,
                assist_satellite_entity_id=endpoint.assist_satellite_entity_id,
                media_player_entity_id=endpoint.media_player_entity_id,
                previous_volume=previous_volume,
                started_at=dt_util.now(),
            )
            self._active_by_endpoint[record.endpoint_entry_id] = active
            active.task = self.hass.async_create_task(
                self._async_run(active, entry),
                f"{DOMAIN} alarm {alarm_id}",
            )
            return active

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

        await self._async_stop_media(active.media_player_entity_id)

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

        snooze_minutes = int(
            minutes
            if minutes is not None
            else self._option(
                entry,
                CONF_DEFAULT_SNOOZE_MINUTES,
                DEFAULT_SNOOZE_MINUTES,
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
        active = tuple(self._active_by_endpoint.values())
        for item in active:
            with contextlib.suppress(PlaybackError, HomeAssistantError):
                await self.async_stop(alarm_id=item.alarm_id, reason="shutdown")
