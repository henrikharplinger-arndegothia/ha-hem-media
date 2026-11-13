"""Config flow: TMDB token (required), put.io token (optional), region + services (options)."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, PutioClient, TmdbClient
from .const import (CONF_PUTIO_TOKEN, CONF_REGION, CONF_SERVICES, CONF_TMDB_TOKEN, DEFAULT_REGION,
                    DEFAULT_SERVICES, DOMAIN)


class HemMediaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                await TmdbClient(session, user_input[CONF_TMDB_TOKEN], DEFAULT_REGION, DEFAULT_SERVICES).validate()
            except AuthError:
                errors[CONF_TMDB_TOKEN] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            if user_input.get(CONF_PUTIO_TOKEN):
                try:
                    await PutioClient(session, user_input[CONF_PUTIO_TOKEN]).validate()
                except AuthError:
                    errors[CONF_PUTIO_TOKEN] = "invalid_auth"
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Hem Media", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_TMDB_TOKEN): str,
                vol.Optional(CONF_PUTIO_TOKEN, default=""): str,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return HemMediaOptionsFlow()


class HemMediaOptionsFlow(config_entries.OptionsFlowWithReload):
    """Saving options reloads the entry so region/services take effect immediately."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            user_input[CONF_REGION] = (user_input.get(CONF_REGION) or DEFAULT_REGION).strip().upper()[:2]
            user_input[CONF_SERVICES] = [s.strip() for s in user_input[CONF_SERVICES].split(",") if s.strip()]
            return self.async_create_entry(data=user_input)
        cur = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Optional(CONF_REGION, default=cur.get(CONF_REGION, DEFAULT_REGION)): str,
            vol.Optional(CONF_SERVICES, default=", ".join(cur.get(CONF_SERVICES, DEFAULT_SERVICES))): str,
        }))
