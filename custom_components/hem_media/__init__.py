"""Hem Media: TMDB 'where can I watch it' search + my put.io files, for the wall dashboards.

Services:
  hem_media.search      {query}                  → sensor.hem_media_sok (attributes tmdb + putio)
  hem_media.clear                                → empties the search
  hem_media.play_putio  {file_id, entity_id}     → plays a put.io video (or the largest video in a
                                                    folder) on a media player, e.g. an Apple TV (AirPlay)
"""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, PutioClient, TmdbClient
from .const import (CONF_PUTIO_TOKEN, CONF_REGION, CONF_SERVICES, CONF_TMDB_TOKEN, DEFAULT_REGION,
                    DEFAULT_SERVICES, DOMAIN, QUERY_MAX, SEARCH_LIMIT, UPDATE_MINUTES)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


class HemMediaCoordinator(DataUpdateCoordinator):
    """Polls put.io (storage + latest files); holds the latest search result."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(minutes=UPDATE_MINUTES))
        session = async_get_clientsession(hass)
        data = {**entry.data, **entry.options}
        self.tmdb = TmdbClient(session, data[CONF_TMDB_TOKEN], data.get(CONF_REGION, DEFAULT_REGION),
                               data.get(CONF_SERVICES, DEFAULT_SERVICES))
        token = data.get(CONF_PUTIO_TOKEN) or ""
        self.putio = PutioClient(session, token) if token else None
        self.search_result: dict = {"query": "", "tmdb": [], "putio": [], "errors": []}
        self.search_gen = 0   # bumped by every search/clear; stale searches don't overwrite newer ones

    async def _async_update_data(self) -> dict:
        if not self.putio:
            return {"account": None, "latest": []}
        try:
            return {"account": await self.putio.account(), "latest": await self.putio.latest()}
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"put.io: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coord = HemMediaCoordinator(hass, entry)
    # put.io is optional: a failing first refresh leaves its sensors unavailable (and keeps retrying)
    # instead of blocking the whole integration, so TMDB search still works.
    await coord.async_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def _coord() -> HemMediaCoordinator:
        return next(iter(hass.data[DOMAIN].values()))

    async def handle_search(call: ServiceCall) -> None:
        c = _coord()
        q = call.data["query"].strip()[:QUERY_MAX]
        c.search_gen += 1
        gen = c.search_gen
        result = {"query": q, "tmdb": [], "putio": [], "errors": []}
        if len(q) > 1:
            try:
                result["tmdb"] = await c.tmdb.search(q, SEARCH_LIMIT)
            except AuthError:
                result["errors"].append("tmdb: nyckeln avvisades")
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("TMDB search failed: %s", err)
                result["errors"].append("tmdb: svarar inte")
            if c.putio:
                try:
                    result["putio"] = await c.putio.search(q)
                except AuthError:
                    result["errors"].append("put.io: token avvisades")
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("put.io search failed: %s", err)
                    result["errors"].append("put.io: svarar inte")
        if gen == c.search_gen:   # a newer search or clear started meanwhile → drop this result
            c.search_result = result
            c.async_update_listeners()

    async def handle_clear(call: ServiceCall) -> None:
        c = _coord()
        c.search_gen += 1
        c.search_result = {"query": "", "tmdb": [], "putio": [], "errors": []}
        c.async_update_listeners()

    async def handle_play_putio(call: ServiceCall) -> None:
        c = _coord()
        if not c.putio:
            raise HomeAssistantError("put.io is not configured")
        try:
            vid = await c.putio.playable_video_id(int(call.data["file_id"]))
            if vid is None:
                raise HomeAssistantError("Ingen video hittades i den put.io-filen/mappen")
            url = await c.putio.hls_url(vid)
        except AuthError as err:
            raise HomeAssistantError(f"put.io avvisade token: {err}") from err
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"put.io svarar inte: {err}") from err
        await hass.services.async_call(
            "media_player", "play_media",
            {"entity_id": call.data["entity_id"], "media_content_type": "video", "media_content_id": url},
            blocking=True,
        )

    async def handle_open_app(call: ServiceCall) -> None:
        # Samsung Tizen TVs/projectors: the samsungtv integration's play_media(app) can start an app in
        # the background only; the TV's local REST API (port 8001) brings it to the foreground.
        ent = er.async_get(hass).async_get(call.data["entity_id"])
        entry = hass.config_entries.async_get_entry(ent.config_entry_id) if ent and ent.config_entry_id else None
        if not entry or entry.domain != "samsungtv" or not entry.data.get("host"):
            raise HomeAssistantError("open_app needs a media_player from the Samsung TV integration")
        url = f"http://{entry.data['host']}:8001/api/v2/applications/{call.data['app_id']}"
        try:
            async with async_get_clientsession(hass).post(url, timeout=8) as resp:
                if resp.status >= 400:
                    raise HomeAssistantError(f"TV:n svarade {resp.status} (appen finns inte?)")
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"TV:n svarar inte: {err}") from err

    if not hass.services.has_service(DOMAIN, "search"):
        hass.services.async_register(DOMAIN, "search", handle_search, schema=vol.Schema({vol.Required("query"): vol.All(cv.string, vol.Length(max=QUERY_MAX))}))
        hass.services.async_register(DOMAIN, "clear", handle_clear)
        hass.services.async_register(DOMAIN, "play_putio", handle_play_putio, schema=vol.Schema({
            vol.Required("file_id"): vol.Coerce(int), vol.Required("entity_id"): cv.entity_id}))
        hass.services.async_register(DOMAIN, "open_app", handle_open_app, schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id, vol.Required("app_id"): vol.Match(r"^[0-9A-Za-z._]{3,40}$")}))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for s in ("search", "clear", "play_putio", "open_app"):
                hass.services.async_remove(DOMAIN, s)
    return ok
