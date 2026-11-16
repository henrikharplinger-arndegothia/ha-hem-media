"""Hem Media: TMDB 'where can I watch it' search + my put.io files, for the wall dashboards.

Services:
  hem_media.search      {query}                  → sensor.hem_media_sok (attributes tmdb + putio)
  (polled)                                       → sensor.hem_media_bladdra (popular rows per service + kids),
                                                    sensor.hem_media_put_io_videor (newest videos, with posters)
  hem_media.clear                                → empties the search
  hem_media.play_putio  {file_id, entity_id}     → plays a put.io video (or the largest video in a
                                                    folder) on a media player, e.g. an Apple TV (AirPlay)
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.util import dt as dt_util

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, PutioClient, TmdbClient
from .const import (BROWSE_HOURS, CONF_PUTIO_TOKEN, CONF_REGION, CONF_SERVICES, CONF_TMDB_TOKEN,
                    DEFAULT_REGION, DEFAULT_SERVICES, DOMAIN, PUTIO_RECENT, PUTIO_WALK_FOLDERS, QUERY_MAX,
                    SEARCH_LIMIT, UPDATE_MINUTES)

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
        self.browse: list[dict] = []
        self.browse_at = None
        self._match_cache: dict[str, dict] = {}   # put.io file name -> TMDB guess

    async def _refresh_browse(self) -> None:
        now = dt_util.utcnow()
        if self.browse_at and now - self.browse_at < timedelta(hours=BROWSE_HOURS) and self.browse:
            return
        try:
            self.browse = await self.tmdb.browse()
            self.browse_at = now
            self.async_update_listeners()   # publish even if the put.io part of this poll fails
        except Exception as err:  # noqa: BLE001 — keep the old rows; try again next poll
            _LOGGER.warning("TMDB browse failed: %s", err)

    async def _videos(self) -> list[dict]:
        vids = await self.putio.recent_videos(PUTIO_RECENT, PUTIO_WALK_FOLDERS)
        for v in vids:
            m = self._match_cache.get(v["name"])
            if m is None:
                m, ok = await self.tmdb.match_file(v["name"])
                if ok:   # don't cache a timeout/429: try again next poll
                    if len(self._match_cache) > 300:
                        self._match_cache.clear()
                    self._match_cache[v["name"]] = m
            v.update({"title": m["title"] or v["name"], "year": m["year"], "kind": m["kind"],
                      "episode": m["episode"], "poster": m["poster"]})
        return vids

    async def _async_update_data(self) -> dict:
        await self._refresh_browse()
        if not self.putio:
            return {"account": None, "latest": [], "videos": []}
        try:
            data = {"account": await self.putio.account(), "latest": await self.putio.latest()}
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"put.io: {err}") from err
        try:
            data["videos"] = await self._videos()
        except Exception as err:  # noqa: BLE001 — keep storage/latest even if the walk fails
            _LOGGER.warning("put.io video list failed: %s", err)
            data["videos"] = (self.data or {}).get("videos", [])
        return data


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
                for it in result["tmdb"]:   # app to open on the TV: first of my services that has it
                    it["app"] = next((c.tmdb.app_for(s) for s in it["on_my_services"] if c.tmdb.app_for(s)), "")
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
            vol.Required("entity_id"): cv.entity_id, vol.Required("app_id"): vol.All(vol.Coerce(str), vol.Match(r"^[0-9A-Za-z._]{3,40}$"))}))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for s in ("search", "clear", "play_putio", "open_app"):
                hass.services.async_remove(DOMAIN, s)
    return ok
