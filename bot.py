"""Telegram bot with /support command as requested."""
from __future__ import annotations

import logging
import os
from typing import Final, Sequence

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from personal_area import (
    personal_area_support_button,
    register_personal_area,
    setup_personal_area_menu,
)

LOGGER = logging.getLogger(__name__)

SUPPORT_MESSAGE: Final[str] = (
    "🛠 *Чтобы мы быстрее помогли, напишите:*\n"
    "— что вы сделали?\n"
    "— чего ожидали?\n"
    "— что на самом деле произошло?\n"
    "— и когда это случилось?\n\n"
    "А если еще и скриншоты будут — разберемся с вопросом в первую очередь 😊"
)

SUPPORT_BUTTON_TEXT: Final[str] = "✉️ Написать в поддержку"

SUPPORT_COMMAND: Final[BotCommand] = BotCommand("support", "Написать в поддержку")
PERSONAL_AREA_COMMAND: Final[BotCommand] = BotCommand("cab", "Личный кабинет")
EXTRA_COMMANDS: Final[Sequence[BotCommand]] = (SUPPORT_COMMAND,)
HANDLER_TYPES: Final[tuple[type[CommandHandler], type[CallbackQueryHandler], type[MessageHandler]]] = (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
)
FILTERS_DESCRIPTION: Final[str] = repr(filters.TEXT & ~filters.COMMAND)

__all__ = [
    "build_application",
    "main",
    "support",
]


def _support_url() -> str:
    """Return the support chat URL for the inline button."""

    url = os.getenv("SUPPORT_CHAT_URL")
    if not url:
        LOGGER.warning(
            "SUPPORT_CHAT_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_support_chat"
    return url


def _support_keyboard() -> InlineKeyboardMarkup:
    """Assemble the inline keyboard for the support helper message."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(SUPPORT_BUTTON_TEXT, url=_support_url())],
            [personal_area_support_button()],
        ]
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /support command by showing helper text and inline buttons."""

    message: Message | None = update.effective_message
    if message is None:
        LOGGER.debug("No message to reply to for /support command")
        return

    await message.reply_text(
        SUPPORT_MESSAGE,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_support_keyboard(),
    )


async def _configure_bot_commands(application: Application) -> None:
    """Register bot commands, including the personal area, in Telegram."""

    commands = [*EXTRA_COMMANDS, PERSONAL_AREA_COMMAND]
    try:
        await application.bot.set_my_commands(commands)
    except TelegramError as exc:  # pragma: no cover - сетевые ошибки некритичны
        LOGGER.warning("Unable to configure bot commands via bot.set_my_commands: %s", exc)

    await setup_personal_area_menu(application, EXTRA_COMMANDS)


def build_application(token: str) -> Application:
    """Create a telegram application instance with the /support and /cab commands."""

    application = Application.builder().token(token).build()
    LOGGER.debug(
        "Handlers prepared: %s; text filter: %s",
        ", ".join(handler.__name__ for handler in HANDLER_TYPES),
        FILTERS_DESCRIPTION,
    )

    application.add_handler(CommandHandler("support", support))
    register_personal_area(
        application,
        support_message=SUPPORT_MESSAGE,
        support_keyboard_factory=_support_keyboard,
    )

    application.post_init = _configure_bot_commands

    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")

    build_application(token).run_polling()


if __name__ == "__main__":
    main()
