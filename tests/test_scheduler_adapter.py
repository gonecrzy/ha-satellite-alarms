"""Tests for the Scheduler Component adapter."""

import pytest

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.satellite_alarms.const import SCHEDULER_DOMAIN
from custom_components.satellite_alarms.scheduler_adapter import (
    SchedulerAdapter,
    SchedulerNotReadyError,
)


async def _noop_service(call: ServiceCall) -> None:
    """Handle a test service call."""


async def test_scheduler_adapter_requires_services(hass: HomeAssistant) -> None:
    """The adapter should reject an incomplete Scheduler service API."""
    adapter = SchedulerAdapter(hass)

    assert adapter.is_ready is False

    with pytest.raises(SchedulerNotReadyError):
        adapter.ensure_ready()

    hass.services.async_register(SCHEDULER_DOMAIN, "add", _noop_service)
    hass.services.async_register(SCHEDULER_DOMAIN, "edit", _noop_service)

    assert adapter.is_ready is False

    hass.services.async_register(SCHEDULER_DOMAIN, "remove", _noop_service)

    assert adapter.is_ready is True
    adapter.ensure_ready()
