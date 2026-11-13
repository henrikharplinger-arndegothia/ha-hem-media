"""Constants for Hem Media."""
DOMAIN = "hem_media"

CONF_TMDB_TOKEN = "tmdb_token"      # TMDB v4 read access token (Bearer) or v3 API key
CONF_PUTIO_TOKEN = "putio_token"    # put.io OAuth token (optional)
CONF_REGION = "region"
CONF_SERVICES = "services"

DEFAULT_REGION = "SE"
# Provider names exactly as TMDB reports them for Sweden (case-insensitive equality, no substrings:
# "Max" must not match "Cinemax", and "Apple TV" is Apple's rental store, not the Apple TV+ service).
DEFAULT_SERVICES = ["Netflix", "HBO Max", "Max", "Disney Plus", "Apple TV Plus", "Apple TV+"]
QUERY_MAX = 100

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
PUTIO_API = "https://api.put.io/v2"

UPDATE_MINUTES = 15
SEARCH_LIMIT = 6
