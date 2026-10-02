"""Diagnostics support for Satellite Alarms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_REGISTRY, DATA_SCHEDULER_ADAPTER, DOMAIN
from .models import AlarmEndpoint
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for one configured endpoint."""
    domain_data = hass.data.get(DOMAIN, {})
    registry: AlarmRegistry | None = domain_data.get(DATA_REGISTRY)
    adapter: SchedulerAdapter | None = domain_data.get(DATA_SCHEDULER_ADAPTER)
    endpoint = AlarmEndpoint.from_config_entry(entry)

    return {
        "endpoint": {
            "entry_id": endpoint.entry_id,
            "name": endpoint.name,
            "area_id": endpoint.area_id,
            "assist_satellite_entity_ids": list(endpoint.assist_satellite_entity_ids),
            "media_player_entity_ids": list(endpoint.media_player_entity_ids),
            "playback_targets": [
                {
                    "assist_satellite_entity_id": target.assist_satellite_entity_id,
                    "media_player_entity_id": target.media_player_entity_id,
                }
                for target in endpoint.playback_targets
            ],
        },
        "options": dict(entry.options),
        "scheduler_ready": bool(adapter and adapter.is_ready),
        "alarm_record_count": (len(registry.for_endpoint(entry.entry_id)) if registry else 0),
    }
