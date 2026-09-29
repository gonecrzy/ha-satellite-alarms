"""Config flow for Satellite Alarms."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AREA_ID,
    CONF_ASSIST_SATELLITE,
    CONF_DEFAULT_ALARM_MEDIA,
    CONF_DEFAULT_SNOOZE_MINUTES,
    CONF_DEFAULT_VOLUME,
    CONF_MAX_RING_MINUTES,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    CONF_VOLUME_RAMP_ENABLED,
    CONF_VOLUME_RAMP_SECONDS,
    CONF_VOLUME_RAMP_START,
    DEFAULT_ALARM_MEDIA,
    DEFAULT_MAX_RING_MINUTES,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_VOLUME,
    DEFAULT_VOLUME_RAMP_ENABLED,
    DEFAULT_VOLUME_RAMP_SECONDS,
    DEFAULT_VOLUME_RAMP_START,
    DOMAIN,
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
        }
    )


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(
            CONF_DEFAULT_VOLUME, default=DEFAULT_VOLUME
        ): selector.NumberSelector(
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
    }
)


class SatelliteAlarmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Satellite Alarms."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a satellite alarm endpoint."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not SchedulerAdapter(self.hass).is_ready:
                errors["base"] = "scheduler_not_ready"
            elif self.hass.states.get(user_input[CONF_ASSIST_SATELLITE]) is None:
                errors[CONF_ASSIST_SATELLITE] = "entity_not_found"
            elif self.hass.states.get(user_input[CONF_MEDIA_PLAYER]) is None:
                errors[CONF_MEDIA_PLAYER] = "entity_not_found"
            else:
                await self.async_set_unique_id(user_input[CONF_ASSIST_SATELLITE])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_config_schema(),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SatelliteAlarmsOptionsFlow()


class SatelliteAlarmsOptionsFlow(OptionsFlow):
    """Manage endpoint alarm defaults."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Satellite Alarms options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
