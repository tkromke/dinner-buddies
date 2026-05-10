"""Agent orchestration.

Slice 3: real time math.
- Compute Chloe's MRT arrival from her commute
- Decide dine-in vs takeout from arrival time + mood
- Per-place leave_home_time using the SPEC's rules
Picks are still hardcoded; real candidate filtering arrives in Slice 4
and Claude reasoning in Slice 5.
"""

import logging
from datetime import datetime, time as dtime, timedelta

import config
import maps

logger = logging.getLogger(__name__)


def _parse_clock(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _compute_leave_home(
    arrival: datetime, walk_minutes: int, mode: str, place_name: str,
) -> datetime:
    """Tobi's leave-home time for a specific candidate place."""
    is_sun_plaza = "Sun Plaza" in place_name

    if mode == "dine-in" or is_sun_plaza:
        return arrival - timedelta(minutes=config.TOBI_WALK_TO_MRT_MIN)

    tobi_total = (2 * walk_minutes) + config.BUYING_TIME_MIN
    return max(
        arrival - timedelta(minutes=tobi_total),
        arrival - timedelta(minutes=config.MIN_TOBI_LEAD_TIME_MIN),
    )


def _decide_mode(arrival: datetime, mood: str | None) -> str:
    if mood == "takeout":
        logger.info("Mode: takeout (explicit mood tag)")
        return "takeout"

    arrival_t = arrival.time()
    window_start = _parse_clock(config.DINE_IN_WINDOW_START)
    cutoff = _parse_clock(config.DINE_IN_CUTOFF_TIME)
    hours_end = _parse_clock(config.DINNER_HOURS_END)

    in_dine_in_window = window_start <= arrival_t <= cutoff
    in_takeout_window = cutoff < arrival_t <= hours_end

    logger.info(
        "Mode decision: arrival=%s, dinner_window=%s-%s, in_window=%s → %s",
        _fmt(arrival),
        config.DINE_IN_WINDOW_START,
        config.DINE_IN_CUTOFF_TIME,
        in_dine_in_window,
        "dine-in" if in_dine_in_window else "takeout",
    )

    if in_dine_in_window:
        return "dine-in"
    if in_takeout_window:
        logger.info(
            "Mode: takeout (auto-switched, arrival %s past %s cutoff)",
            _fmt(arrival), config.DINE_IN_CUTOFF_TIME,
        )
        return "takeout"

    logger.warning(
        "Arrival %s is outside normal dinner hours (%s-%s) — proceeding with takeout",
        _fmt(arrival), config.DINE_IN_WINDOW_START, config.DINNER_HOURS_END,
    )
    return "takeout"


def plan(trigger_user: str, minutes_until_leaving: int, mood: str | None) -> dict:
    """Return a dinner plan dict matching prompts/dinner_agent.md."""
    now = datetime.now()
    chloe_departure = now + timedelta(minutes=minutes_until_leaving)

    commute_min = maps.get_commute_minutes(
        origin=config.CHLOE_OFFICE_LOCATION,
        destination=config.SEMBAWANG_MRT_LOCATION,
        departure_time=chloe_departure,
    )

    arrival = now + timedelta(
        minutes=(
            minutes_until_leaving
            + commute_min
            + config.CHLOE_OFFICE_BUFFER_MIN
        )
    )
    logger.info(
        "Chloe leaving in %d → office commute %d min + %d buffer → arrival %s",
        minutes_until_leaving, commute_min, config.CHLOE_OFFICE_BUFFER_MIN, _fmt(arrival),
    )

    mode = _decide_mode(arrival, mood)

    # Hardcoded picks — real candidate filtering lands in Slice 4.
    top_name = "White Restaurant (Sun Plaza)"
    top_walk = 3
    top_leave = _compute_leave_home(arrival, top_walk, mode, top_name)
    logger.info("Tobi leave time for top pick (%s): %s", top_name, _fmt(top_leave))

    backup_name = "Saizeriya (Sun Plaza)"
    backup_walk = 3
    backup_leave = _compute_leave_home(arrival, backup_walk, mode, backup_name)
    logger.info("Tobi leave time for backup pick (%s): %s", backup_name, _fmt(backup_leave))

    return {
        "mode": mode,
        "meeting_point": "Sembawang MRT",
        "arrival_time": _fmt(arrival),
        "top_pick": {
            "place_id": "p002",
            "name": top_name,
            "leave_home_time": _fmt(top_leave),
            "for_user": None,
            "reasoning": (
                "Personal note flags this as the healthy pick, "
                "and closes at 21:30 so timing works."
            ),
        },
        "backup_pick": {
            "place_id": "p004",
            "name": backup_name,
            "leave_home_time": _fmt(backup_leave),
            "for_user": None,
            "reasoning": (
                "Use this if undecided; arrival before peak so no table wait."
            ),
        },
        "summary_line": (
            f"Meet at Sembawang MRT at {_fmt(arrival)} — "
            f"{top_name.split('(')[0].strip()}, "
            f"{backup_name.split('(')[0].strip()} as backup. "
            f"(Triggered by {trigger_user}, leaving in {minutes_until_leaving}m"
            + (f", mood={mood}" if mood else "")
            + ".)"
        ),
    }
