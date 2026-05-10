"""Agent orchestration.

Slice 2: returns a hardcoded plan matching the schema in
prompts/dinner_agent.md. Real time math arrives in Slice 3, real Claude
reasoning in Slice 5.
"""


def plan(trigger_user: str, minutes_until_leaving: int, mood: str | None) -> dict:
    """Return a dinner plan dict.

    Hardcoded for Slice 2. Schema matches prompts/dinner_agent.md.
    """
    return {
        "mode": "dine-in",
        "meeting_point": "Sembawang MRT",
        "arrival_time": "19:45",
        "top_pick": {
            "place_id": "p002",
            "name": "White Restaurant (Sun Plaza)",
            "leave_home_time": "19:40",
            "for_user": None,
            "reasoning": (
                "Personal note flags this as the healthy pick, "
                "and closes at 21:30 so timing works."
            ),
        },
        "backup_pick": {
            "place_id": "p004",
            "name": "Saizeriya (Sun Plaza)",
            "leave_home_time": "19:40",
            "for_user": None,
            "reasoning": (
                "Use this if undecided; arrival before peak "
                "so no table wait."
            ),
        },
        "summary_line": (
            f"Meet at Sembawang MRT at 19:45 — White Restaurant, "
            f"Saizeriya as backup. (Triggered by {trigger_user}, "
            f"leaving in {minutes_until_leaving}m"
            + (f", mood={mood}" if mood else "")
            + ".)"
        ),
    }
