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

PERSONAL_AREA_COMMAND: Final[str] = "cab"
PERSONAL_AREA_CALLBACK_DATA: Final[str] = "personal-area-open"
PERSONAL_AREA_EDIT_NAME_CALLBACK: Final[str] = "personal-area-edit-name"
PERSONAL_AREA_EDIT_AGE_CALLBACK: Final[str] = "personal-area-edit-age"
PERSONAL_AREA_BACK_CALLBACK: Final[str] = "personal-area-back"
PERSONAL_AREA_CLOSE_CALLBACK: Final[str] = "personal-area-close"

PERSONAL_AREA_PROFILE_KEY: Final[str] = "personal_area_profile"
PERSONAL_AREA_AWAITING_INPUT_KEY: Final[str] = "personal_area_awaiting"
PERSONAL_AREA_MESSAGE_KEY: Final[str] = "personal_area_message"

BOT_COMMANDS: Final[tuple[BotCommand, ...]] = (
    BotCommand("support", "Написать в поддержку"),
    BotCommand(PERSONAL_AREA_COMMAND, "Личный кабинет"),
)


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
            [InlineKeyboardButton(PERSONAL_AREA_BUTTON_TEXT, callback_data=PERSONAL_AREA_CALLBACK_DATA)],
        ]
    )


