"""Satellite Alarms integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .alarm_manager import AlarmManager
from .const import (
    DATA_ALARM_MANAGER,
    DATA_RECONCILED,
    DATA_REGISTRY,
    DATA_SCHEDULER_ADAPTER,
    DOMAIN,
)
from .models import AlarmEndpoint
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter, SchedulerNotReadyError
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Satellite Alarms domain."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    registry = AlarmRegistry(hass)
    await registry.async_load()
    scheduler = SchedulerAdapter(hass)
    manager = AlarmManager(hass, registry, scheduler)

    domain_data[DATA_REGISTRY] = registry
    domain_data[DATA_SCHEDULER_ADAPTER] = scheduler
    domain_data[DATA_ALARM_MANAGER] = manager

    await async_register_services(hass, manager)
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
    return True
