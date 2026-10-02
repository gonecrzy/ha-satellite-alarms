"""Diagnostics support for Satellite Alarms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .alarm_manager import AlarmManager
from .const import (
    CONF_PLAYBACK_MODE,
    DATA_ALARM_MANAGER,
    DATA_PLAYBACK_MANAGER,
    DATA_REGISTRY,
    DATA_SCHEDULER_ADAPTER,
    DEFAULT_PLAYBACK_MODE,
    DOMAIN,
)
from .models import AlarmEndpoint
from .playback import PlaybackManager
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return operational diagnostics for one configured room endpoint."""
    domain_data = hass.data.get(DOMAIN, {})
    registry: AlarmRegistry | None = domain_data.get(DATA_REGISTRY)
    adapter: SchedulerAdapter | None = domain_data.get(DATA_SCHEDULER_ADAPTER)
    manager: AlarmManager | None = domain_data.get(DATA_ALARM_MANAGER)
    playback: PlaybackManager | None = domain_data.get(DATA_PLAYBACK_MANAGER)
    endpoint = AlarmEndpoint.from_config_entry(entry)

    playback_targets = []
    for target in endpoint.playback_targets:
        satellite_state = hass.states.get(target.assist_satellite_entity_id)
        player_state = hass.states.get(target.media_player_entity_id)
        playback_targets.append(
            {
                "assist_satellite_entity_id": target.assist_satellite_entity_id,
                "assist_satellite_state": satellite_state.state if satellite_state else None,
                "media_player_entity_id": target.media_player_entity_id,
                "media_player_state": player_state.state if player_state else None,
                "media_player_volume": (
                    player_state.attributes.get("volume_level") if player_state else None
                ),
            }
        )

    alarms: list[dict[str, Any]] = []
    if registry:
        for record in registry.for_endpoint(entry.entry_id):
            response = manager.response(record) if manager else {}
            alarms.append(
                {
                    "alarm_id": record.alarm_id,
                    "name": record.name,
                    "scheduler_entity_id": response.get(
                        "scheduler_entity_id", record.scheduler_entity_id
                    ),
                    "scheduler_found": bool(
                        adapter and adapter.find_entity_id(record.alarm_id)
                    ),
                    "time": record.metadata.get("time"),
                    "recurrence": record.metadata.get("recurrence"),
                    "date": record.metadata.get("date"),
                    "days": record.metadata.get("days"),
                    "enabled": response.get("enabled"),
                    "next_trigger": response.get("next_trigger"),
                    "skip_next": record.metadata.get("skip_next", False),
                    "override": record.metadata.get("override"),
                    "has_alarm_media_override": bool(record.metadata.get("alarm_media")),
                    "alarm_volume_override": record.metadata.get("alarm_volume"),
                    "snooze_minutes_override": record.metadata.get("snooze_minutes"),
                }
            )

    active_data: dict[str, Any] | None = None
    queued: list[str] = []
    if playback:
        queued = list(playback.queued_for_endpoint(entry.entry_id))
        active = playback.active_for_endpoint(entry.entry_id)
        if active:
            active_data = {
                "alarm_id": active.alarm_id,
                "started_at": active.started_at.isoformat(),
                "playback_mode": active.playback_mode,
                "current_assist_satellite": active.assist_satellite_entity_id,
                "current_media_player": active.media_player_entity_id,
                "targets": [
                    {
                        "assist_satellite_entity_id": target.assist_satellite_entity_id,
                        "media_player_entity_id": target.media_player_entity_id,
                        "previous_volume": target.previous_volume,
                        "touched": target.touched,
                    }
                    for target in active.targets
                ],
            }

    return {
        "endpoint": {
            "entry_id": endpoint.entry_id,
            "name": endpoint.name,
            "area_id": endpoint.area_id,
            "playback_mode": entry.options.get(
                CONF_PLAYBACK_MODE, DEFAULT_PLAYBACK_MODE
            ),
            "playback_targets": playback_targets,
        },
        "options": dict(entry.options),
        "scheduler_ready": bool(adapter and adapter.is_ready),
        "alarm_record_count": len(alarms),
        "alarms": alarms,
        "active_alarm": active_data,
        "queued_alarm_ids": queued,
    }
