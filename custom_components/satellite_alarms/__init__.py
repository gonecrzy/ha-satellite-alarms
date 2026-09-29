"""Satellite Alarms integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DATA_REGISTRY,
    DATA_REGISTRY_LOCK,
    DATA_SCHEDULER_ADAPTER,
    DOMAIN,
)
from .models import AlarmEndpoint
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter, SchedulerNotReadyError

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Satellite Alarms domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Satellite Alarms endpoint."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    adapter = domain_data.get(DATA_SCHEDULER_ADAPTER)
    if adapter is None:
        adapter = SchedulerAdapter(hass)
        domain_data[DATA_SCHEDULER_ADAPTER] = adapter

    try:
        adapter.ensure_ready()
    except SchedulerNotReadyError as err:
        raise ConfigEntryNotReady(str(err)) from err

    lock = domain_data.get(DATA_REGISTRY_LOCK)
    if lock is None:
        lock = asyncio.Lock()
        domain_data[DATA_REGISTRY_LOCK] = lock

    async with lock:
        registry = domain_data.get(DATA_REGISTRY)
        if registry is None:
            registry = AlarmRegistry(hass)
            await registry.async_load()
            domain_data[DATA_REGISTRY] = registry

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
    return True
