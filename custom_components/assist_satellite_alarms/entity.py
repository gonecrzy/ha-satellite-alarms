"""Shared room entity support for Satellite Alarms."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alarm_manager import AlarmManager
from .const import (
    DATA_ALARM_MANAGER,
    DATA_PLAYBACK_MANAGER,
    DOMAIN,
    SIGNAL_ALARMS_UPDATED,
    SIGNAL_PLAYBACK_UPDATED,
)
from .models import AlarmEndpoint, AlarmRecord
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



class SatelliteAlarmEntity(SatelliteAlarmRoomEntity):
    """Base entity representing one managed alarm inside a room."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        alarm_id: str,
        key: str,
    ) -> None:
        """Initialize an alarm-specific entity."""
        self.alarm_id = alarm_id
        super().__init__(hass, entry, f"alarm_{alarm_id}_{key}")

    @property
    def record(self) -> AlarmRecord | None:
        """Return current alarm metadata."""
        record = self.manager.registry.get(self.alarm_id)
        if record is None or record.endpoint_entry_id != self.entry.entry_id:
            return None
        return record

    @property
    def alarm_display_name(self) -> str:
        """Return the current user-facing alarm name."""
        record = self.record
        return (record.name if record and record.name else "Alarm").strip()

    @property
    def available(self) -> bool:
        """Return whether this alarm still belongs to the room."""
        return self.record is not None


def setup_dynamic_alarm_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory,
) -> None:
    """Keep one dynamic entity type synchronized with the room alarm registry."""
    manager: AlarmManager = hass.data[DOMAIN][DATA_ALARM_MANAGER]
    entities: dict[str, Entity] = {}

    @callback
    def sync_entities() -> None:
        records = {
            record.alarm_id: record
            for record in manager.alarms_for_endpoint(entry.entry_id)
        }

        for alarm_id in set(entities) - set(records):
            entity = entities.pop(alarm_id)
            hass.async_create_task(entity.async_remove(force_remove=True))

        new_entities = []
        for alarm_id in records:
            if alarm_id in entities:
                continue
            entity = factory(hass, entry, alarm_id)
            entities[alarm_id] = entity
            new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_ALARMS_UPDATED,
            sync_entities,
        )
    )
