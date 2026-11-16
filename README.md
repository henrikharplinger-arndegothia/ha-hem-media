# Hem Media (TMDB + put.io) for Home Assistant

Small integration for a family wall dashboard:

- **Where can we watch it?** Search a film or series; see which of *your* services has it in Sweden
  (Netflix, HBO Max, Disney+, Apple TV+ …), plus rent/buy options. Data: TMDB watch providers
  (the same source JustWatch uses).
- **My put.io:** storage, latest files, search in your files, and play a put.io video (or the
  largest video in a folder) on a media player such as an Apple TV (AirPlay, HLS).

No download/indexer search is included.

## Install

1. Marketplace (HACS) → ⋮ → Custom repositories → Git repository:
   `https://github.com/henrikharplinger-arndegothia/ha-hem-media`, type **Integration** → Download.
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **Hem Media**:
   - **TMDB token**: themoviedb.org → account → Settings → API → *API Read Access Token* (v4) or the
     v3 API key. Free.
   - **put.io token** (optional): put.io → Settings → Apps → create an app / OAuth token.
4. Options (⚙ on the integration): region (default `SE`) and your services as TMDB names them
   (default `Netflix, HBO Max, Max, Disney Plus, Apple TV`).

## Entities

| Entity | State | Attributes |
|---|---|---|
| `sensor.hem_media_sok` | last query | `tmdb`: [{title, year, kind, poster, on_my_services, other_streaming, rent, buy, link}], `putio`: [{id, name, type, size_gb, image}] |
| `sensor.hem_media_put_io_lagring` | % used | used_gb, size_gb, free_gb |
| `sensor.hem_media_put_io_senaste` | count | files: [{id, name, type, size_gb, created, image}] |
| `sensor.hem_media_put_io_videor` | count | videos: newest videos inside put.io folders, with title/year/poster/episode guessed from the file name via TMDB |
| `sensor.hem_media_bladdra` | rows | rows: [{key, title, items}] — "För barnen" + "Populärt på <tjänst>" for each of your services (refresh every 6 h); items have `app` (the app to open) |

## Services

```yaml
action: hem_media.search
data: {query: Dune}

action: hem_media.play_putio
data: {file_id: 123456789, entity_id: media_player.downstairs}

action: hem_media.clear

action: hem_media.open_app        # Samsung Tizen TV/projector: app to the foreground
data: {entity_id: media_player.projektor, app_id: "3201907018807"}   # Netflix
```

Note: playback uses put.io's separate *download token* (stream/download only), never your OAuth
token; the URL is sent only from Home Assistant to your own media player on the LAN.
