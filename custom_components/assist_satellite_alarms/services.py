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
    ATTR_DATE,
    ATTR_ENDPOINT_ID,
    ATTR_RECURRENCE,
    ATTR_TIME,
    CONF_NAME,
    DOMAIN,
    EVENT_ALARM_TRIGGERED,
    RECURRENCE_ONCE,
    RECURRENCES,
    SERVICE_CREATE,
    SERVICE_DELETE,
    SERVICE_DISABLE,
    SERVICE_ENABLE,
    SERVICE_FIRE,
    SERVICE_UPDATE,
)


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


CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENDPOINT_ID): cv.string,
        vol.Required(ATTR_TIME): _validate_time,
        vol.Optional(ATTR_RECURRENCE, default=RECURRENCE_ONCE): vol.In(RECURRENCES),
        vol.Optional(ATTR_DATE): _validate_date,
        vol.Optional(CONF_NAME): cv.string,
    }
)

UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ALARM_ID): cv.string,
        vol.Optional(ATTR_TIME): _validate_time,
        vol.Optional(ATTR_RECURRENCE): vol.In(RECURRENCES),
        vol.Optional(ATTR_DATE): _validate_date,
        vol.Optional(CONF_NAME): cv.string,
    }
)

ALARM_ID_SCHEMA = vol.Schema({vol.Required(ATTR_ALARM_ID): cv.string})


def _service_error(err: Exception) -> ServiceValidationError:
    """Convert manager validation errors to Home Assistant service errors."""
    return ServiceValidationError(str(err))


async def async_register_services(hass: HomeAssistant, manager: AlarmManager) -> None:
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
                name=call.data.get(CONF_NAME),
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
                name=call.data.get(CONF_NAME),
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

    async def async_fire(call: ServiceCall) -> dict[str, object]:
        try:
            event_data = manager.fire_event_data(call.data[ATTR_ALARM_ID])
        except (AlarmNotFoundError, EndpointNotFoundError, ValueError) as err:
            raise _service_error(err) from err
        hass.bus.async_fire(EVENT_ALARM_TRIGGERED, event_data)
        return event_data

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
        SERVICE_FIRE,
        async_fire,
        schema=ALARM_ID_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
