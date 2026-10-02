"""Repair issue monitoring for Satellite Alarms room endpoints."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    META_DATE,
    META_RECURRENCE,
    META_TIME,
    RECURRENCE_ONCE,
    SIGNAL_ALARMS_UPDATED,
)
from .models import AlarmEndpoint
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter


class RoomHealthMonitor:
    """Create and clear actionable repair issues for one alarm room."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        registry: AlarmRegistry,
        scheduler: SchedulerAdapter,
    ) -> None:
        """Initialize a room health monitor."""
        self.hass = hass
        self.entry = entry
        self.registry = registry
        self.scheduler = scheduler
        self.endpoint = AlarmEndpoint.from_config_entry(entry)
        self._known_issue_ids: set[str] = set()
        self._unsubscribers: list[CALLBACK_TYPE] = []

    def start(self) -> None:
        """Start monitoring room configuration and schedule health."""
        self._unsubscribers.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ALARMS_UPDATED,
                self._handle_alarm_update,
            )
        )
        self._unsubscribers.append(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._handle_state_changed)
        )

        if self.hass.state is CoreState.running:
            self._check()
        else:
            self._unsubscribers.append(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    self._handle_started,
                )
            )

    def stop(self) -> None:
        """Stop monitoring and clear issues owned by this monitor."""
        while self._unsubscribers:
            self._unsubscribers.pop()()
        for issue_id in self._known_issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._known_issue_ids.clear()

    @callback
    def _handle_started(self, _event: Event) -> None:
        """Check health once Home Assistant has completed startup."""
        self._check()

    @callback
    def _handle_alarm_update(self) -> None:
        """Recheck after alarm metadata changes."""
        self._check()

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        """Recheck when a relevant room or Scheduler entity changes."""
        entity_id = event.data.get("entity_id")
        if not isinstance(entity_id, str):
            return
        if entity_id in self._target_entity_ids or entity_id.startswith("switch.schedule_"):
            self._check()

    @property
    def _target_entity_ids(self) -> set[str]:
        """Return all configured satellite and media-player entities."""
        return {
            *self.endpoint.assist_satellite_entity_ids,
            *self.endpoint.media_player_entity_ids,
        }

    @staticmethod
    def _safe_issue_fragment(value: str) -> str:
        """Convert an entity/alarm identifier into a stable issue-ID fragment."""
        return value.replace(".", "_").replace(":", "_")

    @callback
    def _check(self) -> None:
        """Synchronize repair issues with current room health."""
        desired: set[str] = set()
        entity_registry = er.async_get(self.hass)

        for entity_id in sorted(self._target_entity_ids):
            if (
                entity_registry.async_get(entity_id) is not None
                or self.hass.states.get(entity_id) is not None
            ):
                issue_id = (
                    f"{self.entry.entry_id}_missing_target_{self._safe_issue_fragment(entity_id)}"
                )
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue

            issue_id = (
                f"{self.entry.entry_id}_missing_target_{self._safe_issue_fragment(entity_id)}"
            )
            desired.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_room_target",
                translation_placeholders={
                    "room": self.endpoint.name,
                    "entity_id": entity_id,
                },
            )

        for record in self.registry.for_endpoint(self.entry.entry_id):
            issue_id = f"{self.entry.entry_id}_missing_schedule_{record.alarm_id}"
            if self.scheduler.find_entity_id(record.alarm_id) is not None:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue

            if record.metadata.get(META_RECURRENCE) == RECURRENCE_ONCE:
                date_value = record.metadata.get(META_DATE)
                time_value = record.metadata.get(META_TIME)
                parsed_date = dt_util.parse_date(str(date_value)) if date_value else None
                parsed_time = dt_util.parse_time(str(time_value)) if time_value else None
                if parsed_date and parsed_time:
                    scheduled = dt_util.start_of_local_day(parsed_date).replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute,
                        second=parsed_time.second,
                    )
                    if scheduled <= dt_util.now():
                        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                        continue

            desired.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_alarm_schedule",
                translation_placeholders={
                    "room": self.endpoint.name,
                    "alarm": record.name or record.alarm_id,
                },
            )

        for stale_issue_id in self._known_issue_ids - desired:
            ir.async_delete_issue(self.hass, DOMAIN, stale_issue_id)
        self._known_issue_ids = desired
