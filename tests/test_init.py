"""Tests for Satellite Alarms integration setup."""

from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms import async_setup, async_setup_entry
from custom_components.assist_satellite_alarms.const import (
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DATA_ALARM_MANAGER,
    DOMAIN,
    SCHEDULER_DOMAIN,
    SERVICE_CREATE,
)


async def _noop(call: ServiceCall) -> None:
    """No-op Scheduler service."""


async def test_setup_registers_services_and_loads_endpoint(hass: HomeAssistant) -> None:
    """Integration setup should initialize shared state and endpoint runtime data."""
    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, _noop)

    assert await async_setup(hass, {}) is True
    assert DATA_ALARM_MANAGER in hass.data[DOMAIN]
    assert hass.services.has_service(DOMAIN, SERVICE_CREATE)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        data={
            CONF_NAME: "Bedroom",
            CONF_ASSIST_SATELLITE: "assist_satellite.bedroom",
            CONF_MEDIA_PLAYER: "media_player.bedroom",
        },
        entry_id="bedroom-entry",
    )
    entry.add_to_hass(hass)

    assert await async_setup_entry(hass, entry) is True
    assert entry.runtime_data.name == "Bedroom"
    assert entry.runtime_data.media_player_entity_id == "media_player.bedroom"
