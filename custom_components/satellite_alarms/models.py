"""Data models for Satellite Alarms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_AREA_ID,
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
)


@dataclass(frozen=True, slots=True)
class AlarmEndpoint:
    """A configured Assist satellite and its alarm media player."""

    entry_id: str
    name: str
    assist_satellite_entity_id: str
    media_player_entity_id: str
    area_id: str | None = None

    @classmethod
    def from_config_entry(cls, entry: ConfigEntry) -> AlarmEndpoint:
        """Build an endpoint from a Home Assistant config entry."""
        return cls(
            entry_id=entry.entry_id,
            name=entry.data[CONF_NAME],
            assist_satellite_entity_id=entry.data[CONF_ASSIST_SATELLITE],
            media_player_entity_id=entry.data[CONF_MEDIA_PLAYER],
            area_id=entry.data.get(CONF_AREA_ID),
        )


@dataclass(slots=True)
class AlarmRecord:
    """Satellite Alarms metadata associated with a Scheduler schedule.

    Scheduler Component remains the source of truth for actual schedule timing,
    recurrence, enabled state, persistence, and next trigger.
    """

    alarm_id: str
    endpoint_entry_id: str
    scheduler_entity_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the record for Home Assistant storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AlarmRecord:
        """Deserialize a record from Home Assistant storage."""
        return cls(
            alarm_id=str(data["alarm_id"]),
            endpoint_entry_id=str(data["endpoint_entry_id"]),
            scheduler_entity_id=data.get("scheduler_entity_id"),
            name=data.get("name"),
            metadata=dict(data.get("metadata", {})),
        )
