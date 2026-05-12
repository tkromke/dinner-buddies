"""Agent orchestration.

Slice 5:
- Real time math (Slice 3)
- Mode decision with full dinner-window logic (Slice 3.1 fix)
- Curated candidate filtering (Slice 4a)
- Claude reasoning via claude_brain.decide() with shape validation
"""

import logging
from datetime import datetime, time as dtime, timedelta

import claude_brain
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


def _build_context(
    mode: str,
    trigger_user: str,
    now: datetime,
    arrival: datetime,
    mood: str | None,
    candidates: list[dict],
) -> dict:
    """Shape the context object exactly as prompts/dinner_agent.md expects."""
    return {
        "mode": mode,
        "trigger_user": trigger_user,
        "current_time": _fmt(now),
        "chloe_arrival_at_mrt": _fmt(arrival),
        "mood_tag": mood,
        "candidates": [
            {
                "place_id": c["id"],
                "name": c["name"],
                "cuisine": c["cuisine"],
                "mood_tags": c["mood_tags"],
                "walk_minutes_from_mrt": c["walk_minutes_from_mrt"],
                "typical_closing": c["typical_closing"],
                "price_range": c["price_range"],
                "personal_notes": c["personal_notes"],
                "last_eaten": c["last_eaten"],
                "source": c["source"],
                "leave_home_time": c["leave_home_time"],
            }
            for c in candidates
        ],
    }


def _validate_plan_shape(plan_dict) -> bool:
    if not isinstance(plan_dict, dict):
        return False
    required = {"mode", "meeting_point", "arrival_time",
                "top_pick", "backup_pick", "summary_line"}
    if not required.issubset(plan_dict.keys()):
        return False
    for key in ("top_pick", "backup_pick"):
        pick = plan_dict[key]
        if pick is None:
            continue
        if not isinstance(pick, dict):
            return False
        pick_required = {"place_id", "name", "leave_home_time", "reasoning"}
        if not pick_required.issubset(pick.keys()):
            return False
    return True


def plan(
    trigger_user: str,
    minutes_until_leaving: int,
    mood: str | None,
    simulated_now: datetime | None = None,
    force_mode: str | None = None,
    exclude_place_ids: list[str] | None = None,
    office_buffer_override: int | None = None,
) -> dict:
    """Return a dinner plan dict matching prompts/dinner_agent.md.

    Args:
        force_mode: if set ("dine-in" or "takeout"), bypass _decide_mode
            and use this. Powers the "Switch mode" button.
        exclude_place_ids: place ids to filter out before ranking. Powers
            the "Show alternatives" button.
        office_buffer_override: if set (including 0), use this in place
            of config.CHLOE_OFFICE_BUFFER_MIN. Powers the "Departure
            confirmed" button (tap → buffer=0, tightening arrival).

    `simulated_now` (if set) replaces datetime.now() for all time math.
    Maps/Claude APIs and log timestamps stay on real clock.
    """
    now = simulated_now if simulated_now is not None else datetime.now()
    if simulated_now is not None:
        logger.info(
            "agent.plan running with simulated_now=%s", _fmt(simulated_now),
        )
    chloe_departure = now + timedelta(minutes=minutes_until_leaving)

    commute_min = maps.get_commute_minutes(
        origin=config.CHLOE_OFFICE_LOCATION,
        destination=config.SEMBAWANG_MRT_LOCATION,
        departure_time=chloe_departure,
    )

    buffer_min = (
        office_buffer_override
        if office_buffer_override is not None
        else config.CHLOE_OFFICE_BUFFER_MIN
    )
    arrival = now + timedelta(
        minutes=(minutes_until_leaving + commute_min + buffer_min)
    )
    logger.info(
        "Chloe leaving in %d → office commute %d min + %d buffer%s → arrival %s",
        minutes_until_leaving, commute_min, buffer_min,
        " (override)" if office_buffer_override is not None else "",
        _fmt(arrival),
    )

    if force_mode is not None:
        mode = force_mode
        logger.info("Mode: %s (forced via force_mode override)", mode)
    else:
        mode = _decide_mode(arrival, mood)

    candidates = places.get_candidates(
        mood=mood,
        arrival_time=arrival,
        mode=mode,
        chloe_arrival_at_mrt=arrival,
        exclude_place_ids=exclude_place_ids,
    )

    context = _build_context(
        mode=mode,
        trigger_user=trigger_user,
        now=now,
        arrival=arrival,
        mood=mood,
        candidates=candidates,
    )
    logger.info("Sending %d candidates to Claude", len(candidates))

    plan_dict = claude_brain.decide(context)

    if not _validate_plan_shape(plan_dict):
        logger.warning(
            "Plan shape validation failed; falling back. Bad shape: %r",
            plan_dict,
        )
        plan_dict = claude_brain.fallback_plan(
            context, "shape validation failed"
        )

    if simulated_now is not None:
        plan_dict["_test_simulated_now"] = _fmt(simulated_now)

    return plan_dict
