"""Constants for Hem Media."""
DOMAIN = "hem_media"

CONF_TMDB_TOKEN = "tmdb_token"      # TMDB v4 read access token (Bearer) or v3 API key
CONF_PUTIO_TOKEN = "putio_token"    # put.io OAuth token (optional)
CONF_REGION = "region"
CONF_SERVICES = "services"

DEFAULT_REGION = "SE"
# Provider names exactly as TMDB reports them for Sweden (case-insensitive equality, no substrings:
# "Max" must not match "Cinemax"). Since Apple's 2025 rename TMDB lists the subscription as "Apple TV";
# that is safe because only the flatrate (subscription) list is matched — the store is under rent/buy.
DEFAULT_SERVICES = ["Netflix", "HBO Max", "Max", "Disney Plus", "Apple TV", "Apple TV Plus", "Apple TV+"]
QUERY_MAX = 100

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
PUTIO_API = "https://api.put.io/v2"

UPDATE_MINUTES = 15
SEARCH_LIMIT = 6

BROWSE_HOURS = 6          # "Vet inte vad vi ska se": popular rows refresh interval
BROWSE_PER_ROW = 12
PUTIO_RECENT = 12         # newest videos found inside put.io folders
PUTIO_WALK_FOLDERS = 15   # newest top-level put.io items walked per refresh (API budget)

# TMDB provider name -> app name used by script.hem_tv (Apple TV source name / Samsung app key).
APP_FOR_SERVICE = {
    "netflix": "Netflix",
    "hbo max": "HBO Max",
    "max": "HBO Max",
    "disney plus": "Disney+",
    "apple tv": "TV",
    "apple tv plus": "TV",
    "apple tv+": "TV",
}
# Short label per app for the dashboard badges.
LABEL_FOR_APP = {"Netflix": "Netflix", "HBO Max": "HBO Max", "Disney+": "Disney+", "TV": "Apple TV+"}
