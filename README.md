# Dinner Buddies

> Demo video: https://www.loom.com/share/89efffb77c00453897d560fb03eb46b1
> Repo: https://github.com/tkromke/dinner-buddies

An AI agent that orchestrates dinner plans between two people. Built as
a take-home assignment for Stripe.

## What it does

Replaces fragmented dinner-coordination texting between Tobias and Chloe
on Chloe's office days. The agent takes a Telegram command
(`/dinner <minutes> [mood] [@HH:MM]`), calculates Chloe's commute and
arrival time at Sembawang MRT, picks 2 restaurants from a curated list
based on the time window and mood, computes Tobi's leave-home time, and
sends the plan to both users with inline buttons to iterate.

## Architecture

Two layers:

- **Deterministic (Python code)**: time math, mode determination (dine-in
  vs takeout), candidate filtering by closing time and mode, leave-home
  calculations per place.
- **Judgement (Claude API)**: picks 2 places from filtered candidates,
  decides if takeout should be a complementary pair (Tobi + Chloe
  different cuisines) or a single option for both, explains each pick
  in one sentence grounded in personal notes.

This separation is deliberate. Time arithmetic and filtering are
mechanical; restaurant choice is judgement. Keeping them apart means
the LLM doesn't compute math (which it can get wrong), and the deterministic
code doesn't pretend to have taste.

## Project structure

```
.
├── SPEC.md                # build spec, time math rules, data flow
├── README.md
├── requirements.txt
├── .env.example
├── config.py              # locations, user mapping, constants
├── bot.py                 # Telegram bot + message formatting
├── agent.py               # plan() orchestration
├── maps.py                # Google Distance Matrix wrapper
├── places.py              # curated list + filter pipeline
├── claude_brain.py        # Anthropic API call + JSON parsing
├── data/
│   └── places.json        # 11 curated places with personal notes
└── prompts/
    └── dinner_agent.md    # system prompt for the agent
```

## Setup

Requires Python 3.11+.

```bash
git clone <repo>
cd dinner-buddies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with real keys
python3 bot.py
```

### Environment variables

| Variable | Where to get |
|----------|--------------|
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `GOOGLE_MAPS_API_KEY` | console.cloud.google.com (Distance Matrix API enabled) |
| `TOBIAS_TELEGRAM_USER_ID` | @userinfobot on Telegram |
| `CHLOE_TELEGRAM_USER_ID` | @userinfobot on Telegram |

## Usage

Command syntax:

```
/dinner <minutes_until_leaving> [mood] [@HH:MM]
```

Examples:

- `/dinner 15` : Chloe leaving in 15 min, default mood, real time
- `/dinner 15 light` : with a mood preference
- `/dinner 15 takeout` : force takeout mode
- `/dinner 15 @18:00` : simulated current time (for testing)
- `/dinner 25 takeout @19:30` : full example

The bot responds with a plan and inline buttons:

- **✅ Chloe left the office**: re-plan assuming Chloe just left,
  removes the 10-min office buffer
- **Show alternatives**: re-plan with previously shown picks excluded
- **Switch mode**: re-plan in the opposite mode (dine-in to takeout or
  the reverse)

## Example output

Input:

```
/dinner 15 @18:00
```

Bot response:
![Telegram message][def]

```
Dinner Plan — dine-in
Meet at Sembawang MRT at 19:11

Top pick: Saizeriya (Sun Plaza)
   Leave home: 19:06
   Personal note flags this as the safe pick when undecided, closes at 22:00.

Backup: Nan Yang Dao (Sun Plaza)
   Leave home: 19:06
   Good when wanting to avoid Japanese or Western, closes at 22:00 with room.

Western comfort at Saizeriya or healthy Chinese at Nan Yang Dao, both close by.

🧪 Test mode: simulated time 18:00

[Chloe left the office]
[Show Alternatives]    [Switch Mode]    
```

Terminal logs during the call:

