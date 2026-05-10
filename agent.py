"""Agent orchestration.

Slice 4a:
- Real time math (Slice 3 carryover)
- Mode decision with full dinner-window logic (Slice 3.1 fix)
- Candidate filtering via places.get_candidates()
- Picks first two candidates as top/backup; Claude reasoning lands in Slice 5
"""

import logging
from datetime import datetime, time as dtime, timedelta

import config
import maps
import places

logger = logging.getLogger(__name__)


def _parse_clock(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


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


def _candidate_to_pick(c: dict) -> dict:
    """Shape a candidate dict into the top_pick/backup_pick schema.

    Reasoning is the place's personal_notes verbatim until Slice 5
    replaces this with Claude's output.
    """
    return {
        "place_id": c["id"],
        "name": c["name"],
        "leave_home_time": c["leave_home_time"],
        "for_user": None,
        "reasoning": c.get("personal_notes") or "From curated list.",
    }


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

    candidates = places.get_candidates(
        mood=mood,
        arrival_time=arrival,
        mode=mode,
        chloe_arrival_at_mrt=arrival,
    )

    base = {
        "mode": mode,
        "meeting_point": "Sembawang MRT",
        "arrival_time": _fmt(arrival),
    }

    if not candidates:
        logger.warning("No candidates survived filtering — empty plan")
        return {
            **base,
            "top_pick": None,
            "backup_pick": None,
            "summary_line": "No viable options for the constraints provided.",
        }

    top = _candidate_to_pick(candidates[0])
    logger.info("Top pick: %s (leave_home=%s)", top["name"], top["leave_home_time"])

    if len(candidates) < 2:
        logger.warning("Only one candidate available — backup_pick is None")
        return {
            **base,
            "top_pick": top,
            "backup_pick": None,
            "summary_line": (
                f"Only one viable option: {top['name'].split('(')[0].strip()}. "
                f"Meet at Sembawang MRT at {_fmt(arrival)}."
            ),
        }

    backup = _candidate_to_pick(candidates[1])
    logger.info("Backup pick: %s (leave_home=%s)", backup["name"], backup["leave_home_time"])

    return {
        **base,
        "top_pick": top,
        "backup_pick": backup,
        "summary_line": (
            f"Meet at Sembawang MRT at {_fmt(arrival)} — "
            f"{top['name'].split('(')[0].strip()}, "
            f"{backup['name'].split('(')[0].strip()} as backup. "
            f"(Triggered by {trigger_user}, leaving in {minutes_until_leaving}m"
            + (f", mood={mood}" if mood else "")
            + ".)"
        ),
    }
