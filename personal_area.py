"""Логика панели «Личный кабинет» для Telegram-бота."""
from __future__ import annotations

import logging
import os
from functools import partial
from typing import Callable, Final, Sequence

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


def personal_area_bot_command() -> BotCommand:
    """Вернуть описание команды /cab для регистрации в меню."""

    return BotCommand(PERSONAL_AREA_COMMAND, "Личный кабинет")


def personal_area_support_button() -> InlineKeyboardButton:
    """Создать кнопку открытия личного кабинета для панели поддержки."""

    return InlineKeyboardButton(
        PERSONAL_AREA_BUTTON_TEXT, callback_data=PERSONAL_AREA_CALLBACK_DATA
    )


def _support_url() -> str:
    """Вернуть ссылку на чат поддержки для кнопок внутри панели."""

    url = os.getenv("SUPPORT_CHAT_URL")
    if not url:
        LOGGER.warning(
            "SUPPORT_CHAT_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_support_chat"
    return url


def _consultation_url() -> str:
    """Вернуть ссылку для записи на консультацию."""

    url = os.getenv("CONSULTATION_URL")
    if not url:
        LOGGER.warning(
            "CONSULTATION_URL is not configured. Falling back to placeholder URL."
        )
        url = "https://t.me/your_consultation_chat"
    return url


def _format_number(value: int) -> str:
    """Форматировать числа с узким пробелом в качестве разделителя."""

    return f"{value:,}".replace(",", "\u202f")


def _generate_referral_code(user_id: int) -> str:
    """Детерминированно сгенерировать реферальный код по ID пользователя."""

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
    """Получить имя бота из кеша или запросить у Telegram."""

    username = context.bot.username
    if username:
        return username

    bot = await context.bot.get_me()
    return bot.username or os.getenv("BOT_USERNAME", "your_bot")


def _ensure_profile(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Вернуть профиль пользователя, создавая заготовку при необходимости."""

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
    """Сохранить идентификаторы последнего сообщения панели."""

    if message is None:
        return

    context.user_data[PERSONAL_AREA_MESSAGE_KEY] = {
        "chat_id": message.chat_id,
        "message_id": message.message_id,
    }


async def _personal_area_payload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str, InlineKeyboardMarkup]:
    """Построить текст и клавиатуру панели личного кабинета."""

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
    """Обновить последнее сообщение панели свежими данными."""

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
    except TelegramError as exc:  # pragma: no cover - сетевые ошибки некритичны
        LOGGER.warning("Failed to refresh personal area message: %s", exc)


async def _show_personal_area(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    new_message: bool,
) -> None:
    """Показать панель личного кабинета новым сообщением или редактированием."""

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


async def personal_area_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /cab."""

    await _show_personal_area(update, context, new_message=True)


async def personal_area_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть личный кабинет по нажатию на inline-кнопку."""

    await _show_personal_area(update, context, new_message=False)


async def personal_area_back(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    support_message: str,
    support_keyboard_factory: Callable[[], InlineKeyboardMarkup],
) -> None:
    """Вернуться к сообщению поддержки."""

    query = update.callback_query
    if query is None:
        return

    await query.answer()
    context.user_data.pop(PERSONAL_AREA_MESSAGE_KEY, None)
    await query.edit_message_text(
        support_message,
        reply_markup=support_keyboard_factory(),
    )


async def personal_area_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Закрыть панель личного кабинета и показать уведомление."""

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
    """Попросить пользователя ввести новое значение поля."""

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
    """Перейти в режим редактирования имени."""

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
    """Перейти в режим редактирования возраста."""

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
    """Обработать ответы пользователя на запросы панели."""

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
        digits = "".join(ch for ch in message.text if ch.isdigit())
        profile["age"] = digits or message.text.strip()

    context.user_data.pop(PERSONAL_AREA_AWAITING_INPUT_KEY, None)

    await message.reply_text("Данные обновлены ✅")
    await _refresh_personal_area_message(update, context)


def register_personal_area(
    application: Application,
    *,
    support_message: str,
    support_keyboard_factory: Callable[[], InlineKeyboardMarkup],
) -> None:
    """Зарегистрировать обработчики, связанные с личным кабинетом."""

    application.add_handler(CommandHandler(PERSONAL_AREA_COMMAND, personal_area_command))
    application.add_handler(
        CallbackQueryHandler(
            personal_area_callback, pattern=fr"^{PERSONAL_AREA_CALLBACK_DATA}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(
                personal_area_back,
                support_message=support_message,
                support_keyboard_factory=support_keyboard_factory,
            ),
            pattern=fr"^{PERSONAL_AREA_BACK_CALLBACK}$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            personal_area_edit_name, pattern=fr"^{PERSONAL_AREA_EDIT_NAME_CALLBACK}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            personal_area_edit_age, pattern=fr"^{PERSONAL_AREA_EDIT_AGE_CALLBACK}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            personal_area_close, pattern=fr"^{PERSONAL_AREA_CLOSE_CALLBACK}$"
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, personal_area_handle_input)
    )


async def setup_personal_area_menu(
    application: Application, extra_commands: Sequence[BotCommand]
) -> None:
    """Зарегистрировать команды бота и кнопку меню Telegram."""

    commands: list[BotCommand] = list(extra_commands)
    commands.append(personal_area_bot_command())

    unique_commands: list[BotCommand] = []
    seen: set[str] = set()
    for command in commands:
        if command.command in seen:
            continue
        unique_commands.append(command)
        seen.add(command.command)

    try:
        await application.bot.set_my_commands(unique_commands)
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except TelegramError as exc:  # pragma: no cover - сетевые ошибки некритичны
        LOGGER.warning("Unable to configure bot commands: %s", exc)
