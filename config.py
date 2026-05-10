"""Config: env vars, constants, and Telegram user ID -> name mapping."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Secrets / API keys ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# --- User identity ---
# Telegram numeric user IDs, loaded from .env. Cast to int for comparison
# against update.effective_user.id which is an int.
def _maybe_int(val: str) -> int | None:
    try:
        return int(val) if val else None
    except ValueError:
        return None

TOBIAS_TELEGRAM_USER_ID = _maybe_int(os.getenv("TOBIAS_TELEGRAM_USER_ID", ""))
CHLOE_TELEGRAM_USER_ID = _maybe_int(os.getenv("CHLOE_TELEGRAM_USER_ID", ""))

USER_ID_TO_NAME: dict[int, str] = {}
if TOBIAS_TELEGRAM_USER_ID is not None:
    USER_ID_TO_NAME[TOBIAS_TELEGRAM_USER_ID] = "tobi"
if CHLOE_TELEGRAM_USER_ID is not None:
    USER_ID_TO_NAME[CHLOE_TELEGRAM_USER_ID] = "chloe"


def name_for_user_id(user_id: int) -> str | None:
    """Map a Telegram user ID to "tobi" or "chloe". Returns None if unknown."""
    return USER_ID_TO_NAME.get(user_id)


# --- Locations (lat/lng dicts; used by maps.py) ---
HOME_LOCATION = {"lat": 1.447168422006055, "lng": 103.8204796119195}
SEMBAWANG_MRT_LOCATION = {"lat": 1.4490799407756672, "lng": 103.81989078803986}
CHLOE_OFFICE_LOCATION = {"lat": 1.2802463624652376, "lng": 103.84940459657376}

# --- Time math constants ---
TOBI_WALK_TO_MRT_MIN = 5
MIN_TOBI_LEAD_TIME_MIN = 5
BUYING_TIME_MIN = 10
MIN_MINUTES_OPEN_AFTER_ARRIVAL = 75
CHLOE_OFFICE_BUFFER_MIN = 10

# Dinner-window boundaries. Arrival inside [DINE_IN_WINDOW_START,
# DINE_IN_CUTOFF_TIME] → dine-in. Inside (DINE_IN_CUTOFF_TIME,
# DINNER_HOURS_END] → takeout (auto-switch). Outside → takeout +
# "outside normal dinner hours" warning.
DINE_IN_WINDOW_START = "17:00"
DINE_IN_CUTOFF_TIME = "19:30"
DINNER_HOURS_END = "23:00"

# --- Mood tags (from SPEC) ---
VALID_MOOD_TAGS = {
    "light", "heavy", "asian", "western", "japanese", "chinese",
    "malay", "indian", "soupy", "comfort", "healthy", "indulgent",
    "quick", "takeout", "late-night",
}

# --- Claude model ---
CLAUDE_MODEL = "claude-sonnet-4-5"
