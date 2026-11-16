"""Small async clients for TMDB (where can I watch it) and put.io (my files)."""
from __future__ import annotations

import logging
import re
from typing import Any

from aiohttp import ClientResponseError, ClientSession, ClientTimeout

from .const import APP_FOR_SERVICE, BROWSE_PER_ROW, PUTIO_API, TMDB_API, TMDB_IMG

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

    @staticmethod
    def app_for(name: str) -> str:
        return APP_FOR_SERVICE.get(name.strip().lower(), "")

    def _item(self, h: dict, kind: str, app: str = "") -> dict:
        date = h.get("release_date") or h.get("first_air_date") or ""
        return {
            "tmdb_id": h.get("id"),
            "kind": "film" if kind == "movie" else "serie",
            "title": h.get("title") or h.get("name") or "",
            "year": date[:4],
            "poster": f"{TMDB_IMG}{h['poster_path']}" if h.get("poster_path") else "",
            "app": app,
        }

    async def my_providers(self) -> list[tuple[int, str]]:
        """(TMDB provider id, app name) for my services in the region, one per app."""
        seen: dict[str, int] = {}
        for kind in ("movie", "tv"):
            data = await self._get(f"/watch/providers/{kind}", watch_region=self._region, language="sv-SE")
            for p in data.get("results", []):
                name = p.get("provider_name", "")
                app = self.app_for(name)
                if self._mine(name) and app and app not in seen:
                    seen[app] = p["provider_id"]
        return [(pid, app) for app, pid in seen.items()]

    async def _discover(self, kind: str, provider_id: int, app: str, n: int, **extra: Any) -> list[dict]:
        data = await self._get(
            f"/discover/{kind}", watch_region=self._region, with_watch_providers=provider_id,
            with_watch_monetization_types="flatrate", sort_by="popularity.desc", language="sv-SE",
            include_adult="false", **extra)
        return [self._item(h, kind, app) for h in data.get("results", []) if h.get("poster_path")][:n]

    @staticmethod
    def _mix(*lists: list[dict]) -> list[dict]:
        out, seen = [], set()
        for group in zip(*lists) if lists else []:
            for it in group:
                key = (it["kind"], it["tmdb_id"])
                if key not in seen:
                    seen.add(key)
                    out.append(it)
        for lst in lists:   # leftovers when lists differ in length
            for it in lst:
                key = (it["kind"], it["tmdb_id"])
                if key not in seen:
                    seen.add(key)
                    out.append(it)
        return out

    async def browse(self) -> list[dict]:
        """Rows for "we don't know what to watch": popular now per service, plus a kids row."""
        rows, kids = [], []
        for pid, app in await self.my_providers():
            try:
                films = await self._discover("movie", pid, app, BROWSE_PER_ROW // 2)
                series = await self._discover("tv", pid, app, BROWSE_PER_ROW // 2)
                rows.append({"key": app, "title": f"Populärt på {app if app != 'TV' else 'Apple TV+'}",
                             "items": self._mix(series, films)[:BROWSE_PER_ROW]})
                kids.append(self._mix(
                    await self._discover("tv", pid, app, 3, with_genres="10762"),
                    await self._discover("movie", pid, app, 3, with_genres="10751|16",
                                         **{"certification_country": "SE", "certification.lte": "7"})))
            except AuthError:
                raise
            except Exception as err:  # noqa: BLE001 — one service failing must not hide the others
                _LOGGER.warning("TMDB browse failed for %s: %s", app, err)
        if kids:
            rows.insert(0, {"key": "barn", "title": "För barnen", "items": self._mix(*kids)[:BROWSE_PER_ROW]})
        return rows

    async def match_file(self, name: str) -> tuple[dict, bool]:
        """Best TMDB guess (title, year, poster, kind, episode) for a put.io file name.
        Returns (guess, ok); ok=False on a request failure, so the caller doesn't cache it."""
        g = guess_title(name)
        full = g.pop("full_title", "")
        if not g["title"]:
            return g, True
        kind = "tv" if g["kind"] == "serie" else "movie"
        base = {"language": "sv-SE", "include_adult": "false"}
        tries = []
        if g["year"]:
            tries.append({"query": g["title"], "year" if kind == "movie" else "first_air_date_year": g["year"]})
            if full and full != g["title"]:
                tries.append({"query": full})      # "Blade Runner 2049": the number was part of the title
        tries.append({"query": g["title"]})
        res = []
        try:
            for q in tries:
                res = (await self._get(f"/search/{kind}", **base, **q)).get("results", [])
                if res:
                    break
        except AuthError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("TMDB match failed for %s: %s", name, err)
            return g, False
        if res:
            it = self._item(res[0], kind)
            g.update({"title": it["title"] or g["title"], "year": it["year"] or g["year"], "poster": it["poster"]})
        return g, True

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


_VIDEO_EXT = re.compile(r"\.(mkv|mp4|avi|m4v|mov|ts|wmv)$", re.I)
_EPISODE = re.compile(r"\b[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})(?:[-]?[Ee]\d{1,3})*\b")
_SEASON = re.compile(r"\b(?:[Ss](\d{1,2})|Season[ ._-]?(\d{1,2}))\b", re.I)
_YEAR = re.compile(r"(?<!\d)(19[3-9]\d|20[0-4]\d)(?!\d)")
_JUNK = re.compile(r"\b(2160p|1080p|720p|480p|4k|uhd|web[- .]?dl|webrip|web|bluray|brrip|bdrip|hdtv|hdr\d*|"
                   r"dv|x26[45]|h\.?26[45]|hevc|aac\d?|ac3|ddp?\d?|atmos|remux|proper|repack|extended|"
                   r"multi|nordic|swesub)\b", re.I)


def guess_title(name: str) -> dict:
    """'The.Wild.Robot.2024.1080p.WEB-DL.mkv' -> title 'The Wild Robot', year 2024, film.
    'Bluey.S03E12.720p.mkv' -> title 'Bluey', serie, episode 'S03E12'."""
    base = _VIDEO_EXT.sub("", name)
    base = re.sub(r"[\[\]()]", " ", base).replace(".", " ").replace("_", " ")
    out = {"title": "", "year": "", "kind": "film", "episode": "", "poster": ""}
    cut = len(base)
    m = _EPISODE.search(base)
    if m:
        out.update(kind="serie", episode=f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}")
        cut = min(cut, m.start())
    else:
        s = _SEASON.search(base)
        if s:
            out.update(kind="serie", episode=f"Säsong {int(s.group(1) or s.group(2))}")
            cut = min(cut, s.start())
    j = _JUNK.search(base)
    if j and j.start() > 0:
        cut = min(cut, j.start())
    out["full_title"] = re.sub(r"\s{2,}", " ", re.sub(r"[\s\-]+$", "", base[:cut]).strip(" -"))
    years = [y for y in _YEAR.finditer(base[:cut]) if y.start() > 0]   # last year wins: "Blade Runner 2049 2017"
    y = years[-1] if years else None
    if y:
        out["year"] = y.group(1)
        cut = min(cut, y.start())
    title = re.sub(r"[\s\-()\[\]]+$", "", base[:cut]).strip(" -")
    out["title"] = re.sub(r"\s{2,}", " ", title)
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

    async def _children(self, parent_id: int, max_pages: int = 20) -> list[dict]:
        """All children of a folder, following put.io's listing cursor (max_pages requests)."""
        data = await self._get("/files/list", parent_id=parent_id, per_page=200)
        files = list(data.get("files", []))
        cursor, pages = data.get("cursor"), 1
        while cursor and pages < max_pages:
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

    async def recent_videos(self, limit: int, walk_folders: int) -> list[dict]:
        """Newest videos anywhere in put.io (looks inside the newest top-level folders, 3 levels),
        so a folder like "chill.institute" shows what is actually in it."""
        top = (await self._get("/files/list", parent_id=0, sort_by="DATE_DESC", per_page=walk_folders)).get("files", [])
        videos = [f for f in top if f.get("file_type") == "VIDEO"]
        # Budget = folder listings (one page of 200 each), so a refresh makes at most ~41 requests.
        queue, depth, budget = [f["id"] for f in top if f.get("file_type") == "FOLDER"], 0, 40
        while queue and depth < 3 and budget > 0:
            nxt = []
            for pid in queue:
                if budget <= 0:
                    break
                budget -= 1
                for k in await self._children(pid, max_pages=1):
                    if k.get("file_type") == "VIDEO":
                        videos.append(k)
                    elif k.get("file_type") == "FOLDER":
                        nxt.append(k["id"])
            queue, depth = nxt, depth + 1
        # Skip samples/extras; newest first
        videos = [v for v in videos if (v.get("size") or 0) > 150e6 and "sample" not in v.get("name", "").lower()]
        videos.sort(key=lambda v: v.get("created_at") or "", reverse=True)
        return [self._file(v) for v in videos[:limit]]

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