```
2026-05-13 08:41:16,819 - __main__ - INFO - TEST MODE: using simulated current_time=18:00 (real time=08:41)
2026-05-13 08:41:16,819 - __main__ - INFO - /dinner received: user=tobi (id=[USER_ID]) minutes=15 mood=None test_mode=True
2026-05-13 08:41:16,819 - agent - INFO - agent.plan running with simulated_now=18:00
2026-05-13 08:41:17,044 - maps - INFO - Distance Matrix: origin={'lat': 1.28, 'lng': 103.85} dest={'lat': 1.45, 'lng': 103.82} → 2747 sec (46 min)
2026-05-13 08:41:17,045 - agent - INFO - Chloe leaving in 15 → office commute 46 min + 10 buffer → arrival 19:11
2026-05-13 08:41:17,045 - agent - INFO - Mode decision: arrival=19:11, dinner_window=17:00-19:30, in_window=True → dine-in
2026-05-13 08:41:17,046 - places - INFO - Loaded 11 curated places from data/places.json
2026-05-13 08:41:17,047 - places - INFO - Curated: 11 places → 8 after mode filter → 8 after closing-time filter → 8 after mood filter
2026-05-13 08:41:17,047 - agent - INFO - Sending 8 candidates to Claude
2026-05-13 08:41:17,059 - claude_brain - INFO - Loaded system prompt: 5133 chars
2026-05-13 08:41:21,649 - httpx - INFO - HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
2026-05-13 08:41:21,707 - claude_brain - INFO - Claude API call: 4.65s, model=claude-sonnet-4-5, tokens_in=2967, tokens_out=250
2026-05-13 08:41:21,707 - claude_brain - INFO - Claude returned plan: top=p004, backup=p003, mode=dine-in, reasoning_top='Personal note flags this as the safe pick when undecided, closes at 22:00.'
2026-05-13 08:41:21,707 - __main__ - INFO - agent.plan returned mode=dine-in top=p004 backup=p003
2026-05-13 08:41:22,259 - httpx - INFO - HTTP Request: POST https://api.telegram.org/bot[REDACTED_TG_TOKEN]/sendMessage "HTTP/1.1 200 OK"
```

## Mode determination

The agent runs in dine-in or takeout mode:

1. If the user includes `takeout` as a mood tag, takeout is forced.
2. If the calculated arrival time falls outside the 17:00-19:30 window,
   the agent auto-switches to takeout.
3. Otherwise, dine-in.

## Process

I worked in two phases:

1. **Planning (Claude.ai chat).** Defined the workflow, scoped the build,
   designed the agent prompt, structured the curated data layer. Output:
   SPEC.md, prompts/dinner_agent.md, data/places.json.

2. **Building (Claude Code).** Implemented the core agent in 5 vertical
   slices, then added test-mode time simulation and three interactive buttons
   (Switch Mode, Show Alternatives, Chloe left the office) for the demo.
   Captured three real failures during the build: a None-handling crash
   when the agent returned only one viable candidate, a late-night cutoff
   bug from naive time string comparison, and a dependency conflict between
   anthropic and httpx versions. Each was diagnosed and fixed during the
   relevant slice.

Build time: ~4 hours of focused implementation. Planning: ~90 minutes
upfront.

## What's intentionally out of scope

- **Calendar integration**: mode is inferred from time, not Chloe's
  calendar
- **Real-time location tracking**: commute is computed from a hardcoded
  office coordinate. Both users share location via Apple Find My in
  real life, but integrating that is overkill for the demo
- **Restaurant booking**
- **Persistent state across sessions**: `last_eaten` dates are read-only,
  faked for demo if relevant
- **Google Places API for restaurant data**: the curated list with
  personal notes was deliberately chosen over Google ratings. Public
  ratings don't capture what matters here ("works when Chloe has a
  9pm call", "doesn't work when very hungry"). Distance Matrix is
  used for commute timing only.
- **User accounts, web UI, multi-couple support**

## What I'd add with more time

- **Variable meeting points.** Distance Matrix already handles commute
  calculations, so adding mid-route meeting points (when Tobi has an
  appointment in town and they eat near the appointment) is mostly
  config: a few more candidate locations, a command argument to
  specify where, and the same time math runs. The curated list would
  need entries for each new area.
- **Calendar integration** to detect Chloe's actual end-of-day without
  her having to trigger the command, and to detect Tobi's town
  appointments to auto-suggest a town meeting point.
- **Persistent `last_eaten` tracking** so the agent genuinely avoids
  repeats across days, not just within a session.

## Limitations

- Tobi's leave time has a 5-minute floor before Chloe's arrival. For
  takeout from very close places, Tobi leaves at the floor rather than
  later, even when his actual walk-plus-buying time would let him leave
  later.
- Mood filter falls back to "no filter" if zero candidates match (logged),
  which is a deliberate "show something rather than nothing" choice.
- All times are local (SGT). No timezone handling.
- In takeout mode, Tobi currently meets Chloe at the MRT before heading 
  to the takeout place. The original design had Tobi pick up food first 
  for non-Sun-Plaza takeout, then meet at MRT. Current behavior is a 
  simpler unified flow that works but loses the time optimization.


[def]: demo_assets/dinner_plan_dine_in.png