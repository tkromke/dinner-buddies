# Dinner Agent: Build Spec

## What we're building

A Telegram-based agent that helps a couple (Tobias and Chloe) decide where and when to eat dinner. They live in Sembawang, Singapore, and eat out every day. On Chloe's office days (3-4x a week) the timing logistics matter more, which is when this agent runs.

The agent takes a trigger from either user when one of them is leaving the office, calculates commute and meeting timing, fetches restaurant options from a curated list (with Google Places fallback), and returns a structured dinner plan: where to meet, what to eat (top + backup), and when each person should leave.

The goal is to remove the fragmented back-and-forth that happens between "leaving office" and "we meet at the MRT" so they arrive at the meeting point already aligned.

## Users

Two users: Tobias (works from home) and Chloe (hybrid, mostly office). Either can trigger the agent from Telegram.

## Trigger and inputs

The agent is triggered by a Telegram command:

`/dinner <minutes_until_leaving> [optional_mood_tag]`

Examples:
- `/dinner 15` (default mood)
- `/dinner 20 light`
- `/dinner 10 takeout`

Mood tags: `light`, `heavy`, `asian`, `western`, `japanese`, `chinese`, `malay`, `indian`, `soupy`, `comfort`, `healthy`, `indulgent`, `quick`, `takeout`, `late-night`.

The trigger person is identified by Telegram user ID and assumed to be the one leaving the office (typically Chloe).

## Mode: dine-in vs takeout

The agent runs in one of two modes, determined as follows:

1. If mood tag is `takeout`, mode is takeout.
2. If trigger time + minutes_until_leaving puts arrival past 19:30, mode defaults to takeout.
3. Otherwise, mode is dine-in.

Both users see the chosen mode in the response and can switch via inline button: "Switch to takeout" or "Switch to dine-in".

## What the agent returns

A single Telegram message sent to both users with:

- Meeting point (Sembawang MRT)
- Estimated arrival time at MRT
- Top restaurant pick: name, walk time, closes-at, why it fits, when Tobi should leave home
- Backup pick: same fields
- Mode-specific summary line ("Tobi grabs X, Chloe grabs Y, meet back home" for takeout complementary pair, etc.)

Followed by inline keyboard buttons:
- Confirm top pick
- Show alternatives
- Switch mode (dine-in ↔ takeout)

## Architecture

```
project/
├── SPEC.md
├── README.md
├── requirements.txt
├── .env.example
├── config.py                  # locations, user mapping, constants
├── bot.py                     # Telegram bot entry point
├── agent.py                   # main orchestration: plan() function
├── maps.py                    # Google Distance Matrix wrapper
├── places.py                  # hybrid: curated + Google fallback
├── claude_brain.py            # Anthropic API call + agent prompt loader
├── data/
│   └── places.json            # curated list of 11 places
└── prompts/
    └── dinner_agent.md        # the agent's reasoning prompt
```

## Data flow

1. User sends `/dinner 15 light` to Telegram bot
2. `bot.py` parses: user_id → "chloe", minutes=15, mood="light"
3. `bot.py` calls `agent.plan(trigger_user="chloe", minutes_until_leaving=15, mood="light")`
4. `agent.plan()`:
   a. Determines mode (dine-in vs takeout) using the rules above
   b. Computes Chloe's arrival time at Sembawang MRT
   c. Fetches candidates via `places.get_candidates(mood, arrival_time, mode)`
   d. For each candidate, computes Tobi's `leave_home_time` based on mode and walk distance
   e. Builds context object and calls `claude_brain.decide(context)` for the structured plan
   f. Returns the plan to `bot.py`
5. `bot.py` formats the plan into a Telegram message + inline keyboard, sends to both users

## External dependencies

APIs:
- Anthropic Claude API (model: claude-sonnet-4-5 or latest sonnet): agent reasoning
- Google Places API (Nearby Search + Place Details): restaurant candidates fallback
- Google Distance Matrix API: commute times
- Telegram Bot API: interface

Python libraries:
- `python-telegram-bot`: Telegram interface
- `anthropic`: Claude SDK
- `googlemaps`: Google Maps SDK (covers Places + Distance Matrix)
- `python-dotenv`: env var management
- `pydantic`: structured outputs from Claude

Environment variables (in `.env`):
- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `TOBIAS_TELEGRAM_USER_ID`
- `CHLOE_TELEGRAM_USER_ID`

## Curated places data

The primary source of restaurant candidates is `data/places.json`, a hand-curated list of places they actually eat at near Sembawang MRT and surroundings.

Schema for each entry:

