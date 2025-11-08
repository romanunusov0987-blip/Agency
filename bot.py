"""Telegram bot with /support command as requested."""
from __future__ import annotations

import logging
import os
from typing import Final

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
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
PERSONAL_AREA_CALLBACK_DATA: Final[str] = "personal-area-open"
PERSONAL_AREA_EDIT_NAME_CALLBACK: Final[str] = "personal-area-edit-name"
PERSONAL_AREA_EDIT_AGE_CALLBACK: Final[str] = "personal-area-edit-age"
PERSONAL_AREA_BACK_CALLBACK: Final[str] = "personal-area-back"

PROFILE_KEY: Final[str] = "personal_area_profile"
AWAITING_INPUT_KEY: Final[str] = "personal_area_awaiting"

DEFAULT_COMMANDS: Final[tuple[BotCommand, ...]] = (
    BotCommand("support", "Написать в поддержку"),
    BotCommand("cab", "Личный кабинет"),
)


def _support_url() -> str:
    """Return the URL to open when the user presses the support button."""
    url = os.getenv("SUPPORT_CHAT_URL")
    if not url:
        LOGGER.warning(
            "SUPPORT_CHAT_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_support_chat"
    return url


def _consultation_url() -> str:
    """Return the URL that leads to the consultation booking flow."""
    url = os.getenv("CONSULTATION_URL")
    if not url:
        LOGGER.warning(
            "CONSULTATION_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_consultation_chat"
    return url


def _format_number(value: int) -> str:
    """Format numbers with thousands separators for readability."""
    return f"{value:,}".replace(",", " ")


def _generate_referral_code(user_id: int) -> str:
    """Create a deterministic short referral code based on the user identifier."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if user_id <= 0:
        user_id = abs(user_id) + 1
    base = len(alphabet)
    code = ""
    while user_id:
        user_id, remainder = divmod(user_id, base)
        code = alphabet[remainder] + code
    return code or "0"


async def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Resolve the bot username, falling back to a placeholder if needed."""
    username = context.bot.username
    if username:
        return username
    bot = await context.bot.get_me()
    return bot.username or os.getenv("BOT_USERNAME", "your_bot")


def _ensure_profile(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Return stored profile data, creating defaults when required."""
    profile = context.user_data.setdefault(
        PROFILE_KEY,
        {
            "name": None,
            "age": None,
            "gender": None,
            "free_tokens": 0,
            "free_tokens_limit": 50_000,
            "paid_tokens": 0,
            "subscription": 0,
            "ref_code": None,
        },
    )
    if not profile.get("ref_code"):
        profile["ref_code"] = _generate_referral_code(user_id)
    return profile


async def _personal_area_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str, InlineKeyboardMarkup]:
    """Construct the personal area message text and keyboard."""
    user = update.effective_user
    if user is None:
        raise RuntimeError("Personal area requested without an effective user")

    profile = _ensure_profile(context, user.id)
    name = profile.get("name") or "не указано"
    gender = profile.get("gender") or "не указано"
    age = profile.get("age") or "не указано"
    free_tokens = profile.get("free_tokens", 0)
    free_tokens_limit = profile.get("free_tokens_limit", 50_000)
    paid_tokens = profile.get("paid_tokens", 0)
    subscription = profile.get("subscription", 0)
    referral_code = profile.get("ref_code") or _generate_referral_code(user.id)
    username = await _bot_username(context)
    referral_link = f"https://t.me/{username}?start={referral_code}"

    text = (
        "🧑‍💼 *Личный кабинет*\n\n"
        "📋 *Твой профиль*\n"
        f"ID: `{user.id}`\n"
        f"Имя: {name}\n"
        f"Пол: {gender}\n"
        f"Возраст: {age}\n\n"
        "🎁 *Баланс токенов:*\n"
        f"   Бесплатных: {_format_number(free_tokens)} из {_format_number(free_tokens_limit)}\n"
        f"   Платных: {_format_number(paid_tokens)}\n\n"
        f"📨 Подписка: {subscription}\n\n"
        "🔗 *Твоя ссылка для приглашений:*\n"
        f"{referral_link}\n"
        "P.S. Подробнее о реферальной программе — 🎁 Поделиться"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 Назад", callback_data=PERSONAL_AREA_BACK_CALLBACK)],
            [InlineKeyboardButton("👤 Начать общение", url=_support_url())],
            [
                InlineKeyboardButton(
                    "✏️ Изменить имя", callback_data=PERSONAL_AREA_EDIT_NAME_CALLBACK
                )
            ],
            [
                InlineKeyboardButton(
                    "🎂 Изменить возраст", callback_data=PERSONAL_AREA_EDIT_AGE_CALLBACK
                )
            ],
            [
                InlineKeyboardButton(
                    "🗓 Записаться на консультацию", url=_consultation_url()
                )
            ],
        ]
    )

    return text, keyboard


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


async def _remember_personal_area_message(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
) -> None:
    """Persist the last personal area message identifiers for later updates."""
    context.user_data["personal_area_message"] = {
        "chat_id": chat_id,
        "message_id": message_id,
    }


async def show_personal_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the personal area either in response to a command or a callback."""
    text, keyboard = await _personal_area_text(update, context)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.message is None:
            return
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        await _remember_personal_area_message(
            context, query.message.chat_id, query.message.message_id
        )
        return

    message = update.effective_message
    if message is None:
        LOGGER.debug("No message found for personal area rendering")
        return

    sent = await message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    await _remember_personal_area_message(context, sent.chat_id, sent.message_id)


async def _delete_personal_area_reference(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forget stored information about the personal area message."""
    context.user_data.pop("personal_area_message", None)


async def personal_area_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the back button by deleting the personal area message."""
    if update.callback_query is None or update.callback_query.message is None:
        return

    query = update.callback_query
    await query.answer()

    try:
        await query.message.delete()
    except TelegramError as error:
        LOGGER.warning("Failed to delete personal area message: %s", error)

    await _delete_personal_area_reference(context)


async def _prompt_for_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field: str,
    prompt_text: str,
) -> None:
    """Prepare to receive user input for profile editing."""
    query = update.callback_query
    if query is None or query.message is None:
        return

    await query.answer()

    context.user_data[AWAITING_INPUT_KEY] = {
        "field": field,
        "chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
    }

    await query.message.reply_text(prompt_text)


async def personal_area_edit_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Ask the user for a new name value."""
    await _prompt_for_input(
        update,
        context,
        field="name",
        prompt_text="Введите новое имя:",
    )


async def personal_area_edit_age(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Ask the user for a new age value."""
    await _prompt_for_input(
        update,
        context,
        field="age",
        prompt_text="Введите ваш возраст (числом):",
    )


async def _refresh_personal_area_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    update: Update,
) -> None:
    """Re-render the personal area message after a profile change."""
    try:
        text, keyboard = await _personal_area_text(update, context)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as error:
        LOGGER.warning("Failed to refresh personal area message: %s", error)


async def personal_area_text_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Process user input when editing profile fields."""
    awaiting = context.user_data.get(AWAITING_INPUT_KEY)
    if not awaiting:
        return

    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    text_value = message.text.strip()
    field = awaiting.get("field")
    profile = _ensure_profile(context, user.id)

    if field == "name":
        profile["name"] = text_value
        confirmation = f"Имя обновлено на «{text_value}»."
    elif field == "age":
        digits = "".join(filter(str.isdigit, text_value))
        if not digits:
            await message.reply_text("Пожалуйста, введите возраст числом.")
            return
        profile["age"] = digits
        confirmation = f"Возраст обновлен на {digits}."
    else:
        confirmation = "Изменений не внесено."

    await message.reply_text(confirmation)
    context.user_data.pop(AWAITING_INPUT_KEY, None)

    target = context.user_data.get("personal_area_message")
    if not target:
        return

    await _refresh_personal_area_message(
        context,
        chat_id=target["chat_id"],
        message_id=target["message_id"],
        update=update,
    )


async def _configure_bot_commands(application: Application) -> None:
    """Expose key bot commands and ensure they show up in the menu."""

    await application.bot.set_my_commands(list(DEFAULT_COMMANDS))
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def build_application(token: str) -> Application:
    """Create a telegram application instance with the /support command."""
    application = Application.builder().token(token).build()

    application.post_init = _configure_bot_commands

    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler("cab", show_personal_area))
    application.add_handler(
        CallbackQueryHandler(show_personal_area, pattern=f"^{PERSONAL_AREA_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(personal_area_back, pattern=f"^{PERSONAL_AREA_BACK_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            personal_area_edit_name, pattern=f"^{PERSONAL_AREA_EDIT_NAME_CALLBACK}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            personal_area_edit_age, pattern=f"^{PERSONAL_AREA_EDIT_AGE_CALLBACK}$"
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, personal_area_text_input)
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
