"""Claude reasoning layer.

decide(context) -> plan dict. Loads prompts/dinner_agent.md as the
system prompt, sends the context as a single user message, parses the
JSON reply. Falls back to a deterministic first-two-candidates plan on
any failure (no API key, network/API error, invalid JSON).
"""

import json
import logging
import os
import time

from anthropic import Anthropic, APIError

import config

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "dinner_agent.md")
MAX_TOKENS = 1024

_client: Anthropic | None = None
_system_prompt: str | None = None


def _get_client() -> Anthropic | None:
    global _client
    if _client is None and config.ANTHROPIC_API_KEY:
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _load_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            _system_prompt = f.read()
        logger.info("Loaded system prompt: %d chars", len(_system_prompt))
    return _system_prompt


def _candidate_to_pick(c: dict, reasoning: str) -> dict:
    return {
        "place_id": c["place_id"],
        "name": c["name"],
        "leave_home_time": c["leave_home_time"],
        "for_user": None,
        "reasoning": reasoning,
    }


def _empty_plan(context: dict) -> dict:
    return {
        "mode": context["mode"],
        "meeting_point": "Sembawang MRT",
        "arrival_time": context["chloe_arrival_at_mrt"],
        "top_pick": None,
        "backup_pick": None,
        "summary_line": "No viable options for the constraints provided.",
    }


def fallback_plan(context: dict, reason: str) -> dict:
    """Deterministic first-two-candidates plan, used on any failure."""
    candidates = context.get("candidates", [])
    if not candidates:
        return _empty_plan(context)
    reasoning = f"Pre-computed fallback: {reason}."
    top = _candidate_to_pick(candidates[0], reasoning)
    backup = (
        _candidate_to_pick(candidates[1], reasoning)
        if len(candidates) > 1 else None
    )
    return {
        "mode": context["mode"],
        "meeting_point": "Sembawang MRT",
        "arrival_time": context["chloe_arrival_at_mrt"],
        "top_pick": top,
        "backup_pick": backup,
        "summary_line": f"Fallback plan ({reason}).",
    }


def _extract_json(text: str) -> dict:
    """Strip optional ``` code fences then json.loads."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def decide(context: dict) -> dict:
    """Pick top + backup using Claude. Always returns a plan dict."""
    if not context.get("candidates"):
        logger.info("No candidates — skipping Claude, returning empty plan")
        return _empty_plan(context)

    if not config.USE_CLAUDE:
        logger.info("USE_CLAUDE=False — skipping API, using fallback")
        return fallback_plan(context, "USE_CLAUDE disabled")

    client = _get_client()
    if client is None:
        logger.warning("ANTHROPIC_API_KEY missing — using fallback")
        return fallback_plan(context, "no Anthropic API key")

    system = _load_system_prompt()
    user_content = json.dumps(context, indent=2)

    raw_text = ""
    t0 = time.perf_counter()
    try:
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        elapsed = time.perf_counter() - t0
        raw_text = response.content[0].text if response.content else ""

        logger.info(
            "Claude API call: %.2fs, model=%s, tokens_in=%d, tokens_out=%d",
            elapsed, config.CLAUDE_MODEL,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        plan_dict = _extract_json(raw_text)

        top = plan_dict.get("top_pick") or {}
        backup = plan_dict.get("backup_pick") or {}
        logger.info(
            "Claude returned plan: top=%s, backup=%s, mode=%s, reasoning_top='%s'",
            top.get("place_id"), backup.get("place_id"),
            plan_dict.get("mode"),
            (top.get("reasoning") or "")[:80],
        )
        return plan_dict

    except APIError as e:
        elapsed = time.perf_counter() - t0
        logger.warning("Claude API error after %.2fs: %s", elapsed, e)
        return fallback_plan(context, "Claude response could not be parsed")
    except json.JSONDecodeError as e:
        logger.warning("Claude returned invalid JSON: %s", e)
        logger.warning("Raw Claude response: %r", raw_text)
        return fallback_plan(context, "Claude response could not be parsed")
    except Exception as e:
        logger.warning("Unexpected Claude error: %s", e)
        return fallback_plan(context, "Claude response could not be parsed")
