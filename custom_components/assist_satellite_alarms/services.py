"""Home Assistant service actions for Satellite Alarms."""

from __future__ import annotations

from datetime import date, time
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .alarm_manager import AlarmManager, AlarmNotFoundError, EndpointNotFoundError
from .const import (
    ATTR_ALARM_ID,
    ATTR_ALARM_MEDIA,
    ATTR_ALARM_VOLUME,
    ATTR_DATE,
    ATTR_DAYS,
    ATTR_ENDPOINT_ID,
    ATTR_FAILURE_ACTIONS,
    ATTR_MINUTES,
    ATTR_OCCURRENCE,
    ATTR_OCCURRENCE_ID,
    ATTR_POST_ACTIONS,
    ATTR_PRE_ACTIONS,
    ATTR_RECURRENCE,
    ATTR_SNOOZE_MINUTES,
    ATTR_TIME,
    CONF_NAME,
    DOMAIN,
    EVENT_ALARM_FAILED,
    EVENT_ALARM_OVERRIDE_CREATED,
    EVENT_ALARM_SKIPPED,
    EVENT_ALARM_SNOOZED,
    EVENT_ALARM_STOPPED,
    EVENT_ALARM_TRIGGERED,
    OCCURRENCE_OVERRIDE,
    OCCURRENCE_SCHEDULED,
    OCCURRENCES,
    RECURRENCE_ONCE,
    RECURRENCES,
    SERVICE_CREATE,
    SERVICE_DELETE,
    SERVICE_DISABLE,
    SERVICE_ENABLE,
    SERVICE_FIRE,
    SERVICE_LIST,
    SERVICE_OVERRIDE_NEXT,
    SERVICE_SKIP_NEXT,
    SERVICE_SNOOZE,
    SERVICE_STOP,
    SERVICE_UPDATE,
    WEEKDAYS,
)
from .playback import PlaybackError, PlaybackManager


def _validate_time(value: Any) -> str:
    """Validate and normalize an alarm clock time."""
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    parsed = dt_util.parse_time(str(value))
    if parsed is None:
        raise vol.Invalid("Invalid alarm time")
    return parsed.strftime("%H:%M:%S")


def _validate_date(value: Any) -> str:
    """Validate and normalize a calendar date."""
    if isinstance(value, date):
        return value.isoformat()
    parsed = dt_util.parse_date(str(value))
    if parsed is None:
        raise vol.Invalid("Invalid alarm date")
    return parsed.isoformat()


def _validate_active_selector(data: dict[str, Any]) -> dict[str, Any]:
    """Require exactly one active-alarm selector."""
    selectors = [key for key in (ATTR_ALARM_ID, ATTR_ENDPOINT_ID) if data.get(key)]
    if len(selectors) != 1:
        raise vol.Invalid("Provide exactly one of alarm_id or endpoint_id")
    return data


