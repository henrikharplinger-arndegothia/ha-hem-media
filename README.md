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

## Services

```yaml
action: hem_media.search
data: {query: Dune}

action: hem_media.play_putio
data: {file_id: 123456789, entity_id: media_player.downstairs}

action: hem_media.clear
```

Note: put.io's HLS URL carries the OAuth token as a query parameter; it is sent only from Home
Assistant to your own media player on the LAN.
