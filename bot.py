"""Telegram bot with /support command as requested."""
from __future__ import annotations

import logging
import os
from typing import Final

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)

LOGGER = logging.getLogger(__name__)

SUPPORT_MESSAGE: Final[str] = (
    "🛠 Чтобы мы быстрее помогли, напишите:\n"
    "— что вы сделали?\n"
    "— чего ожидали?\n"
    "— что на самом деле произошло?\n"
    "— и когда это случилось?\n\n"
    "А если еще и скриншоты будут — разберемся с вопросом в первую очередь 😊"
)

SUPPORT_BUTTON_TEXT: Final[str] = "✉️ Написать в поддержку"
PERSONAL_AREA_BUTTON_TEXT: Final[str] = "🧑‍💼 Личный кабинет"
PERSONAL_AREA_CALLBACK_DATA: Final[str] = "personal-area-unavailable"


def _support_url() -> str:
    """Return the URL to open when the user presses the support button."""
    url = os.getenv("SUPPORT_CHAT_URL")
    if not url:
        LOGGER.warning(
            "SUPPORT_CHAT_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_support_chat"
    return url


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the support helper message along with inline buttons."""
    message = update.effective_message
    if message is None:
        LOGGER.debug("No message to reply to for /support command")
        return

    keyboard = [
        [InlineKeyboardButton(SUPPORT_BUTTON_TEXT, url=_support_url())],
        [InlineKeyboardButton(PERSONAL_AREA_BUTTON_TEXT, callback_data=PERSONAL_AREA_CALLBACK_DATA)],
    ]

    await message.reply_text(
        SUPPORT_MESSAGE,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def personal_area_placeholder(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Let the user know that the personal area is not ready yet."""
    if update.callback_query is None:
        return

    await update.callback_query.answer(
        "Личный кабинет скоро появится, заглядывайте позже!", show_alert=True
    )


def build_application(token: str) -> Application:
    """Create a telegram application instance with the /support command."""
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("support", support))
    application.add_handler(
        CallbackQueryHandler(personal_area_placeholder, pattern=f"^{PERSONAL_AREA_CALLBACK_DATA}$")
    )

    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")

    build_application(token).run_polling()


if __name__ == "__main__":
    main()
