"""Alarm lifecycle orchestration for Satellite Alarms."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    META_DATE,
    META_RECURRENCE,
    META_TIME,
    RECURRENCE_ONCE,
)
from .models import AlarmEndpoint, AlarmRecord
from .registry import AlarmRegistry
from .scheduler_adapter import SchedulerAdapter


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
        """Normalize the date for a recurrence."""
        if recurrence != RECURRENCE_ONCE:
            return None
        return date_value or cls._next_date(time_value)

    async def async_create(
        self,
        *,
        endpoint_id: str,
        time_value: str,
        recurrence: str,
        date_value: str | None = None,
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
        entity_id = self.scheduler.expected_entity_id(alarm_id)
        record = AlarmRecord(
            alarm_id=alarm_id,
            endpoint_entry_id=endpoint.entry_id,
            scheduler_entity_id=entity_id,
            name=name or f"{endpoint.name} alarm",
            metadata={
                META_TIME: time_value,
                META_RECURRENCE: recurrence,
                META_DATE: target_date,
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
                value is not None for value in (time_value, recurrence, date_value)
            )

            if new_recurrence == RECURRENCE_ONCE:
                if date_value is not None:
                    new_date = date_value
                elif current_recurrence == RECURRENCE_ONCE:
                    current_date = record.metadata.get(META_DATE)
                    new_date = str(current_date) if current_date else None
                    if new_date is None:
                        new_date = self._next_date(new_time)
                else:
                    new_date = self._next_date(new_time)
            else:
                new_date = None

            if schedule_changed:
                entity_id = record.scheduler_entity_id or self.scheduler.find_entity_id(alarm_id)
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
                )
                record.scheduler_entity_id = entity_id
                record.metadata[META_TIME] = new_time
                record.metadata[META_RECURRENCE] = new_recurrence
                record.metadata[META_DATE] = new_date

            if name is not None:
                record.name = name

            await self.registry.async_upsert(record)
            return record

    async def async_delete(self, alarm_id: str) -> None:
        """Delete an alarm and its Scheduler Component schedule."""
        async with self._lock:
            record = self._record(alarm_id)
            entity_id = record.scheduler_entity_id or self.scheduler.find_entity_id(alarm_id)
            if entity_id is None:
                raise AlarmNotFoundError(
                    f"Scheduler entity for alarm {alarm_id} could not be found"
                )
            await self.scheduler.async_remove_schedule(entity_id)
            await self.registry.async_remove(alarm_id)

    async def async_set_enabled(self, alarm_id: str, enabled: bool) -> AlarmRecord:
        """Enable or disable an alarm."""
        record = self._record(alarm_id)
        entity_id = record.scheduler_entity_id or self.scheduler.find_entity_id(alarm_id)
        if entity_id is None:
            raise AlarmNotFoundError(
                f"Scheduler entity for alarm {alarm_id} could not be found"
            )
        await self.scheduler.async_set_enabled(entity_id, enabled)
        record.scheduler_entity_id = entity_id
        await self.registry.async_upsert(record)
        return record

    def response(self, record: AlarmRecord) -> dict[str, object]:
        """Build a service response for an alarm."""
        entity_id = record.scheduler_entity_id
        return {
            "alarm_id": record.alarm_id,
            "endpoint_id": record.endpoint_entry_id,
            "name": record.name,
            "scheduler_entity_id": entity_id,
            "time": record.metadata.get(META_TIME),
            "recurrence": record.metadata.get(META_RECURRENCE),
            "date": record.metadata.get(META_DATE),
            "next_trigger": self.scheduler.next_trigger(entity_id) if entity_id else None,
        }

    def fire_event_data(self, alarm_id: str) -> dict[str, object]:
        """Build event data when Scheduler fires an alarm."""
        record = self._record(alarm_id)
        endpoint = self._endpoint(record.endpoint_entry_id)
        return {
            **self.response(record),
            "assist_satellite_entity_id": endpoint.assist_satellite_entity_id,
            "media_player_entity_id": endpoint.media_player_entity_id,
        }
