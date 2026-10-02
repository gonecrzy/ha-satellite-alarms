"""Data models for Satellite Alarms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_ADDITIONAL_PLAYBACK_TARGETS,
    CONF_AREA_ID,
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
)


@dataclass(frozen=True, slots=True)
class PlaybackTarget:
    """One Assist satellite paired with its volume-control media player."""

    assist_satellite_entity_id: str
    media_player_entity_id: str


@dataclass(frozen=True, slots=True)
class AlarmEndpoint:
    """A room-level alarm endpoint with one or more satellite/player pairs."""

    entry_id: str
    name: str
    assist_satellite_entity_id: str
    media_player_entity_id: str
    area_id: str | None = None
    additional_playback_targets: tuple[PlaybackTarget, ...] = ()

    @classmethod
    def from_config_entry(cls, entry: ConfigEntry) -> AlarmEndpoint:
        """Build an endpoint from a Home Assistant config entry."""
        additional: list[PlaybackTarget] = []
        for item in entry.data.get(CONF_ADDITIONAL_PLAYBACK_TARGETS, []):
            if not isinstance(item, Mapping):
                continue
            satellite = item.get(CONF_ASSIST_SATELLITE)
            player = item.get(CONF_MEDIA_PLAYER)
            if satellite and player:
                additional.append(
                    PlaybackTarget(
                        assist_satellite_entity_id=str(satellite),
                        media_player_entity_id=str(player),
                    )
                )

        return cls(
            entry_id=entry.entry_id,
            name=entry.data[CONF_NAME],
            assist_satellite_entity_id=entry.data[CONF_ASSIST_SATELLITE],
            media_player_entity_id=entry.data[CONF_MEDIA_PLAYER],
            area_id=entry.data.get(CONF_AREA_ID),
            additional_playback_targets=tuple(additional),
        )

    @property
    def primary_playback_target(self) -> PlaybackTarget:
        """Return the primary satellite/player pair."""
        return PlaybackTarget(
            assist_satellite_entity_id=self.assist_satellite_entity_id,
            media_player_entity_id=self.media_player_entity_id,
        )

    @property
    def playback_targets(self) -> tuple[PlaybackTarget, ...]:
        """Return primary first followed by additional room targets."""
        return (self.primary_playback_target, *self.additional_playback_targets)

    @property
    def assist_satellite_entity_ids(self) -> tuple[str, ...]:
        """Return all satellites that identify this room endpoint."""
        return tuple(target.assist_satellite_entity_id for target in self.playback_targets)

    @property
    def media_player_entity_ids(self) -> tuple[str, ...]:
        """Return all alarm media players in this room endpoint."""
        return tuple(target.media_player_entity_id for target in self.playback_targets)


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
