"""Google Maps wrapper.

Slice 3: only get_commute_minutes() — the office-to-MRT transit time.
Falls back to a sensible default on any failure (no API key, API error,
no route found) so the agent always has a number to work with.
"""

import logging
from datetime import datetime

import googlemaps
from googlemaps.exceptions import ApiError, HTTPError, Timeout, TransportError

import config

logger = logging.getLogger(__name__)

DEFAULT_OFFICE_TO_MRT_MIN = 50

_client = None
if config.GOOGLE_MAPS_API_KEY:
    try:
        _client = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY)
    except Exception as e:
        logger.warning("googlemaps.Client init failed: %s", e)
else:
    logger.info("GOOGLE_MAPS_API_KEY missing — maps calls will use defaults")


def get_commute_minutes(
    origin: dict,
    destination: dict,
    departure_time: datetime,
) -> int:
    """Return transit commute minutes between two lat/lng points.

    Args:
        origin / destination: dicts with "lat" and "lng" keys.
        departure_time: when the commute starts (used for transit schedule).
    """
    if _client is None:
        logger.warning(
            "No Google Maps client — using default commute %d min",
            DEFAULT_OFFICE_TO_MRT_MIN,
        )
        return DEFAULT_OFFICE_TO_MRT_MIN

    try:
        result = _client.distance_matrix(
            origins=[(origin["lat"], origin["lng"])],
            destinations=[(destination["lat"], destination["lng"])],
            mode="transit",
            departure_time=departure_time,
        )
        element = result["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            logger.warning(
                "Distance Matrix returned status=%s — using default %d min",
                element.get("status"), DEFAULT_OFFICE_TO_MRT_MIN,
            )
            return DEFAULT_OFFICE_TO_MRT_MIN
        seconds = element["duration"]["value"]
        minutes = round(seconds / 60)
        logger.info(
            "Distance Matrix: origin=%s dest=%s → %d sec (%d min)",
            origin, destination, seconds, minutes,
        )
        return minutes
    except (ApiError, HTTPError, Timeout, TransportError, KeyError, IndexError) as e:
        logger.warning(
            "Distance Matrix call failed (%s) — using default %d min",
            e, DEFAULT_OFFICE_TO_MRT_MIN,
        )
        return DEFAULT_OFFICE_TO_MRT_MIN