- `id`: short stable id, e.g. "p001"
- `name`: full name including mall/location
- `cuisine`: short label, e.g. "japanese", "chinese", "malay"
- `mood_tags`: array from {asian, western, japanese, chinese, malay, indian, sit-down, takeout, quick, light, heavy, comfort, healthy, indulgent, soupy, late-night}
- `walk_minutes_from_mrt`: integer (also used as proxy for walk-from-home)
- `typical_closing`: 24h time string, e.g. "22:00"
- `price_range`: "$", "$$", "$$$"
- `personal_notes`: 1-2 sentences of personal context (when it works, when it doesn't)
- `last_eaten`: ISO date string or null. Used to discourage repeats.

`places.py` exposes:

- `get_candidates(mood: str | None, arrival_time: datetime, mode: str) -> list[Place]`
  - Filters curated list by mood tags, closing time, and mode (dine-in/takeout)
  - If fewer than 3 candidates remain, calls `_fallback_to_google(...)` to pull fresh options
  - Returns merged list, max 10 candidates, with a `source` field marking each as "curated" or "google"
  - Pre-computes `leave_home_time` per candidate based on mode and walk distance

The `source` field is passed to Claude so it knows which entries have personal context.

## Time math (deterministic, in code)

All time calculations happen in `agent.py` and `places.py` before calling Claude. Claude receives pre-computed times as facts, never computes them itself.

Constants (in config.py):
- `TOBI_WALK_TO_MRT_MIN = 5`
- `MIN_TOBI_LEAD_TIME_MIN = 5` (Tobi can never leave home less than 5 min before Chloe arrives at MRT)
- `BUYING_TIME_MIN = 10` (estimated time to buy takeout food)
- `MIN_MINUTES_OPEN_AFTER_ARRIVAL = 75`
- `CHLOE_OFFICE_BUFFER_MIN = 10` (time from leaving desk to actually being on the train)

Calculations:

**Chloe's arrival time:**
```
chloe_arrival_at_mrt = now + minutes_until_leaving + commute_office_to_mrt + CHLOE_OFFICE_BUFFER_MIN
```

**Dine-in mode (any restaurant), or takeout from Sun Plaza (where Tobi meets Chloe at MRT first):**
```
tobi_leave_home = chloe_arrival_at_mrt - TOBI_WALK_TO_MRT_MIN
```

**Takeout from a non-Sun-Plaza place (Tobi goes there alone, then to MRT):**
```
tobi_total_time = (2 * walk_minutes_from_mrt) + BUYING_TIME_MIN

tobi_leave_home = max(
    chloe_arrival_at_mrt - tobi_total_time,
    chloe_arrival_at_mrt - MIN_TOBI_LEAD_TIME_MIN  # 5-min floor
)
```

The `leave_home_time` is calculated PER place since walk distance varies, so top_pick and backup_pick may have different leave times.

## The agent's job

Claude (via `claude_brain.decide()`) is responsible for:
- Picking the top and backup options from the candidate list
- In takeout mode, deciding whether the pair should be complementary (different cuisines for Tobi and Chloe) or two ranked single options
- Justifying each pick in one short sentence grounded in personal_notes or constraints

Claude is NOT responsible for:
- Computing arrival times, leave-home times, or any clock math
- Filtering closed restaurants (pre-filtered in code)
- Filtering by mode (dine-in candidates excluded in takeout mode and vice versa, in code)
- Sending the message

## Out of scope (do not build)

- Calendar integration
- Real-time location sharing (Chloe's office is hardcoded)
- Restaurant booking
- User accounts, auth, persistence
- Web UI
- Persistent `last_eaten` updates (read-only for MVP, can be faked for demo)
- Variable meeting points beyond Sembawang MRT
- Cuisine preference learning
- Multi-couple support

## Build order (vertical slices)

**Slice 1: Hello, world (30 min)**
- Telegram bot that responds to `/dinner` with parsed args + "received" message
- `.env` loading, basic config, user ID mapping

**Slice 2: Hardcoded plan (45 min)**
- `agent.plan()` returns a hardcoded plan object
- `bot.py` formats it into a real Telegram message with inline buttons
- Message sent to both users

**Slice 3: Real time math (45 min)**
- `maps.py` calls Distance Matrix for Chloe's commute
- Mode determination logic (dine-in vs takeout)
- `leave_home_time` calculations per mode

**Slice 4a: Curated list loader (30 min)**
- `places.py` loads `data/places.json`
- Filter by mood, closing time, mode
- Pre-compute `leave_home_time` per candidate
- Returns max 10, marks each `source: "curated"`

**Slice 4b: Google Places fallback (45 min, optional)**
- If curated returns < 3 candidates, query Google Places
- Pre-filter for opening hours and rating ≥ 4.0
- Mark these `source: "google"`, no `personal_notes`
- Skip if time tight

**Slice 5: Claude reasoning (60-90 min)**
- `claude_brain.py` loads the agent prompt, builds context, calls Claude API
- Parse JSON response with fallback to plain-text on parsing failure
- Replace hardcoded plan in `agent.plan()` with the real one

**Slice 6: Polish (30-60 min)**
- Inline button handlers (Confirm / Alternatives / Switch mode)
- Better error messages
- README with setup steps

If time runs out: stop after Slice 5. Polish is optional.

## Failure logging

Print/log statements at every API boundary so demo video can show internals if useful:
- "Chloe leaving in 15 → arrival at MRT estimated 19:47"
- "Mode: dine-in (arrival before 19:30 cutoff)"
- "Curated list: 11 places → 7 after mood filter → 5 after closing-time filter"
- "Sending 5 candidates to Claude for ranking"
- "Claude returned: top=p002 (White Restaurant), backup=p004 (Saizeriya)"

## Testing strategy (manual)

Three real-world scenarios to test before recording:
1. Standard: `/dinner 15` at 18:30 on a weekday (dine-in mode)
2. Late: `/dinner 20` at 19:30 (auto-switches to takeout)
3. Mood: `/dinner 20 light` (filter visible in Claude's reasoning)

If all three return sensible plans, ship.