def _consultation_url() -> str:
    """Return the consultation URL for booking a meeting with the team."""
    url = os.getenv("CONSULTATION_URL")
    if not url:
        LOGGER.warning(
            "CONSULTATION_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_consultation_chat"
    return url


def _format_number(value: int) -> str:
    """Format integers with a thin space as a thousands separator."""
    return f"{value:,}".replace(",", " ")


def _generate_referral_code(user_id: int) -> str:
    """Generate a deterministic referral code based on the Telegram user id."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    base = len(alphabet)
    if user_id <= 0:
        user_id = abs(user_id) + 1

    code = ""
    while user_id:
        user_id, remainder = divmod(user_id, base)
        code = alphabet[remainder] + code
    return code or "0"


async def _resolve_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Return the bot username by querying Telegram when required."""
    username = context.bot.username
    if username:
        return username

    bot = await context.bot.get_me()
    return bot.username or os.getenv("BOT_USERNAME", "your_bot")


def _ensure_profile(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Fetch personal area data for the user, creating defaults when necessary."""
    profile = context.user_data.setdefault(
        PERSONAL_AREA_PROFILE_KEY,
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


def _remember_personal_area_message(context: ContextTypes.DEFAULT_TYPE, message) -> None:
    """Store the latest personal area message identifiers for later updates."""

    if message is None:
        return

    context.user_data[PERSONAL_AREA_MESSAGE_KEY] = {
        "chat_id": message.chat_id,
        "message_id": message.message_id,
    }


async def _personal_area_payload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str, InlineKeyboardMarkup]:
    """Build personal area text and inline keyboard based on stored profile."""

    user = update.effective_user
    if user is None:
        raise RuntimeError("Personal area requested without an effective user")

    profile = _ensure_profile(context, user.id)
    name = profile.get("name") or "не указано"
    gender = profile.get("gender") or "не указано"
    age = profile.get("age") or "не указано"
    free_tokens = profile.get("free_tokens", 0)
    free_limit = profile.get("free_tokens_limit", 50_000)
    paid_tokens = profile.get("paid_tokens", 0)
    subscription = profile.get("subscription", 0)
    ref_code = profile.get("ref_code") or _generate_referral_code(user.id)

    username = await _resolve_bot_username(context)
    referral_link = f"https://t.me/{username}?start={ref_code}"

    text = (
        "🧑‍💼 *Личный кабинет*\n\n"
        "📋 *Твой профиль*\n"
        f"ID: `{user.id}`\n"
        f"Имя: {name}\n"
        f"Пол: {gender}\n"
        f"Возраст: {age}\n\n"
        "🎁 *Баланс токенов:*\n"
        f"   Бесплатных: {_format_number(free_tokens)} из {_format_number(free_limit)}\n"
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
            [InlineKeyboardButton("🔙 Закрыть", callback_data=PERSONAL_AREA_CLOSE_CALLBACK)],
        ]
    )

    return text, keyboard


async def _refresh_personal_area_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Update the stored personal area message with fresh profile data."""

    target = context.user_data.get(PERSONAL_AREA_MESSAGE_KEY)
    if not target:
        return

    text, keyboard = await _personal_area_payload(update, context)

    try:
        await context.bot.edit_message_text(
            chat_id=target["chat_id"],
            message_id=target["message_id"],
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:  # pragma: no cover - network failure is not critical
        LOGGER.warning("Failed to refresh personal area message: %s", exc)


async def _show_personal_area(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    new_message: bool,
) -> None:
    """Render the personal area either as a new message or by editing the current one."""

    text, keyboard = await _personal_area_payload(update, context)

    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        _remember_personal_area_message(context, query.message)
        return

    message = update.effective_message
    if message is None:
        LOGGER.debug("No message to display personal area")
        return

    if new_message:
        sent = await message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        _remember_personal_area_message(context, sent)
    else:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        _remember_personal_area_message(context, message)


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /support command by showing helper text and inline buttons."""
    message = update.effective_message
    if message is None:
        LOGGER.debug("No message to reply to for /support command")
        return

    await message.reply_text(
        SUPPORT_MESSAGE,
        reply_markup=_support_keyboard(),
    )


async def personal_area_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for the /cab command."""
    await _show_personal_area(update, context, new_message=True)


async def personal_area_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses that request the personal area."""
    await _show_personal_area(update, context, new_message=False)


async def personal_area_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return the user back to the support helper message."""

    query = update.callback_query
    if query is None:
        return

    await query.answer()
    context.user_data.pop(PERSONAL_AREA_MESSAGE_KEY, None)
    await query.edit_message_text(
        SUPPORT_MESSAGE,
        reply_markup=_support_keyboard(),
    )


async def personal_area_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the personal area panel by replacing it with a short notification."""
    query = update.callback_query
    if query is None:
        return

    await query.answer("Панель закрыта")
    context.user_data.pop(PERSONAL_AREA_MESSAGE_KEY, None)
    await query.edit_message_text("Панель личного кабинета закрыта.")


async def _ask_for_value(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    field: str,
    prompt: str,
) -> None:
    """Request the user to enter a value for one of the editable fields."""

    query = update.callback_query
    if query is None:
        return

    context.user_data[PERSONAL_AREA_AWAITING_INPUT_KEY] = field
    await query.answer()
    await query.edit_message_text(
        prompt,
        parse_mode=ParseMode.MARKDOWN,
    )


async def personal_area_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the flow into name editing mode."""
    await _ask_for_value(
        update,
        context,
        field="name",
        prompt=(
            "✏️ *Изменение имени*\n\n"
            "Отправьте новое имя одним сообщением.\n"
            "Чтобы отменить, отправьте /cab."
        ),
    )


async def personal_area_edit_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the flow into age editing mode."""
    await _ask_for_value(
        update,
        context,
        field="age",
        prompt=(
            "🎂 *Изменение возраста*\n\n"
            "Отправьте возраст числом.\n"
            "Чтобы отменить, отправьте /cab."
        ),
    )


async def personal_area_handle_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Process textual responses for the personal area edit flows."""

    awaiting = context.user_data.get(PERSONAL_AREA_AWAITING_INPUT_KEY)
    if not awaiting:
        return

    message = update.effective_message
    if message is None or message.text is None:
        return

    profile = _ensure_profile(context, update.effective_user.id if update.effective_user else 0)

    if awaiting == "name":
        profile["name"] = message.text.strip()
    elif awaiting == "age":
        digits = ''.join(ch for ch in message.text if ch.isdigit())
        profile["age"] = digits or message.text.strip()

    context.user_data.pop(PERSONAL_AREA_AWAITING_INPUT_KEY, None)

    await message.reply_text("Данные обновлены ✅")
    await _refresh_personal_area_message(update, context)


async def _update_bot_commands(application: Application) -> None:
    """Synchronise bot commands and ensure the menu button lists them."""

    try:
        await application.bot.set_my_commands(list(BOT_COMMANDS))
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except TelegramError as exc:  # pragma: no cover - network failure is not critical
        LOGGER.warning("Unable to configure bot commands: %s", exc)


def build_application(token: str) -> Application:
    """Create a telegram application instance with the /support and /cab commands."""
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler(PERSONAL_AREA_COMMAND, personal_area_command))
    application.add_handler(
        CallbackQueryHandler(personal_area_callback, pattern=f"^{PERSONAL_AREA_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(personal_area_back, pattern=f"^{PERSONAL_AREA_BACK_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(personal_area_edit_name, pattern=f"^{PERSONAL_AREA_EDIT_NAME_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(personal_area_edit_age, pattern=f"^{PERSONAL_AREA_EDIT_AGE_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(personal_area_close, pattern=f"^{PERSONAL_AREA_CLOSE_CALLBACK}$")
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, personal_area_handle_input)
    )

    application.post_init.append(_update_bot_commands)

    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")

    build_application(token).run_polling()


if __name__ == "__main__":
    main()
