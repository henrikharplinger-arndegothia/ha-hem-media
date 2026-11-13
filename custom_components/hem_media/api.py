"""Small async clients for TMDB (where can I watch it) and put.io (my files)."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientResponseError, ClientSession, ClientTimeout

from .const import PUTIO_API, TMDB_API, TMDB_IMG

_LOGGER = logging.getLogger(__name__)
TIMEOUT = ClientTimeout(total=15)


class AuthError(Exception):
    """The service rejected the token (401/403)."""


def _raise_for(r) -> None:
    if r.status in (401, 403):
        raise AuthError(f"{r.status} {r.reason}")
    r.raise_for_status()


class TmdbClient:
    """TMDB search + watch providers for one region."""

    def __init__(self, session: ClientSession, token: str, region: str, services: list[str]) -> None:
        self._session = session
        self._token = token.strip()
        self._region = (region or "SE").strip().upper()
        self._services = {s.strip().lower() for s in services if s.strip()}

    async def _get(self, path: str, **params: Any) -> dict:
        headers = {"accept": "application/json"}
        # v4 read access tokens are long JWTs; v3 API keys are 32 hex chars.
        if len(self._token) > 40:
            headers["Authorization"] = f"Bearer {self._token}"
        else:
            params["api_key"] = self._token
        async with self._session.get(f"{TMDB_API}{path}", params=params, headers=headers, timeout=TIMEOUT) as r:
            _raise_for(r)
            return await r.json()

    async def validate(self) -> None:
        await self._get("/configuration")

    def _mine(self, name: str) -> bool:
        return name.strip().lower() in self._services

    async def search(self, query: str, limit: int) -> list[dict]:
        data = await self._get("/search/multi", query=query, language="sv-SE", region=self._region, include_adult="false")
        hits = [h for h in data.get("results", []) if h.get("media_type") in ("movie", "tv")][:limit]
        out = []
        for h in hits:
            kind = h["media_type"]
            providers_ok = True
            try:
                prov = await self._get(f"/{kind}/{h['id']}/watch/providers")
                reg = prov.get("results", {}).get(self._region, {})
            except Exception as err:  # noqa: BLE001 — one failing title must not fail the search
                _LOGGER.debug("TMDB providers failed for %s: %s", h.get("id"), err)
                reg, providers_ok = {}, False
            flat = [p["provider_name"] for p in reg.get("flatrate", [])]
            date = h.get("release_date") or h.get("first_air_date") or ""
            out.append({
                "tmdb_id": h["id"],
                "kind": "film" if kind == "movie" else "serie",
                "title": h.get("title") or h.get("name") or "",
                "year": date[:4],
                "poster": f"{TMDB_IMG}{h['poster_path']}" if h.get("poster_path") else "",
                "on_my_services": [p for p in flat if self._mine(p)],
                "other_streaming": [p for p in flat if not self._mine(p)],
                "rent": [p["provider_name"] for p in reg.get("rent", [])],
                "buy": [p["provider_name"] for p in reg.get("buy", [])],
                "link": reg.get("link", ""),
                "providers_ok": providers_ok,
            })
        return out


class PutioClient:
    """put.io: account, latest files, search in my files, stream URLs."""

    def __init__(self, session: ClientSession, token: str) -> None:
        self._session = session
        self._token = token.strip()
        self._download_token: str | None = None

    def _headers(self) -> dict:
        return {"Authorization": f"token {self._token}", "accept": "application/json"}

    async def _get(self, path: str, **params: Any) -> dict:
        async with self._session.get(f"{PUTIO_API}{path}", params=params, headers=self._headers(), timeout=TIMEOUT) as r:
            _raise_for(r)
            return await r.json()

    async def _post(self, path: str, data: dict) -> dict:
        async with self._session.post(f"{PUTIO_API}{path}", data=data, headers=self._headers(), timeout=TIMEOUT) as r:
            _raise_for(r)
            return await r.json()

    async def _children(self, parent_id: int) -> list[dict]:
        """All children of a folder, following put.io's listing cursor (max 20 pages)."""
        data = await self._get("/files/list", parent_id=parent_id, per_page=200)
        files = list(data.get("files", []))
        cursor, pages = data.get("cursor"), 1
        while cursor and pages < 20:
            data = await self._post("/files/list/continue", {"cursor": cursor, "per_page": 200})
            files += data.get("files", [])
            cursor, pages = data.get("cursor"), pages + 1
        return files

    async def validate(self) -> None:
        await self._get("/account/info")

    async def account(self) -> dict:
        info = (await self._get("/account/info")).get("info", {})
        disk = info.get("disk", {})
        return {"used": disk.get("used", 0), "size": disk.get("size", 0), "avail": disk.get("avail", 0)}

    @staticmethod
    def _file(f: dict) -> dict:
        return {
            "id": f.get("id"),
            "name": f.get("name", ""),
            "type": "mapp" if f.get("file_type") == "FOLDER" else ("video" if f.get("file_type") == "VIDEO" else "fil"),
            "size_gb": round((f.get("size") or 0) / 1e9, 2),
            "created": f.get("created_at", ""),
            "image": f.get("screenshot") or f.get("icon") or "",
        }

    async def latest(self, limit: int = 12) -> list[dict]:
        data = await self._get("/files/list", parent_id=0, sort_by="DATE_DESC", per_page=limit)
        return [self._file(f) for f in data.get("files", [])][:limit]

    async def search(self, query: str, limit: int = 6) -> list[dict]:
        data = await self._get("/files/search", query=query, per_page=limit * 2)
        files = [f for f in data.get("files", []) if f.get("file_type") in ("VIDEO", "FOLDER")]
        return [self._file(f) for f in files][:limit]

    async def playable_video_id(self, file_id: int) -> int | None:
        """A video id for file_id: itself if it is a video, else the largest video in the folder
        including sub-folders (up to 3 levels deep)."""
        f = (await self._get(f"/files/{file_id}")).get("file", {})
        if f.get("file_type") == "VIDEO":
            return f["id"]
        if f.get("file_type") != "FOLDER":
            return None
        best: dict | None = None
        queue, depth = [file_id], 0
        while queue and depth < 3:
            nxt = []
            for pid in queue:
                for k in await self._children(pid):
                    if k.get("file_type") == "VIDEO" and (best is None or (k.get("size") or 0) > (best.get("size") or 0)):
                        best = k
                    elif k.get("file_type") == "FOLDER":
                        nxt.append(k["id"])
            queue, depth = nxt, depth + 1
        return best["id"] if best else None

    async def download_token(self) -> str:
        """put.io's separate download token: lets a player fetch files without the OAuth token."""
        if not self._download_token:
            info = (await self._get("/account/info", download_token=1)).get("info", {})
            self._download_token = info.get("download_token") or ""
            if not self._download_token:
                raise AuthError("put.io returned no download token")
        return self._download_token

    async def hls_url(self, video_id: int) -> str:
        """HLS stream for a player. Requests Swedish/English subtitle tracks where put.io has them
        (the player decides which to show). Uses the download token, never the OAuth token."""
        from urllib.parse import urlencode
        q = urlencode({"subtitle_languages": "swe,eng", "oauth_token": await self.download_token()})
        return f"{PUTIO_API}/files/{video_id}/hls/media.m3u8?{q}"
