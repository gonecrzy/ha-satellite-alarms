"""Config flow for Satellite Alarms."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ADDITIONAL_ASSIST_SATELLITES,
    CONF_ADDITIONAL_MEDIA_PLAYERS,
    CONF_ADDITIONAL_PLAYBACK_TARGETS,
    CONF_AREA_ID,
    CONF_ASSIST_SATELLITE,
    CONF_DEFAULT_ALARM_MEDIA,
    CONF_DEFAULT_ALARM_MESSAGE,
    CONF_DEFAULT_SNOOZE_MINUTES,
    CONF_DEFAULT_VOLUME,
    CONF_MAX_RING_MINUTES,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    CONF_PLAYBACK_MODE,
    CONF_VOLUME_RAMP_ENABLED,
    CONF_VOLUME_RAMP_SECONDS,
    CONF_VOLUME_RAMP_START,
    DEFAULT_ALARM_MEDIA,
    DEFAULT_ALARM_MESSAGE,
    DEFAULT_MAX_RING_MINUTES,
    DEFAULT_PLAYBACK_MODE,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_VOLUME,
    DEFAULT_VOLUME_RAMP_ENABLED,
    DEFAULT_VOLUME_RAMP_SECONDS,
    DEFAULT_VOLUME_RAMP_START,
    DOMAIN,
    PLAYBACK_MODE_ALL,
    PLAYBACK_MODE_FALLBACK,
    PLAYBACK_MODE_PRIMARY,
)
from .scheduler_adapter import SchedulerAdapter


def _config_schema() -> vol.Schema:
    """Build the endpoint configuration schema."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Optional(CONF_AREA_ID): selector.AreaSelector(),
            vol.Required(CONF_ASSIST_SATELLITE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="assist_satellite")
            ),
            vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            vol.Optional(CONF_ADDITIONAL_ASSIST_SATELLITES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="assist_satellite", multiple=True)
            ),
            vol.Optional(CONF_ADDITIONAL_MEDIA_PLAYERS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
        }
    )


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PLAYBACK_MODE, default=DEFAULT_PLAYBACK_MODE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"label": "Primary only", "value": PLAYBACK_MODE_PRIMARY},
                    {"label": "All room speakers", "value": PLAYBACK_MODE_ALL},
                    {"label": "Primary with fallback", "value": PLAYBACK_MODE_FALLBACK},
                ]
            )
        ),
        vol.Optional(CONF_DEFAULT_VOLUME, default=DEFAULT_VOLUME): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0,
                max=1.0,
                step=0.05,
                mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_DEFAULT_SNOOZE_MINUTES, default=DEFAULT_SNOOZE_MINUTES
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=60,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_VOLUME_RAMP_ENABLED, default=DEFAULT_VOLUME_RAMP_ENABLED
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_VOLUME_RAMP_START, default=DEFAULT_VOLUME_RAMP_START
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0,
                max=1.0,
                step=0.05,
                mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_VOLUME_RAMP_SECONDS, default=DEFAULT_VOLUME_RAMP_SECONDS
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=600,
                step=5,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_MAX_RING_MINUTES, default=DEFAULT_MAX_RING_MINUTES
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=120,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_DEFAULT_ALARM_MEDIA, default=DEFAULT_ALARM_MEDIA
        ): selector.TextSelector(),
        vol.Optional(
            CONF_DEFAULT_ALARM_MESSAGE, default=DEFAULT_ALARM_MESSAGE
        ): selector.TextSelector(),
    }
)


class SatelliteAlarmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Satellite Alarms."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure a satellite alarm endpoint."""
        errors: dict[str, str] = {}

        if user_input is not None:
            primary_satellite = user_input[CONF_ASSIST_SATELLITE]
            primary_player = user_input[CONF_MEDIA_PLAYER]
            additional_satellites = list(
                user_input.get(CONF_ADDITIONAL_ASSIST_SATELLITES, [])
            )
            additional_players = list(
                user_input.get(CONF_ADDITIONAL_MEDIA_PLAYERS, [])
            )
            all_satellites = [primary_satellite, *additional_satellites]
            all_players = [primary_player, *additional_players]

            if not SchedulerAdapter(self.hass).is_ready:
                errors["base"] = "scheduler_not_ready"
            elif len(additional_satellites) != len(additional_players):
                errors["base"] = "playback_target_count_mismatch"
            elif len(set(all_satellites)) != len(all_satellites):
                errors["base"] = "duplicate_satellite"
            elif len(set(all_players)) != len(all_players):
                errors["base"] = "duplicate_media_player"
            elif any(self.hass.states.get(entity_id) is None for entity_id in all_satellites):
                errors["base"] = "entity_not_found"
            elif any(self.hass.states.get(entity_id) is None for entity_id in all_players):
                errors["base"] = "entity_not_found"
            elif self._satellites_already_configured(set(all_satellites)):
                errors["base"] = "satellite_already_in_room"
            else:
                await self.async_set_unique_id(primary_satellite)
                self._abort_if_unique_id_configured()

                data = dict(user_input)
                data.pop(CONF_ADDITIONAL_ASSIST_SATELLITES, None)
                data.pop(CONF_ADDITIONAL_MEDIA_PLAYERS, None)
                data[CONF_ADDITIONAL_PLAYBACK_TARGETS] = [
                    {
                        CONF_ASSIST_SATELLITE: satellite,
                        CONF_MEDIA_PLAYER: player,
                    }
                    for satellite, player in zip(
                        additional_satellites, additional_players, strict=True
                    )
                ]

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_config_schema(),
            errors=errors,
        )

    def _satellites_already_configured(self, satellites: set[str]) -> bool:
        """Return whether any selected satellite already belongs to another endpoint."""
        for entry in self._async_current_entries():
            configured = {entry.data.get(CONF_ASSIST_SATELLITE)}
            for item in entry.data.get(CONF_ADDITIONAL_PLAYBACK_TARGETS, []):
                if isinstance(item, dict):
                    configured.add(item.get(CONF_ASSIST_SATELLITE))
            configured.discard(None)
            if satellites.intersection(configured):
                return True
        return False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SatelliteAlarmsOptionsFlow()


class SatelliteAlarmsOptionsFlow(OptionsFlow):
    """Manage endpoint alarm defaults."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage Satellite Alarms options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
