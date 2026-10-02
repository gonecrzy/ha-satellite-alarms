"""Scheduler Component adapter for Satellite Alarms."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    ATTR_ALARM_ID,
    DOMAIN,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_SELECTED_DAYS,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKENDS,
    SCHEDULER_DOMAIN,
    WEEKDAYS,
)

SERVICE_ADD = "add"
SERVICE_EDIT = "edit"
SERVICE_REMOVE = "remove"

_REQUIRED_SERVICES = (SERVICE_ADD, SERVICE_EDIT, SERVICE_REMOVE)

_SCHEDULER_DAILY = "daily"
_SCHEDULER_WORKDAY = "workday"
_SCHEDULER_WEEKEND = "weekend"
_REPEAT = "repeat"
_SINGLE = "single"


class SchedulerNotReadyError(RuntimeError):
    """Raised when Scheduler Component is not ready for use."""


class SchedulerAdapter:
    """Boundary between Satellite Alarms and Scheduler Component."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the adapter."""
        self.hass = hass

    @property
    def is_ready(self) -> bool:
        """Return whether the Scheduler Component service API is ready."""
        return all(
            self.hass.services.has_service(SCHEDULER_DOMAIN, service)
            for service in _REQUIRED_SERVICES
        )

    def ensure_ready(self) -> None:
        """Raise if Scheduler Component is not installed/configured and ready."""
        if not self.is_ready:
            raise SchedulerNotReadyError(
                "Scheduler Component is not ready. Install it, add the Scheduler "
                "integration in Home Assistant, and restart/reload before setting "
                "up Satellite Alarms."
            )

    @staticmethod
    def alarm_tag(alarm_id: str) -> str:
        """Return the stable Scheduler tag for an alarm."""
        return f"{DOMAIN}:{alarm_id}"

    @staticmethod
    def schedule_name(alarm_id: str) -> str:
        """Return the immutable internal Scheduler schedule name."""
        return f"Assist Satellite Alarm {alarm_id}"

    @classmethod
    def expected_entity_id(cls, alarm_id: str) -> str:
        """Return the Scheduler entity ID produced by the immutable name."""
        return f"switch.schedule_{slugify(cls.schedule_name(alarm_id))}"

    @staticmethod
    def _weekdays_for_recurrence(
        recurrence: str, days: list[str] | tuple[str, ...] | None = None
    ) -> list[str]:
        """Translate a Satellite Alarms recurrence to Scheduler Component."""
        if recurrence == RECURRENCE_SELECTED_DAYS:
            normalized = [day for day in WEEKDAYS if days and day in days]
            if not normalized:
                raise ValueError("Selected-day alarms require at least one weekday")
            if len(normalized) != len(set(days or ())):
                raise ValueError("Selected-day alarms contain an invalid weekday")
            return normalized

        mapping = {
            RECURRENCE_ONCE: [_SCHEDULER_DAILY],
            RECURRENCE_DAILY: [_SCHEDULER_DAILY],
            RECURRENCE_WEEKDAYS: [_SCHEDULER_WORKDAY],
            RECURRENCE_WEEKENDS: [_SCHEDULER_WEEKEND],
        }
        return mapping[recurrence]

    @classmethod
    def build_schedule_payload(
        cls,
        *,
        alarm_id: str,
        time: str,
        recurrence: str,
        date: str | None,
        days: list[str] | tuple[str, ...] | None = None,
        include_name: bool = True,
    ) -> dict[str, Any]:
        """Build a Scheduler Component add/edit payload."""
        if recurrence == RECURRENCE_ONCE and date is None:
            raise ValueError("One-time alarms require a date")

        payload: dict[str, Any] = {
            "weekdays": cls._weekdays_for_recurrence(recurrence, days),
            "start_date": date if recurrence == RECURRENCE_ONCE else None,
            "end_date": date if recurrence == RECURRENCE_ONCE else None,
            "timeslots": [
                {
                    "start": time,
                    "actions": [
                        {
                            "service": f"{DOMAIN}.fire",
                            "service_data": {ATTR_ALARM_ID: alarm_id},
                        }
                    ],
                }
            ],
            "repeat_type": _SINGLE if recurrence == RECURRENCE_ONCE else _REPEAT,
            "tags": [DOMAIN, cls.alarm_tag(alarm_id)],
        }
        if include_name:
            payload["name"] = cls.schedule_name(alarm_id)
        return payload

    @classmethod
    def build_snooze_payload(
        cls,
        *,
        alarm_id: str,
        occurrence_id: str,
        trigger_at,
    ) -> dict[str, Any]:
        """Build a transient one-time schedule for a snoozed occurrence."""
        date = trigger_at.date().isoformat()
        return {
            "name": f"Assist Satellite Alarm Snooze {occurrence_id}",
            "weekdays": [_SCHEDULER_DAILY],
            "start_date": date,
            "end_date": date,
            "timeslots": [
                {
                    "start": trigger_at.strftime("%H:%M:%S"),
                    "actions": [
                        {
                            "service": f"{DOMAIN}.fire",
                            "service_data": {ATTR_ALARM_ID: alarm_id},
                        }
                    ],
                }
            ],
            "repeat_type": _SINGLE,
            "tags": [
                DOMAIN,
                f"{DOMAIN}:snooze:{occurrence_id}",
                f"{DOMAIN}:parent:{alarm_id}",
            ],
        }

    async def async_create_schedule(
        self,
        *,
        alarm_id: str,
        time: str,
        recurrence: str,
        date: str | None,
        days: list[str] | tuple[str, ...] | None = None,
    ) -> str:
        """Create a persistent Scheduler Component schedule."""
        self.ensure_ready()
        payload = self.build_schedule_payload(
            alarm_id=alarm_id,
            time=time,
            recurrence=recurrence,
            date=date,
            days=days,
        )
        await self.hass.services.async_call(
            SCHEDULER_DOMAIN,
            SERVICE_ADD,
            payload,
            blocking=True,
        )
        return self.expected_entity_id(alarm_id)

    async def async_create_snooze_schedule(self, *, alarm_id: str, minutes: int) -> str:
        """Create a transient Scheduler schedule for a snoozed occurrence."""
        self.ensure_ready()
        occurrence_id = uuid4().hex
        trigger_at = dt_util.now() + timedelta(minutes=minutes)
        payload = self.build_snooze_payload(
            alarm_id=alarm_id,
            occurrence_id=occurrence_id,
            trigger_at=trigger_at,
        )
        await self.hass.services.async_call(
            SCHEDULER_DOMAIN,
            SERVICE_ADD,
            payload,
            blocking=True,
        )
        return f"switch.schedule_{slugify(payload['name'])}"

    async def async_update_schedule(
        self,
        *,
        entity_id: str,
        alarm_id: str,
        time: str,
        recurrence: str,
        date: str | None,
        days: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """Update a Scheduler Component schedule."""
        self.ensure_ready()
        payload = self.build_schedule_payload(
            alarm_id=alarm_id,
            time=time,
            recurrence=recurrence,
            date=date,
            days=days,
            include_name=False,
        )
        payload[ATTR_ENTITY_ID] = entity_id
        await self.hass.services.async_call(
            SCHEDULER_DOMAIN,
            SERVICE_EDIT,
            payload,
            blocking=True,
        )

    async def async_remove_schedule(self, entity_id: str) -> None:
        """Remove a Scheduler Component schedule."""
        self.ensure_ready()
        await self.hass.services.async_call(
            SCHEDULER_DOMAIN,
            SERVICE_REMOVE,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

    async def async_set_enabled(self, entity_id: str, enabled: bool) -> None:
        """Enable or disable a Scheduler schedule through its switch entity."""
        service = SERVICE_TURN_ON if enabled else SERVICE_TURN_OFF
        await self.hass.services.async_call(
            "switch",
            service,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

    def find_entity_id(self, alarm_id: str) -> str | None:
        """Find a Scheduler entity by the stable alarm tag."""
        tag = self.alarm_tag(alarm_id)
        for state in self.hass.states.async_all("switch"):
            if tag in state.attributes.get("tags", []):
                return state.entity_id
        return None

    def next_trigger(self, entity_id: str) -> str | None:
        """Return Scheduler Component's next trigger for an entity."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return state.attributes.get("next_trigger")
