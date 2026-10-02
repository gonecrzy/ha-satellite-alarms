"""Satellite Alarms integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .alarm_manager import AlarmManager
from .const import (
    BUILTIN_ALARM_MEDIA_FILENAME,
    BUILTIN_ALARM_MEDIA_URL,
    DATA_ALARM_MANAGER,
    DATA_PLAYBACK_MANAGER,
    DATA_RECONCILED,
    DATA_VOICE_CONTROLLER,
    DATA_REGISTRY,
    DATA_SCHEDULER_ADAPTER,
    DOMAIN,
)
from .models import AlarmEndpoint
from .playback import PlaybackManager
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter, SchedulerNotReadyError
from .services import async_register_services
from .voice import VoiceController

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Satellite Alarms domain."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    manager = AlarmManager(hass, registry, scheduler)
    playback = PlaybackManager(hass, registry, scheduler)
    voice = VoiceController(hass, manager, playback)

    domain_data[DATA_REGISTRY] = registry
    domain_data[DATA_SCHEDULER_ADAPTER] = scheduler
    domain_data[DATA_ALARM_MANAGER] = manager
    domain_data[DATA_PLAYBACK_MANAGER] = playback
    domain_data[DATA_VOICE_CONTROLLER] = voice

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                BUILTIN_ALARM_MEDIA_URL,
                str(Path(__file__).parent / "media" / BUILTIN_ALARM_MEDIA_FILENAME),
                True,
            )
        ]
    )

    await async_register_services(hass, manager, playback)
    voice.register()

    async def async_shutdown(_event: Event) -> None:
        voice.unregister()
        await playback.async_shutdown()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_shutdown)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Satellite Alarms endpoint."""
    domain_data = hass.data[DOMAIN]
    adapter: SchedulerAdapter = domain_data[DATA_SCHEDULER_ADAPTER]
    manager: AlarmManager = domain_data[DATA_ALARM_MANAGER]

    try:
        adapter.ensure_ready()
    except SchedulerNotReadyError as err:
        raise ConfigEntryNotReady(str(err)) from err

    if not domain_data.get(DATA_RECONCILED):
        matched, missing = await manager.async_reconcile()
        domain_data[DATA_RECONCILED] = True
        _LOGGER.info(
            "Reconciled Satellite Alarms with Scheduler: %s matched, %s missing",
            matched,
            missing,
        )

    endpoint = AlarmEndpoint.from_config_entry(entry)
    entry.runtime_data = endpoint

    _LOGGER.info(
        "Loaded Satellite Alarms endpoint %s (%s -> %s)",
        endpoint.name,
        endpoint.assist_satellite_entity_id,
        endpoint.media_player_entity_id,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one Satellite Alarms endpoint."""
    playback: PlaybackManager = hass.data[DOMAIN][DATA_PLAYBACK_MANAGER]
    active = playback.active_for_endpoint(entry.entry_id)
    if active is not None:
        await playback.async_stop(endpoint_id=entry.entry_id, reason="unload")
    return True
