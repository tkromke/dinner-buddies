"""Telegram bot entry point.

Slice 2: parse /dinner, build a (hardcoded) plan via agent.plan(),
format it as Markdown, send to both users with inline keyboard.
Real time math + Claude reasoning come in later slices.
"""

import logging
import re
import sys
import uuid
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import agent
import config

# In-memory request-state store. Keyed by short request id; embedded in
# button callback_data so each tap can look up the original plan params.
# Cleared on bot restart — fine for the demo.
_request_state: dict[str, dict] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Formatting ---------------------------------------------------------

def _md_escape(text: str) -> str:
    """Escape characters reserved by legacy Telegram Markdown.

    Legacy Markdown reserves: * _ ` [
    Restaurant names with parentheses, dots, dashes are fine.
    """
    for ch in ("\\", "*", "_", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def format_plan(plan_dict: dict) -> str:
    top = plan_dict.get("top_pick")
    backup = plan_dict.get("backup_pick")
    summary = plan_dict.get("summary_line", "")
    test_sim = plan_dict.get("_test_simulated_now")
    departure_confirmed = plan_dict.get("_departure_confirmed", False)

    # Empty plan: just the summary as the whole body.
    if top is None and backup is None:
        lines = [f"_{_md_escape(summary)}_"]
        if test_sim:
            lines += ["", f"🧪 Test mode: simulated time {_md_escape(test_sim)}"]
        return "\n".join(lines)

    mode = plan_dict.get("mode", "")
    meeting_point = plan_dict.get("meeting_point", "")
    arrival_time = plan_dict.get("arrival_time", "")

    lines: list[str] = []
    if departure_confirmed:
        lines += [
            "🟢 Departure confirmed — plan updated for actual departure time",
            "",
        ]
    lines += [
        f"*Dinner Plan* — _{_md_escape(mode)}_",
        "",
        f"Meet at *{_md_escape(meeting_point)}* at *{_md_escape(arrival_time)}*",
        "",
    ]

    if top:
        lines += [
            f"*Top pick:* {_md_escape(top['name'])}",
            f"  _Leave home: {_md_escape(top['leave_home_time'])}_",
            f"  {_md_escape(top['reasoning'])}",
            "",
        ]
    if backup:
        lines += [
            f"*Backup:* {_md_escape(backup['name'])}",
            f"  _Leave home: {_md_escape(backup['leave_home_time'])}_",
            f"  {_md_escape(backup['reasoning'])}",
            "",
        ]
    elif top:
        lines += ["_No backup option viable for this timing._", ""]

    lines.append(f"_{_md_escape(summary)}_")

    if test_sim:
        lines += ["", f"🧪 Test mode: simulated time {_md_escape(test_sim)}"]

    return "\n".join(lines)


# --- Argument parsing ---------------------------------------------------

TEST_TIME_PATTERN = re.compile(r"^@(\d{1,2}):(\d{2})$")


def _extract_simulated_time(
    args: list[str],
) -> tuple[list[str], datetime | None, str | None]:
    """Pull any @HH:MM token out of args.

    Returns (remaining_args, simulated_datetime_or_None, parse_error_or_None).
    A parse_error means the user typed something starting with `@` that
    wasn't a valid HH:MM, and we should reject the command.
    """
    remaining: list[str] = []
    simulated: datetime | None = None
    parse_error: str | None = None

    for token in args:
        if not token.startswith("@"):
            remaining.append(token)
            continue
        m = TEST_TIME_PATTERN.match(token)
        if not m:
            parse_error = token
            continue
        hour = int(m.group(1))
        minute = int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            parse_error = token
            continue
        simulated = datetime.now().replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    return remaining, simulated, parse_error


def plan_keyboard(
    plan_dict: dict, request_id: str, show_confirm_departure: bool = True,
) -> InlineKeyboardMarkup:
    """Build the inline keyboard. Each callback_data carries the request id
    so the handler can look up the stored plan params.

    `show_confirm_departure` is False once the user has already tapped
    "Chloe left the office" — the button disappears for subsequent
    re-renders within the same request.
    """
    top = plan_dict.get("top_pick")
    backup = plan_dict.get("backup_pick")

    if top is None and backup is None:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Try different settings",
                callback_data=f"try:{request_id}",
            )],
        ])

    rows: list[list[InlineKeyboardButton]] = []
    if show_confirm_departure:
        rows.append([InlineKeyboardButton(
            "✅ Chloe left the office",
            callback_data=f"confirm_dep:{request_id}",
        )])
    rows.append([
        InlineKeyboardButton("Show alternatives", callback_data=f"alts:{request_id}"),
        InlineKeyboardButton("Switch mode", callback_data=f"switch:{request_id}"),
    ])
    return InlineKeyboardMarkup(rows)


