"""Scheduler Component adapter for Satellite Alarms.

v0.1 validates the dependency and centralizes Scheduler-specific knowledge.
Schedule creation/edit/removal will be added in v0.2.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import SCHEDULER_DOMAIN

SERVICE_ADD = "add"
SERVICE_EDIT = "edit"
SERVICE_REMOVE = "remove"

_REQUIRED_SERVICES = (SERVICE_ADD, SERVICE_EDIT, SERVICE_REMOVE)


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
