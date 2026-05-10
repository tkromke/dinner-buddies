"""Telegram bot entry point.

Slice 2: parse /dinner, build a (hardcoded) plan via agent.plan(),
format it as Markdown, send to both users with inline keyboard.
Real time math + Claude reasoning come in later slices.
"""

import logging
import sys

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import agent
import config

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
    mode = plan_dict["mode"]
    meeting_point = plan_dict["meeting_point"]
    arrival_time = plan_dict["arrival_time"]
    top = plan_dict["top_pick"]
    backup = plan_dict["backup_pick"]
    summary = plan_dict["summary_line"]

    lines = [
        f"*Dinner Plan* — _{_md_escape(mode)}_",
        "",
        f"Meet at *{_md_escape(meeting_point)}* at *{_md_escape(arrival_time)}*",
        "",
        f"*Top pick:* {_md_escape(top['name'])}",
        f"  _Leave home: {_md_escape(top['leave_home_time'])}_",
        f"  {_md_escape(top['reasoning'])}",
        "",
        f"*Backup:* {_md_escape(backup['name'])}",
        f"  _Leave home: {_md_escape(backup['leave_home_time'])}_",
        f"  {_md_escape(backup['reasoning'])}",
        "",
        f"_{_md_escape(summary)}_",
    ]
    return "\n".join(lines)


def plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirm top", callback_data="confirm_top"),
            InlineKeyboardButton("Show alternatives", callback_data="show_alts"),
        ],
        [InlineKeyboardButton("Switch mode", callback_data="switch_mode")],
    ])


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

    args = ctx.args or []
    if len(args) < 1:
        await update.message.reply_text(
            "Usage: /dinner <minutes_until_leaving> [mood]\n"
            "Example: /dinner 15 light"
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

    logger.info(
        "/dinner received: user=%s (id=%s) minutes=%s mood=%s",
        name, user.id, minutes, mood,
    )

    plan_dict = agent.plan(
        trigger_user=name,
        minutes_until_leaving=minutes,
        mood=mood,
    )
    logger.info("agent.plan returned mode=%s top=%s backup=%s",
                plan_dict["mode"],
                plan_dict["top_pick"]["place_id"],
                plan_dict["backup_pick"]["place_id"])

    message_text = format_plan(plan_dict)
    keyboard = plan_keyboard()

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


async def on_button(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    logger.info("Button pressed: %s by user_id=%s",
                query.data, query.from_user.id if query.from_user else "?")
    await query.message.reply_text(
        "Slice 2: button handlers come in Slice 6."
    )


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
