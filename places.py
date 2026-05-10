"""Curated places loader + candidate filtering.

Slice 4a: filters data/places.json by mode, closing time, and (optional)
mood, then attaches `source` and a per-place `leave_home_time` to each
surviving entry. Google Places fallback is Slice 4b.
"""

import json
import logging
import os
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

PLACES_PATH = os.path.join(os.path.dirname(__file__), "data", "places.json")
MAX_CANDIDATES = 10

_places_cache: list[dict] | None = None


def load_curated_places() -> list[dict]:
    """Load and cache the curated places list."""
    global _places_cache
    if _places_cache is None:
        with open(PLACES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _places_cache = data["places"]
        logger.info("Loaded %d curated places from %s", len(_places_cache), PLACES_PATH)
    return _places_cache


# --- Helpers ---

def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _close_dt_for(arrival: datetime, typical_closing: str) -> datetime:
    """Build a closing datetime on arrival's calendar day.

    If the closing clock-time is at or before arrival, treat the place as
    closing the next calendar day (covers any "00:30" / "01:00" entries).
    """
    h, m = map(int, typical_closing.split(":"))
    close_dt = arrival.replace(hour=h, minute=m, second=0, microsecond=0)
    if close_dt <= arrival:
        close_dt += timedelta(days=1)
    return close_dt


def _passes_mode(place: dict, mode: str) -> bool:
    tags = place.get("mood_tags", [])
    if mode == "takeout":
        return "takeout" in tags
    if mode == "dine-in":
        return "sit-down" in tags
    return True


def _passes_closing(place: dict, arrival: datetime) -> bool:
    close_dt = _close_dt_for(arrival, place["typical_closing"])
    min_close = arrival + timedelta(minutes=config.MIN_MINUTES_OPEN_AFTER_ARRIVAL)
    return close_dt >= min_close


def _compute_leave_home(
    chloe_arrival_at_mrt: datetime,
    walk_minutes: int,
    mode: str,
    place_name: str,
) -> datetime:
    """Per-place Tobi leave-home time, per SPEC time math."""
    is_sun_plaza = "Sun Plaza" in place_name
    if mode == "dine-in" or is_sun_plaza:
        return chloe_arrival_at_mrt - timedelta(minutes=config.TOBI_WALK_TO_MRT_MIN)
    tobi_total = (2 * walk_minutes) + config.BUYING_TIME_MIN
    return max(
        chloe_arrival_at_mrt - timedelta(minutes=tobi_total),
        chloe_arrival_at_mrt - timedelta(minutes=config.MIN_TOBI_LEAD_TIME_MIN),
    )


# --- Public ---

def get_candidates(
    mood: str | None,
    arrival_time: datetime,
    mode: str,
    chloe_arrival_at_mrt: datetime,
) -> list[dict]:
    """Filter curated places and attach source + leave_home_time."""
    places = load_curated_places()
    n_loaded = len(places)

    after_mode = [p for p in places if _passes_mode(p, mode)]
    n_mode = len(after_mode)

    after_close = [p for p in after_mode if _passes_closing(p, arrival_time)]
    n_close = len(after_close)

    # Mood filter: only when mood is set AND not the takeout mode signal.
    if mood and mood != "takeout":
        mood_filtered = [p for p in after_close if mood in p.get("mood_tags", [])]
        if not mood_filtered:
            logger.warning(
                "Mood filter '%s' produced 0 candidates — skipping filter "
                "to avoid empty result", mood,
            )
            after_mood = after_close
        else:
            after_mood = mood_filtered
    else:
        after_mood = after_close
    n_mood = len(after_mood)

    logger.info(
        "Curated: %d places → %d after mode filter → %d after closing-time "
        "filter → %d after mood filter",
        n_loaded, n_mode, n_close, n_mood,
    )

    # Annotate
    candidates: list[dict] = []
    for place in after_mood[:MAX_CANDIDATES]:
        leave_dt = _compute_leave_home(
            chloe_arrival_at_mrt=chloe_arrival_at_mrt,
            walk_minutes=place["walk_minutes_from_mrt"],
            mode=mode,
            place_name=place["name"],
        )
        candidates.append({
            **place,
            "source": "curated",
            "leave_home_time": _fmt(leave_dt),
        })

    return candidates
