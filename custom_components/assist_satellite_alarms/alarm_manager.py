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
    META_ALARM_MEDIA,
    META_ALARM_VOLUME,
    META_DATE,
    META_DAYS,
    META_FAILURE_ACTIONS,
    META_OVERRIDE,
    META_POST_ACTIONS,
    META_PRE_ACTIONS,
    META_RECURRENCE,
    META_SKIP_NEXT,
    META_SNOOZE_MINUTES,
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

    @staticmethod
    def _normalize_playback_metadata(
        *,
        alarm_media: str | None = None,
        alarm_volume: float | None = None,
        snooze_minutes: int | None = None,
        pre_actions: list[dict] | None = None,
        post_actions: list[dict] | None = None,
        failure_actions: list[dict] | None = None,
    ) -> dict[str, object]:
        """Normalize optional per-alarm playback/action overrides."""
        metadata: dict[str, object] = {}
        if alarm_media is not None:
            metadata[META_ALARM_MEDIA] = alarm_media.strip() or None
        if alarm_volume is not None:
            volume = float(alarm_volume)
            if not 0.0 <= volume <= 1.0:
                raise ValueError("Alarm volume must be between 0.0 and 1.0")
            metadata[META_ALARM_VOLUME] = volume
        if snooze_minutes is not None:
            minutes = int(snooze_minutes)
            if not 1 <= minutes <= 120:
                raise ValueError("Snooze duration must be between 1 and 120 minutes")
            metadata[META_SNOOZE_MINUTES] = minutes
        if pre_actions is not None:
            metadata[META_PRE_ACTIONS] = pre_actions
        if post_actions is not None:
            metadata[META_POST_ACTIONS] = post_actions
        if failure_actions is not None:
            metadata[META_FAILURE_ACTIONS] = failure_actions
        return metadata

    async def async_create(
        self,
        *,
        endpoint_id: str,
        time_value: str,
        recurrence: str,
        date_value: str | None = None,
        days: list[str] | tuple[str, ...] | None = None,
        name: str | None = None,
        alarm_media: str | None = None,
        alarm_volume: float | None = None,
        snooze_minutes: int | None = None,
        pre_actions: list[dict] | None = None,
        post_actions: list[dict] | None = None,
        failure_actions: list[dict] | None = None,
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
        playback_metadata = self._normalize_playback_metadata(
            alarm_media=alarm_media,
            alarm_volume=alarm_volume,
            snooze_minutes=snooze_minutes,
            pre_actions=pre_actions,
            post_actions=post_actions,
            failure_actions=failure_actions,
        )
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
                META_SKIP_NEXT: False,
                META_OVERRIDE: None,
                **playback_metadata,
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
        alarm_media: str | None = None,
        alarm_volume: float | None = None,
        snooze_minutes: int | None = None,
        pre_actions: list[dict] | None = None,
        post_actions: list[dict] | None = None,
        failure_actions: list[dict] | None = None,
    ) -> AlarmRecord:
        """Update alarm metadata and, when needed, its Scheduler schedule."""
        playback_metadata = self._normalize_playback_metadata(
            alarm_media=alarm_media,
            alarm_volume=alarm_volume,
            snooze_minutes=snooze_minutes,
            pre_actions=pre_actions,
            post_actions=post_actions,
            failure_actions=failure_actions,
        )

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
                record.metadata[META_SKIP_NEXT] = False
                record.metadata[META_OVERRIDE] = None

            if name is not None:
                normalized_name = name.strip()
                if not normalized_name:
                    raise ValueError("Alarm name cannot be empty")
                record.name = normalized_name

            record.metadata.update(playback_metadata)
            await self.registry.async_upsert(record)
            return record

    async def async_delete(self, alarm_id: str) -> None:
        """Delete an alarm and its Scheduler Component schedule."""
        async with self._lock:
            record = self._record(alarm_id)
            override = record.metadata.get(META_OVERRIDE)
            if isinstance(override, dict):
                override_entity = override.get("scheduler_entity_id")
                if override_entity and self.hass.states.get(str(override_entity)):
                    await self.scheduler.async_remove_schedule(str(override_entity))

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

    async def async_set_skip_next(self, alarm_id: str, skipped: bool = True) -> AlarmRecord:
        """Mark or clear the next normal Scheduler occurrence for skipping."""
        async with self._lock:
            record = self._record(alarm_id)
            record.metadata[META_SKIP_NEXT] = bool(skipped)
            await self.registry.async_upsert(record)
            return record

    async def async_consume_skip_next(self, alarm_id: str) -> bool:
        """Consume and clear a pending skip marker when the parent schedule fires."""
        async with self._lock:
            record = self._record(alarm_id)
            if not record.metadata.get(META_SKIP_NEXT):
                return False

            if record.metadata.get(META_RECURRENCE) == RECURRENCE_ONCE:
                await self.registry.async_remove(alarm_id)
            else:
                record.metadata[META_SKIP_NEXT] = False
                await self.registry.async_upsert(record)
            return True

    async def async_override_next(
        self,
        alarm_id: str,
        *,
        time_value: str,
        date_value: str | None = None,
    ) -> tuple[AlarmRecord, str | None, str | None]:
        """Temporarily move the next occurrence without changing recurrence."""
        record = self._record(alarm_id)
        trigger = self.trigger_for_record(record)
        if trigger is None:
            raise ValueError("Alarm has no enabled next occurrence to override")

        parsed_time = dt_util.parse_time(time_value)
        if parsed_time is None:
            raise ValueError("Invalid override time")

        target_date = date_value or dt_util.as_local(trigger).date().isoformat()
        parsed_date = dt_util.parse_date(target_date)
        if parsed_date is None:
            raise ValueError("Invalid override date")

        now = dt_util.now()
        target = datetime.combine(parsed_date, parsed_time, tzinfo=now.tzinfo)
        if target <= now:
            raise ValueError("Override occurrence must be scheduled in the future")

        if record.metadata.get(META_RECURRENCE) == RECURRENCE_ONCE:
            updated = await self.async_update(
                alarm_id=alarm_id,
                time_value=time_value,
                date_value=target_date,
            )
            return updated, None, None

        previous_override = record.metadata.get(META_OVERRIDE)
        if isinstance(previous_override, dict):
            old_entity = previous_override.get("scheduler_entity_id")
            if old_entity and self.hass.states.get(str(old_entity)):
                await self.scheduler.async_remove_schedule(str(old_entity))

        override_entity, occurrence_id = await self.scheduler.async_create_override_schedule(
            alarm_id=alarm_id,
            time=time_value,
            date=target_date,
        )

        async with self._lock:
            record = self._record(alarm_id)
            record.metadata[META_SKIP_NEXT] = True
            record.metadata[META_OVERRIDE] = {
                "scheduler_entity_id": override_entity,
                "occurrence_id": occurrence_id,
                "time": time_value,
                "date": target_date,
            }
            await self.registry.async_upsert(record)
            return record, override_entity, occurrence_id

    async def async_clear_override(self, alarm_id: str, occurrence_id: str | None) -> None:
        """Clear override metadata when its transient occurrence fires."""
        async with self._lock:
            record = self._record(alarm_id)
            override = record.metadata.get(META_OVERRIDE)
            if not isinstance(override, dict):
                return
            if occurrence_id and override.get("occurrence_id") != occurrence_id:
                return
            record.metadata[META_OVERRIDE] = None
            await self.registry.async_upsert(record)

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
            "skip_next": bool(record.metadata.get(META_SKIP_NEXT)),
            "override": record.metadata.get(META_OVERRIDE),
            "alarm_media": record.metadata.get(META_ALARM_MEDIA),
            "alarm_volume": record.metadata.get(META_ALARM_VOLUME),
            "snooze_minutes": record.metadata.get(META_SNOOZE_MINUTES),
        }

    def list_responses(self, endpoint_id: str | None = None) -> list[dict[str, object]]:
        """Return service-ready alarm data, optionally scoped to one endpoint."""
        records = (
            self.sorted_alarms_for_endpoint(endpoint_id) if endpoint_id else self.registry.all()
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