def _ids_from_plan(plan_dict: dict) -> list[str]:
    """Extract the place_ids of the picks present in the plan."""
    ids = []
    top = plan_dict.get("top_pick")
    backup = plan_dict.get("backup_pick")
    if top:
        ids.append(top["place_id"])
    if backup:
        ids.append(backup["place_id"])
    return ids


# --- Handlers -----------------------------------------------------------

async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Dinner Buddies bot online. Send /dinner <minutes> [mood] to plan dinner."
    )


async def dinner(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    name = config.name_for_user_id(user.id)
    if name is None:
        logger.warning("Unknown Telegram user_id=%s tried /dinner", user.id)
        await update.message.reply_text(
            f"Sorry, I don't know who you are (user_id={user.id}). "
            "Add your ID to .env as TOBIAS_TELEGRAM_USER_ID or CHLOE_TELEGRAM_USER_ID."
        )
        return

    raw_args = ctx.args or []
    args, simulated_now, parse_error = _extract_simulated_time(raw_args)

    if parse_error:
        await update.message.reply_text(
            f"Bad test-time token '{parse_error}'. "
            "Use @HH:MM, e.g. @18:30."
        )
        return

    if len(args) < 1:
        await update.message.reply_text(
            "Usage: /dinner <minutes_until_leaving> [mood] [@HH:MM]\n"
            "Example: /dinner 15 light\n"
            "Example: /dinner 15 @18:30 (test mode)"
        )
        return

    try:
        minutes = int(args[0])
    except ValueError:
        await update.message.reply_text(
            f"Couldn't parse '{args[0]}' as minutes. Try: /dinner 15"
        )
        return

    mood: str | None = None
    if len(args) >= 2:
        candidate = args[1].lower()
        if candidate in config.VALID_MOOD_TAGS:
            mood = candidate
        else:
            await update.message.reply_text(
                f"Unknown mood '{candidate}'. Valid moods: "
                f"{', '.join(sorted(config.VALID_MOOD_TAGS))}"
            )
            return

    if simulated_now is not None:
        logger.info(
            "TEST MODE: using simulated current_time=%s (real time=%s)",
            simulated_now.strftime("%H:%M"),
            datetime.now().strftime("%H:%M"),
        )

    logger.info(
        "/dinner received: user=%s (id=%s) minutes=%s mood=%s test_mode=%s",
        name, user.id, minutes, mood, simulated_now is not None,
    )

    plan_dict = agent.plan(
        trigger_user=name,
        minutes_until_leaving=minutes,
        mood=mood,
        simulated_now=simulated_now,
    )
    logger.info(
        "agent.plan returned mode=%s top=%s backup=%s",
        plan_dict.get("mode"),
        (plan_dict.get("top_pick") or {}).get("place_id"),
        (plan_dict.get("backup_pick") or {}).get("place_id"),
    )

    request_id = uuid.uuid4().hex[:16]
    _request_state[request_id] = {
        "trigger_user": name,
        "minutes": minutes,
        "mood": mood,
        "simulated_now": simulated_now,
        "current_mode": plan_dict.get("mode"),
        "already_shown_ids": _ids_from_plan(plan_dict),
        "office_buffer_override": None,
    }
    logger.info("Stored request state id=%s state=%s",
                request_id, _request_state[request_id])

    message_text = format_plan(plan_dict)
    keyboard = plan_keyboard(plan_dict, request_id, show_confirm_departure=True)

    # Send to BOTH mapped users (trigger user + partner).
    recipients = list(config.USER_ID_TO_NAME.keys())
    if not recipients:
        # Fallback: at least reply to the trigger user.
        recipients = [user.id]

    for chat_id in recipients:
        try:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
            logger.info("Plan sent to chat_id=%s", chat_id)
        except TelegramError as e:
            # Most likely cause: the partner has never /start'd the bot.
            logger.warning("Failed to send plan to chat_id=%s: %s", chat_id, e)
            if chat_id == user.id:
                # If we couldn't even reach the trigger user, fall back to reply.
                await update.message.reply_text(
                    "Plan ready but message send failed. Check logs."
                )


async def _rerender(
    query, plan_dict: dict, request_id: str, show_confirm_departure: bool,
) -> None:
    """Edit the message in place with the new plan + keyboard.

    Telegram raises BadRequest("Message is not modified") when the new
    text equals the current text — we swallow that since it just means
    the action was a no-op.
    """
    try:
        await query.edit_message_text(
            text=format_plan(plan_dict),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=plan_keyboard(
                plan_dict, request_id,
                show_confirm_departure=show_confirm_departure,
            ),
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            logger.info("Edit was a no-op (same text)")
        else:
            raise


def _show_confirm_for(state: dict) -> bool:
    """Hide the confirm button once a departure has already been confirmed."""
    return state.get("office_buffer_override") is None


async def _handle_switch_mode(query, state: dict, request_id: str) -> None:
    current_mode = state["current_mode"]
    new_mode = "takeout" if current_mode == "dine-in" else "dine-in"
    logger.info(
        "Switch mode: %s → %s (request_id=%s)", current_mode, new_mode, request_id,
    )

    new_plan = agent.plan(
        trigger_user=state["trigger_user"],
        minutes_until_leaving=state["minutes"],
        mood=state["mood"],
        simulated_now=state["simulated_now"],
        force_mode=new_mode,
        exclude_place_ids=None,  # fresh exclusion list on mode switch
        office_buffer_override=state.get("office_buffer_override"),
    )

    if not new_plan.get("top_pick") and not new_plan.get("backup_pick"):
        await query.answer(
            text=f"Switching to {new_mode} produced no viable options.",
            show_alert=True,
        )
        return

    state["current_mode"] = new_plan.get("mode", new_mode)
    state["already_shown_ids"] = _ids_from_plan(new_plan)
    logger.info("State updated after switch: %s", state)

    await query.answer()
    await _rerender(query, new_plan, request_id, show_confirm_departure=_show_confirm_for(state))


async def _handle_show_alternatives(query, state: dict, request_id: str) -> None:
    logger.info(
        "Show alternatives: excluding %s (request_id=%s)",
        state["already_shown_ids"], request_id,
    )

    new_plan = agent.plan(
        trigger_user=state["trigger_user"],
        minutes_until_leaving=state["minutes"],
        mood=state["mood"],
        simulated_now=state["simulated_now"],
        force_mode=state["current_mode"],
        exclude_place_ids=list(state["already_shown_ids"]),
        office_buffer_override=state.get("office_buffer_override"),
    )

    if not new_plan.get("top_pick") and not new_plan.get("backup_pick"):
        await query.answer(text="No more alternatives.", show_alert=True)
        return

    new_ids = _ids_from_plan(new_plan)
    state["already_shown_ids"].extend(
        pid for pid in new_ids if pid not in state["already_shown_ids"]
    )
    logger.info("State updated after alts: %s", state)

    await query.answer()
    await _rerender(query, new_plan, request_id, show_confirm_departure=_show_confirm_for(state))


async def _handle_confirm_departure(query, state: dict, request_id: str) -> None:
    logger.info(
        "Departure confirmed by %s: buffer override=0, re-planning... (request_id=%s)",
        state["trigger_user"], request_id,
    )

    state["office_buffer_override"] = 0

    new_plan = agent.plan(
        trigger_user=state["trigger_user"],
        minutes_until_leaving=state["minutes"],
        mood=state["mood"],
        simulated_now=state["simulated_now"],
        force_mode=state["current_mode"],
        exclude_place_ids=None,  # let Claude re-rank with tightened times
        office_buffer_override=0,
    )

    if not new_plan.get("top_pick") and not new_plan.get("backup_pick"):
        await query.answer(
            text="Tightened timing produced no viable options.",
            show_alert=True,
        )
        return

    new_ids = _ids_from_plan(new_plan)
    state["already_shown_ids"].extend(
        pid for pid in new_ids if pid not in state["already_shown_ids"]
    )
    new_plan["_departure_confirmed"] = True
    logger.info("State updated after confirm: %s", state)

    await query.answer(text="Departure confirmed")
    await _rerender(query, new_plan, request_id, show_confirm_departure=False)


async def on_button(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    data = query.data or ""
    logger.info(
        "Button pressed: %s by user_id=%s",
        data, query.from_user.id if query.from_user else "?",
    )

    if ":" not in data:
        await query.answer()
        if query.message:
            await query.message.reply_text("Unrecognized button.")
        return

    action, request_id = data.split(":", 1)
    state = _request_state.get(request_id)
    if state is None:
        await query.answer(
            text="Plan expired (bot restarted?). Send /dinner again.",
            show_alert=True,
        )
        return

    if action == "try":
        await query.answer()
        if query.message:
            await query.message.reply_text(
                "Try /dinner again with different minutes, mood, or @HH:MM."
            )
        return

    if action == "confirm_dep":
        await _handle_confirm_departure(query, state, request_id)
        return

    if action == "switch":
        await _handle_switch_mode(query, state, request_id)
        return

    if action == "alts":
        await _handle_show_alternatives(query, state, request_id)
        return

    await query.answer(text=f"Unknown action: {action}")


# --- Entry point --------------------------------------------------------

def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing. Copy .env.example to .env and fill it in.")
        sys.exit(1)
    if not config.USER_ID_TO_NAME:
        print("WARNING: No user IDs mapped. Set TOBIAS_TELEGRAM_USER_ID and "
              "CHLOE_TELEGRAM_USER_ID in .env.")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dinner", dinner))
    app.add_handler(CallbackQueryHandler(on_button))

    logger.info("Bot starting. Mapped users: %s", config.USER_ID_TO_NAME)
    app.run_polling()


if __name__ == "__main__":
    main()
