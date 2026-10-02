"""Shared room entity support for Satellite Alarms."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .alarm_manager import AlarmManager
from .const import (
    DATA_ALARM_MANAGER,
    DATA_PLAYBACK_MANAGER,
    DOMAIN,
    SIGNAL_ALARMS_UPDATED,
    SIGNAL_PLAYBACK_UPDATED,
)
from .models import AlarmEndpoint
from .playback import PlaybackManager


class SatelliteAlarmRoomEntity(Entity):
    """Base entity representing one Satellite Alarms room endpoint."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str) -> None:
        """Initialize a room entity."""
        self.hass = hass
        self.entry = entry
        self.endpoint: AlarmEndpoint = entry.runtime_data
        self.manager: AlarmManager = hass.data[DOMAIN][DATA_ALARM_MANAGER]
        self.playback: PlaybackManager = hass.data[DOMAIN][DATA_PLAYBACK_MANAGER]
        self._attr_unique_id = f"{entry.entry_id}_{key}"

        suggested_area: str | None = None
        if self.endpoint.area_id:
            area = ar.async_get(hass).async_get_area(self.endpoint.area_id)
            if area is not None:
                suggested_area = area.name

        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Satellite Alarms",
            model="Room alarm endpoint",
            name=self.endpoint.name,
            suggested_area=suggested_area,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to local alarm/playback and Scheduler state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ALARMS_UPDATED,
                self._handle_local_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PLAYBACK_UPDATED,
                self._handle_local_update,
            )
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._handle_state_changed)
        )

    @callback
    def _handle_local_update(self) -> None:
        """Refresh when Satellite Alarms changes registry or playback state."""
        self.async_write_ha_state()

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        """Refresh when one of our Scheduler switches changes."""
        entity_id = event.data.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith("switch.schedule_"):
            return

        state = event.data.get("new_state") or event.data.get("old_state")
        if state is None:
            return
        tags = state.attributes.get("tags", [])
        if DOMAIN not in tags:
            return
        self.async_write_ha_state()
