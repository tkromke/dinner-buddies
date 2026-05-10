"""Telegram bot entry point.

Slice 1: parse /dinner <minutes> [mood] and reply with a confirmation echo.
Later slices will replace the echo with a real plan from agent.plan().
"""

import logging
import sys

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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

    await update.message.reply_text(
        f"Got it, {name}.\n"
        f"Leaving in: {minutes} min\n"
        f"Mood: {mood or '(none)'}\n"
        f"(Slice 1: echo only — real plan coming in later slices.)"
    )


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

    logger.info("Bot starting. Mapped users: %s", config.USER_ID_TO_NAME)
    app.run_polling()


if __name__ == "__main__":
    main()
