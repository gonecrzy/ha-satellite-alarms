"""Alarm lifecycle orchestration for Satellite Alarms."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    META_DATE,
    META_DAYS,
    META_RECURRENCE,
    META_TIME,
    RECURRENCE_ONCE,
    RECURRENCE_SELECTED_DAYS,
    WEEKDAYS,
)
from .models import AlarmEndpoint, AlarmRecord
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter

_LOGGER = logging.getLogger(__name__)


class AlarmNotFoundError(ValueError):
    """Raised when an alarm ID is unknown."""


class EndpointNotFoundError(ValueError):
    """Raised when an endpoint config entry is unknown."""


class AlarmManager:
    """Coordinate alarm metadata with Scheduler Component."""

    def __init__(
        self,
        hass: HomeAssistant,
        registry: AlarmRegistry,
        scheduler: SchedulerAdapter,
    ) -> None:
        """Initialize the alarm manager."""
        self.hass = hass
        self.registry = registry
        self.scheduler = scheduler
        self._lock = asyncio.Lock()

    def _endpoint(self, entry_id: str) -> AlarmEndpoint:
        """Resolve one configured Satellite Alarms endpoint."""
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise EndpointNotFoundError(f"Unknown Satellite Alarms endpoint: {entry_id}")
        return AlarmEndpoint.from_config_entry(entry)

    def _record(self, alarm_id: str) -> AlarmRecord:
        """Return an alarm record or raise."""
        record = self.registry.get(alarm_id)
        if record is None:
            raise AlarmNotFoundError(f"Unknown alarm: {alarm_id}")
        return record

    @staticmethod
    def _next_date(time_value: str) -> str:
        """Return today or tomorrow for the next occurrence of a local time."""
        parsed_time = dt_util.parse_time(time_value)
        if parsed_time is None:
            raise ValueError(f"Invalid alarm time: {time_value}")

        now = dt_util.now()
        target = datetime.combine(now.date(), parsed_time, tzinfo=now.tzinfo)
        if target <= now:
            target += timedelta(days=1)
        return target.date().isoformat()

    @classmethod
    def _normalize_date(
        cls,
        *,
        recurrence: str,
        time_value: str,
        date_value: str | None,
    ) -> str | None:
        """Normalize the date for a recurrence and reject past one-time alarms."""
        if recurrence != RECURRENCE_ONCE:
            return None

        target_date = date_value or cls._next_date(time_value)
        parsed_date = dt_util.parse_date(target_date)
        parsed_time = dt_util.parse_time(time_value)
        if parsed_date is None or parsed_time is None:
            raise ValueError("Invalid one-time alarm date or time")

        now = dt_util.now()
        target = datetime.combine(parsed_date, parsed_time, tzinfo=now.tzinfo)
        if target <= now:
            raise ValueError("One-time alarm must be scheduled in the future")
        return target_date

    @staticmethod
    def _normalize_days(
        recurrence: str,
        days: list[str] | tuple[str, ...] | None,
    ) -> list[str] | None:
        """Normalize selected weekdays and reject invalid combinations."""
        if recurrence != RECURRENCE_SELECTED_DAYS:
            if days:
                raise ValueError("days can only be used with selected_days recurrence")
            return None

        requested = list(days or ())
        normalized = [day for day in WEEKDAYS if day in requested]
        if not normalized:
            raise ValueError("Selected-day alarms require at least one weekday")
        if len(normalized) != len(set(requested)):
            raise ValueError("Selected-day alarms contain an invalid weekday")
        return normalized

    async def async_create(
        self,
        *,
        endpoint_id: str,
        time_value: str,
        recurrence: str,
        date_value: str | None = None,
        days: list[str] | tuple[str, ...] | None = None,
        name: str | None = None,
    ) -> AlarmRecord:
        """Create an alarm and its Scheduler Component schedule."""
        endpoint = self._endpoint(endpoint_id)
        alarm_id = uuid4().hex
        target_date = self._normalize_date(
            recurrence=recurrence,
            time_value=time_value,
            date_value=date_value,
        )
        target_days = self._normalize_days(recurrence, days)
        entity_id = self.scheduler.expected_entity_id(alarm_id)
        record = AlarmRecord(
            alarm_id=alarm_id,
            endpoint_entry_id=endpoint.entry_id,
            scheduler_entity_id=entity_id,
            name=name.strip() if name and name.strip() else f"{endpoint.name} alarm",
            metadata={
                META_TIME: time_value,
                META_RECURRENCE: recurrence,
                META_DATE: target_date,
                META_DAYS: target_days,
            },
        )

        async with self._lock:
            await self.registry.async_upsert(record)
            try:
                await self.scheduler.async_create_schedule(
                    alarm_id=alarm_id,
                    time=time_value,
                    recurrence=recurrence,
                    date=target_date,
                    days=target_days,
                )
            except Exception:
                await self.registry.async_remove(alarm_id)
                raise

        return record

    async def async_update(
        self,
        *,
        alarm_id: str,
        time_value: str | None = None,
        recurrence: str | None = None,
        date_value: str | None = None,
        days: list[str] | tuple[str, ...] | None = None,
        name: str | None = None,
    ) -> AlarmRecord:
        """Update alarm metadata and, when needed, its Scheduler schedule."""
        async with self._lock:
            record = self._record(alarm_id)
            self._endpoint(record.endpoint_entry_id)

            current_time = str(record.metadata[META_TIME])
            current_recurrence = str(record.metadata[META_RECURRENCE])
            new_time = time_value or current_time
            new_recurrence = recurrence or current_recurrence

            schedule_changed = any(
                value is not None for value in (time_value, recurrence, date_value, days)
            )

            if new_recurrence == RECURRENCE_ONCE:
                current_date = record.metadata.get(META_DATE)
                candidate_date = date_value
                if candidate_date is None and current_recurrence == RECURRENCE_ONCE:
                    candidate_date = str(current_date) if current_date else None
                new_date = self._normalize_date(
                    recurrence=new_recurrence,
                    time_value=new_time,
                    date_value=candidate_date,
                )
            else:
                new_date = None

            if new_recurrence == RECURRENCE_SELECTED_DAYS:
                candidate_days = days
                if candidate_days is None and current_recurrence == RECURRENCE_SELECTED_DAYS:
                    stored_days = record.metadata.get(META_DAYS)
                    candidate_days = list(stored_days) if stored_days else None
                new_days = self._normalize_days(new_recurrence, candidate_days)
            else:
                new_days = self._normalize_days(new_recurrence, days)

            if schedule_changed:
                entity_id = self.scheduler.find_entity_id(alarm_id) or record.scheduler_entity_id
                if entity_id is None:
                    raise AlarmNotFoundError(
                        f"Scheduler entity for alarm {alarm_id} could not be found"
                    )
                await self.scheduler.async_update_schedule(
                    entity_id=entity_id,
                    alarm_id=alarm_id,
                    time=new_time,
                    recurrence=new_recurrence,
                    date=new_date,
                    days=new_days,
                )
                record.scheduler_entity_id = entity_id
                record.metadata[META_TIME] = new_time
                record.metadata[META_RECURRENCE] = new_recurrence
                record.metadata[META_DATE] = new_date
                record.metadata[META_DAYS] = new_days

            if name is not None:
                normalized_name = name.strip()
                if not normalized_name:
                    raise ValueError("Alarm name cannot be empty")
                record.name = normalized_name

            await self.registry.async_upsert(record)
            return record

    async def async_delete(self, alarm_id: str) -> None:
        """Delete an alarm and its Scheduler Component schedule."""
        async with self._lock:
            record = self._record(alarm_id)
            entity_id = self.scheduler.find_entity_id(alarm_id) or record.scheduler_entity_id
            if entity_id is None:
                raise AlarmNotFoundError(
                    f"Scheduler entity for alarm {alarm_id} could not be found"
                )
            await self.scheduler.async_remove_schedule(entity_id)
            await self.registry.async_remove(alarm_id)

    async def async_set_enabled(self, alarm_id: str, enabled: bool) -> AlarmRecord:
        """Enable or disable an alarm."""
        async with self._lock:
            record = self._record(alarm_id)
            entity_id = self.scheduler.find_entity_id(alarm_id) or record.scheduler_entity_id
            if entity_id is None:
                raise AlarmNotFoundError(
                    f"Scheduler entity for alarm {alarm_id} could not be found"
                )
            await self.scheduler.async_set_enabled(entity_id, enabled)
            record.scheduler_entity_id = entity_id
            await self.registry.async_upsert(record)
            return record

    async def async_reconcile(self) -> tuple[int, int]:
        """Reconcile cached Scheduler entity IDs using stable alarm tags."""
        matched = 0
        missing = 0
        changed = False

        async with self._lock:
            for record in self.registry.all():
                entity_id = self.scheduler.find_entity_id(record.alarm_id)
                if entity_id is None:
                    missing += 1
                    _LOGGER.warning(
                        "Scheduler schedule for alarm %s (%s) was not found",
                        record.alarm_id,
                        record.name,
                    )
                    continue

                matched += 1
                if record.scheduler_entity_id != entity_id:
                    record.scheduler_entity_id = entity_id
                    changed = True

            if changed:
                await self.registry.async_save()

        return matched, missing

    def alarms_for_endpoint(self, endpoint_id: str) -> tuple[AlarmRecord, ...]:
        """Return all alarms for a configured endpoint."""
        self._endpoint(endpoint_id)
        return self.registry.for_endpoint(endpoint_id)

    def find_by_name(self, endpoint_id: str, name: str) -> tuple[AlarmRecord, ...]:
        """Find alarms on an endpoint by exact case-insensitive name."""
        requested = name.strip().casefold()
        return tuple(
            record
            for record in self.alarms_for_endpoint(endpoint_id)
            if (record.name or "").strip().casefold() == requested
        )

    def find_by_time(self, endpoint_id: str, time_value: str) -> tuple[AlarmRecord, ...]:
        """Find alarms on an endpoint by normalized clock time."""
        return tuple(
            record
            for record in self.alarms_for_endpoint(endpoint_id)
            if record.metadata.get(META_TIME) == time_value
        )

    def trigger_for_record(self, record: AlarmRecord) -> datetime | None:
        """Return Scheduler Component's next trigger for one record."""
        entity_id = self.scheduler.find_entity_id(record.alarm_id) or record.scheduler_entity_id
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state != STATE_ON:
            return None
        next_trigger = self.scheduler.next_trigger(entity_id)
        if not next_trigger:
            return None
        trigger = dt_util.parse_datetime(str(next_trigger))
        if trigger is None:
            return None
        if trigger.tzinfo is None:
            trigger = trigger.replace(tzinfo=dt_util.now().tzinfo)
        return trigger

    def next_alarm_for_endpoint(self, endpoint_id: str):
        """Return the next Scheduler-backed alarm for an endpoint."""
        candidates = [
            (trigger, record)
            for record in self.alarms_for_endpoint(endpoint_id)
            if (trigger := self.trigger_for_record(record)) is not None
        ]
        if not candidates:
            return None

        trigger, record = min(candidates, key=lambda item: item[0])
        return record, trigger

    def sorted_alarms_for_endpoint(self, endpoint_id: str) -> tuple[AlarmRecord, ...]:
        """Return endpoint alarms ordered by Scheduler next trigger, then name."""
        records = list(self.alarms_for_endpoint(endpoint_id))

        def sort_key(record: AlarmRecord) -> tuple[int, datetime, str]:
            trigger = self.trigger_for_record(record)
            if trigger is None:
                return (1, dt_util.now() + timedelta(days=36500), record.name or "")
            return (0, trigger, record.name or "")

        return tuple(sorted(records, key=sort_key))

    def response(self, record: AlarmRecord) -> dict[str, object]:
        """Build a service response for an alarm."""
        entity_id = self.scheduler.find_entity_id(record.alarm_id) or record.scheduler_entity_id
        state = self.hass.states.get(entity_id) if entity_id else None
        return {
            "alarm_id": record.alarm_id,
            "endpoint_id": record.endpoint_entry_id,
            "name": record.name,
            "scheduler_entity_id": entity_id,
            "time": record.metadata.get(META_TIME),
            "recurrence": record.metadata.get(META_RECURRENCE),
            "date": record.metadata.get(META_DATE),
            "days": record.metadata.get(META_DAYS),
            "enabled": state.state == STATE_ON if state else None,
            "next_trigger": self.scheduler.next_trigger(entity_id) if entity_id else None,
        }

    def list_responses(self, endpoint_id: str | None = None) -> list[dict[str, object]]:
        """Return service-ready alarm data, optionally scoped to one endpoint."""
        records = (
            self.sorted_alarms_for_endpoint(endpoint_id)
            if endpoint_id
            else self.registry.all()
        )
        return [self.response(record) for record in records]

    def fire_event_data(self, alarm_id: str) -> dict[str, object]:
        """Build event data when Scheduler fires an alarm."""
        record = self._record(alarm_id)
        endpoint = self._endpoint(record.endpoint_entry_id)
        return {
            **self.response(record),
            "assist_satellite_entity_id": endpoint.assist_satellite_entity_id,
            "media_player_entity_id": endpoint.media_player_entity_id,
        }
