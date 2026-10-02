"""Tests for Satellite Alarms config flow."""

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.assist_satellite_alarms.const import (
    CONF_ADDITIONAL_ASSIST_SATELLITES,
    CONF_ADDITIONAL_MEDIA_PLAYERS,
    CONF_ADDITIONAL_PLAYBACK_TARGETS,
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
    SCHEDULER_DOMAIN,
)


async def _noop(call: ServiceCall) -> None:
    """No-op Scheduler service."""


def _prepare_entities(hass: HomeAssistant) -> None:
    """Create entities used by room endpoint config-flow tests."""
    for entity_id in (
        "assist_satellite.bedroom_left",
        "assist_satellite.bedroom_right",
        "media_player.bedroom_left",
        "media_player.bedroom_right",
    ):
        hass.states.async_set(entity_id, "idle")


async def test_config_flow_creates_room_with_additional_target(
    hass: HomeAssistant,
) -> None:
    """Config flow should persist explicit satellite/player pair mappings."""
    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, _noop)
    _prepare_entities(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Bedroom",
            CONF_ASSIST_SATELLITE: "assist_satellite.bedroom_left",
            CONF_MEDIA_PLAYER: "media_player.bedroom_left",
            CONF_ADDITIONAL_ASSIST_SATELLITES: ["assist_satellite.bedroom_right"],
            CONF_ADDITIONAL_MEDIA_PLAYERS: ["media_player.bedroom_right"],
        },
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ADDITIONAL_PLAYBACK_TARGETS] == [
        {
            CONF_ASSIST_SATELLITE: "assist_satellite.bedroom_right",
            CONF_MEDIA_PLAYER: "media_player.bedroom_right",
        }
    ]


async def test_config_flow_rejects_unpaired_additional_targets(
    hass: HomeAssistant,
) -> None:
    """Additional satellites and players must be supplied as complete pairs."""
    for service in ("add", "edit", "remove"):
        hass.services.async_register(SCHEDULER_DOMAIN, service, _noop)
    _prepare_entities(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Bedroom",
            CONF_ASSIST_SATELLITE: "assist_satellite.bedroom_left",
            CONF_MEDIA_PLAYER: "media_player.bedroom_left",
            CONF_ADDITIONAL_ASSIST_SATELLITES: ["assist_satellite.bedroom_right"],
        },
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "playback_target_count_mismatch"
