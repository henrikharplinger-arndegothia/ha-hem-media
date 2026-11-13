"""Sensors: search result, put.io storage, latest put.io files."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [HemMediaSearchSensor(coord, entry)]
    if coord.putio:
        ents += [PutioStorageSensor(coord, entry), PutioLatestSensor(coord, entry)]
    async_add_entities(ents)


class _Base(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, entry, key: str, name: str, icon: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": "Hem Media", "manufacturer": "Hem"}


class HemMediaSearchSensor(_Base):
    """State = last query; attributes tmdb (where to watch) and putio (my files)."""

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "search", "Sök", "mdi:movie-search")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self):
        return self.coordinator.search_result.get("query") or "–"

    @property
    def extra_state_attributes(self):
        r = self.coordinator.search_result
        return {"tmdb": r.get("tmdb", []), "putio": r.get("putio", []), "errors": r.get("errors", [])}


class PutioStorageSensor(_Base):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry, "putio_storage", "put.io lagring", "mdi:cloud-outline")

    @property
    def native_value(self):
        a = (self.coordinator.data or {}).get("account")
        return round(a["used"] / a["size"] * 100, 1) if a and a.get("size") else None

    @property
    def extra_state_attributes(self):
        a = (self.coordinator.data or {}).get("account") or {}
        return {"used_gb": round(a.get("used", 0) / 1e9, 1), "size_gb": round(a.get("size", 0) / 1e9, 1),
                "free_gb": round(a.get("avail", 0) / 1e9, 1)}


class PutioLatestSensor(_Base):
    def __init__(self, coord, entry) -> None:
        # Newest items in the put.io root folder (files added inside existing folders don't move them)
        super().__init__(coord, entry, "putio_latest", "put.io senaste", "mdi:folder-play-outline")

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("latest", []))

    @property
    def extra_state_attributes(self):
        return {"files": (self.coordinator.data or {}).get("latest", [])}