def _validate_action_list(value: Any) -> list[dict[str, Any]]:
    """Validate a persisted list of simple Home Assistant service actions."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise vol.Invalid("Actions must be a list")

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise vol.Invalid("Each action must be a mapping")
        action = item.get("action", item.get("service"))
        if not isinstance(action, str) or "." not in action:
            raise vol.Invalid("Each action requires action: domain.service")
        data = item.get("data", {})
        target = item.get("target")
        if not isinstance(data, dict):
            raise vol.Invalid("Action data must be a mapping")
        if target is not None and not isinstance(target, dict):
            raise vol.Invalid("Action target must be a mapping")
        normalized_item: dict[str, Any] = {"action": action, "data": dict(data)}
        if target is not None:
            normalized_item["target"] = dict(target)
        normalized.append(normalized_item)
    return normalized


_PLAYBACK_FIELDS = {
    vol.Optional(ATTR_ALARM_MEDIA): cv.string,
    vol.Optional(ATTR_ALARM_VOLUME): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    vol.Optional(ATTR_SNOOZE_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
    vol.Optional(ATTR_PRE_ACTIONS): _validate_action_list,
    vol.Optional(ATTR_POST_ACTIONS): _validate_action_list,
    vol.Optional(ATTR_FAILURE_ACTIONS): _validate_action_list,
}


CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENDPOINT_ID): cv.string,
        vol.Required(ATTR_TIME): _validate_time,
        vol.Optional(ATTR_RECURRENCE, default=RECURRENCE_ONCE): vol.In(RECURRENCES),
        vol.Optional(ATTR_DATE): _validate_date,
        vol.Optional(ATTR_DAYS): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
        vol.Optional(CONF_NAME): cv.string,
        **_PLAYBACK_FIELDS,
    }
)

UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ALARM_ID): cv.string,
        vol.Optional(ATTR_TIME): _validate_time,
        vol.Optional(ATTR_RECURRENCE): vol.In(RECURRENCES),
        vol.Optional(ATTR_DATE): _validate_date,
        vol.Optional(ATTR_DAYS): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
        vol.Optional(CONF_NAME): cv.string,
        **_PLAYBACK_FIELDS,
    }
)

ALARM_ID_SCHEMA = vol.Schema({vol.Required(ATTR_ALARM_ID): cv.string})

FIRE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ALARM_ID): cv.string,
        vol.Optional(ATTR_OCCURRENCE, default=OCCURRENCE_SCHEDULED): vol.In(OCCURRENCES),
        vol.Optional(ATTR_OCCURRENCE_ID): cv.string,
    }
)

OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ALARM_ID): cv.string,
        vol.Required(ATTR_TIME): _validate_time,
        vol.Optional(ATTR_DATE): _validate_date,
    }
)

LIST_SCHEMA = vol.Schema({vol.Optional(ATTR_ENDPOINT_ID): cv.string})

ACTIVE_ALARM_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_ALARM_ID): cv.string,
            vol.Optional(ATTR_ENDPOINT_ID): cv.string,
        }
    ),
    _validate_active_selector,
)

SNOOZE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_ALARM_ID): cv.string,
            vol.Optional(ATTR_ENDPOINT_ID): cv.string,
            vol.Optional(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
        }
    ),
    _validate_active_selector,
)


def _service_error(err: Exception) -> ServiceValidationError:
    """Convert manager/playback validation errors to Home Assistant service errors."""
    return ServiceValidationError(str(err))


async def async_register_services(
    hass: HomeAssistant,
    manager: AlarmManager,
    playback: PlaybackManager,
) -> None:
    """Register Satellite Alarms service actions once."""
    if hass.services.has_service(DOMAIN, SERVICE_CREATE):
        return

    async def async_create(call: ServiceCall) -> dict[str, object]:
        try:
            record = await manager.async_create(
                endpoint_id=call.data[ATTR_ENDPOINT_ID],
                time_value=call.data[ATTR_TIME],
                recurrence=call.data[ATTR_RECURRENCE],
                date_value=call.data.get(ATTR_DATE),
                days=call.data.get(ATTR_DAYS),
                name=call.data.get(CONF_NAME),
                alarm_media=call.data.get(ATTR_ALARM_MEDIA),
                alarm_volume=call.data.get(ATTR_ALARM_VOLUME),
                snooze_minutes=call.data.get(ATTR_SNOOZE_MINUTES),
                pre_actions=call.data.get(ATTR_PRE_ACTIONS),
                post_actions=call.data.get(ATTR_POST_ACTIONS),
                failure_actions=call.data.get(ATTR_FAILURE_ACTIONS),
            )
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        return manager.response(record)

    async def async_update(call: ServiceCall) -> dict[str, object]:
        try:
            record = await manager.async_update(
                alarm_id=call.data[ATTR_ALARM_ID],
                time_value=call.data.get(ATTR_TIME),
                recurrence=call.data.get(ATTR_RECURRENCE),
                date_value=call.data.get(ATTR_DATE),
                days=call.data.get(ATTR_DAYS),
                name=call.data.get(CONF_NAME),
                alarm_media=call.data.get(ATTR_ALARM_MEDIA),
                alarm_volume=call.data.get(ATTR_ALARM_VOLUME),
                snooze_minutes=call.data.get(ATTR_SNOOZE_MINUTES),
                pre_actions=call.data.get(ATTR_PRE_ACTIONS),
                post_actions=call.data.get(ATTR_POST_ACTIONS),
                failure_actions=call.data.get(ATTR_FAILURE_ACTIONS),
            )
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        return manager.response(record)

    async def async_delete(call: ServiceCall) -> dict[str, object]:
        alarm_id = call.data[ATTR_ALARM_ID]
        try:
            await manager.async_delete(alarm_id)
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        return {"alarm_id": alarm_id, "deleted": True}

    async def async_enable(call: ServiceCall) -> dict[str, object]:
        try:
            record = await manager.async_set_enabled(call.data[ATTR_ALARM_ID], True)
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        return {**manager.response(record), "enabled": True}

    async def async_disable(call: ServiceCall) -> dict[str, object]:
        try:
            record = await manager.async_set_enabled(call.data[ATTR_ALARM_ID], False)
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        return {**manager.response(record), "enabled": False}

    async def async_list(call: ServiceCall) -> dict[str, object]:
        """List alarms, optionally scoped to one configured endpoint."""
        try:
            alarms = manager.list_responses(call.data.get(ATTR_ENDPOINT_ID))
        except EndpointNotFoundError as err:
            raise _service_error(err) from err
        return {"alarms": alarms, "count": len(alarms)}

    async def async_skip_next(call: ServiceCall) -> dict[str, object]:
        """Skip the next normal occurrence of an alarm."""
        alarm_id = call.data[ATTR_ALARM_ID]
        try:
            record = await manager.async_set_skip_next(alarm_id)
        except (AlarmNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        return {**manager.response(record), "skip_next": True}

    async def async_override_next(call: ServiceCall) -> dict[str, object]:
        """Temporarily move the next occurrence while preserving recurrence."""
        alarm_id = call.data[ATTR_ALARM_ID]
        try:
            record, scheduler_entity_id, occurrence_id = await manager.async_override_next(
                alarm_id,
                time_value=call.data[ATTR_TIME],
                date_value=call.data.get(ATTR_DATE),
            )
        except (AlarmNotFoundError, ValueError) as err:
            raise _service_error(err) from err

        response = {
            **manager.response(record),
            "override_scheduler_entity_id": scheduler_entity_id,
            "override_occurrence_id": occurrence_id,
        }
        hass.bus.async_fire(EVENT_ALARM_OVERRIDE_CREATED, response)
        return response

    async def async_fire(call: ServiceCall) -> dict[str, object]:
        """Handle a Scheduler callback for a parent, snooze, or override occurrence."""
        alarm_id = call.data[ATTR_ALARM_ID]
        occurrence = call.data[ATTR_OCCURRENCE]
        occurrence_id = call.data.get(ATTR_OCCURRENCE_ID)

        try:
            event_data = manager.fire_event_data(alarm_id)

            if occurrence == OCCURRENCE_SCHEDULED and await manager.async_consume_skip_next(
                alarm_id
            ):
                result = {
                    **event_data,
                    "ringing": False,
                    "queued": False,
                    "skipped": True,
                    "occurrence": occurrence,
                }
                hass.bus.async_fire(EVENT_ALARM_SKIPPED, result)
                return result

            if occurrence == OCCURRENCE_OVERRIDE:
                await manager.async_clear_override(alarm_id, occurrence_id)

            _active, queued = await playback.async_start_or_queue(alarm_id)
        except PlaybackError as err:
            await playback.async_handle_failure(alarm_id, str(err))
            result = {
                **manager.fire_event_data(alarm_id),
                "ringing": False,
                "queued": False,
                "failed": True,
                "reason": str(err),
                "occurrence": occurrence,
            }
            hass.bus.async_fire(EVENT_ALARM_FAILED, result)
            return result
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err

        result = {
            **event_data,
            "ringing": not queued,
            "queued": queued,
            "skipped": False,
            "occurrence": occurrence,
        }
        hass.bus.async_fire(EVENT_ALARM_TRIGGERED, result)
        return result

    async def async_stop(call: ServiceCall) -> dict[str, object]:
        try:
            active = await playback.async_stop(
                alarm_id=call.data.get(ATTR_ALARM_ID),
                endpoint_id=call.data.get(ATTR_ENDPOINT_ID),
            )
        except PlaybackError as err:
            raise _service_error(err) from err

        response = {
            "alarm_id": active.alarm_id,
            "endpoint_id": active.endpoint_entry_id,
            "stopped": True,
        }
        hass.bus.async_fire(EVENT_ALARM_STOPPED, response)
        return response

    async def async_snooze(call: ServiceCall) -> dict[str, object]:
        try:
            active, minutes, snooze_entity_id = await playback.async_snooze(
                alarm_id=call.data.get(ATTR_ALARM_ID),
                endpoint_id=call.data.get(ATTR_ENDPOINT_ID),
                minutes=call.data.get(ATTR_MINUTES),
            )
        except PlaybackError as err:
            raise _service_error(err) from err

        response = {
            "alarm_id": active.alarm_id,
            "endpoint_id": active.endpoint_entry_id,
            "minutes": minutes,
            "scheduler_entity_id": snooze_entity_id,
            "snoozed": True,
        }
        hass.bus.async_fire(EVENT_ALARM_SNOOZED, response)
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE,
        async_create,
        schema=CREATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE,
        async_update,
        schema=UPDATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE,
        async_delete,
        schema=ALARM_ID_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ENABLE,
        async_enable,
        schema=ALARM_ID_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISABLE,
        async_disable,
        schema=ALARM_ID_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST,
        async_list,
        schema=LIST_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SKIP_NEXT,
        async_skip_next,
        schema=ALARM_ID_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_OVERRIDE_NEXT,
        async_override_next,
        schema=OVERRIDE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FIRE,
        async_fire,
        schema=FIRE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP,
        async_stop,
        schema=ACTIVE_ALARM_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SNOOZE,
        async_snooze,
        schema=SNOOZE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
