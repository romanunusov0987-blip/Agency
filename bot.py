from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Final, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()
LOGGER = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
VEDICASTRO_API_KEY = (os.getenv("VEDICASTRO_API_KEY") or "").strip()

VEDIC_CHART_IMAGE_URL = "https://api.vedicastroapi.com/v3-json/horoscope/chart-image"
VEDIC_DEFAULT_DIV = "D1"
VEDIC_DEFAULT_STYLE = "south"
VEDIC_DEFAULT_COLOR = "#893693"
VEDIC_DEFAULT_LANG = "ru"

DB_PATH = Path("bot.db")

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


class YesNoStates:
    waiting_question = "waiting_question"
    waiting_reveal = "waiting_reveal"


BACK_IMAGE_PATH = Path("images/back.png")
FACES_DIR = Path("images/faces")
YESNO_STATE_KEY = "yesno_state"
YESNO_DATA_KEY = "yesno_data"
YESNO_HISTORY_KEY = "yesno_history"

USER_CONTEXT: Dict[int, Dict[str, Any]] = {}


def get_user_context(user_id: int) -> Dict[str, Any]:
    return USER_CONTEXT.setdefault(user_id, {})


MAJOR_ARCANA_NAMES: List[str] = [
    "Шут",
    "Маг",
    "Жрица",
    "Императрица",
    "Император",
    "Иерофант",
    "Влюблённые",
    "Колесница",
    "Сила",
    "Отшельник",
    "Колесо Фортуны",
    "Справедливость",
    "Повешенный",
    "Смерть",
    "Умеренность",
    "Дьявол",
    "Башня",
    "Звезда",
    "Луна",
    "Солнце",
    "Суд",
    "Мир",
]

MAJOR_ARCANA_KEYWORDS: Dict[int, str] = {
    0: "начало, доверие, импровизация",
    1: "воля, концентрация, ресурсы",
    2: "интуиция, тайна, глубина",
    3: "забота, изобилие, творчество",
    4: "структура, порядок, ответственность",
    5: "традиции, наставничество, обучение",
    6: "выбор, союз, привязанность",
    7: "движение, победа, фокус",
    8: "мужество, мягкая сила, баланс",
    9: "поиск, одиночество, внутренняя мудость",
    10: "цикл, перемены, удача",
    11: "равновесие, честность, договорённость",
    12: "пауза, новая перспектива, жертва",
    13: "трансформация, завершение, обновление",
    14: "гармония, умеренность, поток",
    15: "искушение, зависимость, ограничение",
    16: "кризис, освобождение, пересмотр",
    17: "надежда, вдохновение, исцеление",
    18: "сомнения, иллюзии, скрытое",
    19: "радость, ясность, успех",
    20: "пробуждение, переоценка, итог",
    21: "завершение, целостность, новый цикл",
}

MINOR_RANKS: List[str] = [
    "Туз",
    "Двойка",
    "Тройка",
    "Четвёрка",
    "Пятёрка",
    "Шестёрка",
    "Семёрка",
    "Восьмёрка",
    "Девятка",
    "Десятка",
    "Паж",
    "Рыцарь",
    "Королева",
    "Король",
]

SUIT_INFO: Dict[str, Dict[str, str]] = {
    "wands": {"name": "Жезлов", "keywords": "действие, энергия, проявление"},
    "cups": {"name": "Кубков", "keywords": "чувства, отношения, вдохновение"},
    "swords": {"name": "Мечей", "keywords": "ум, решения, конфликты"},
    "pentacles": {"name": "Пентаклей", "keywords": "материя, ресурсы, стабильность"},
}


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_user_exists(user_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()


def get_user(user_id: int) -> Dict[str, Any]:
    ensure_user_exists(user_id)
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return {}
        return dict(row)


def update_user_field(user_id: int, field: str, value: Any) -> None:
    allowed_fields = {
        "birth_date",
        "birth_time",
        "lat",
        "lon",
        "tz_offset_minutes",
        "name",
        "age",
        "gender",
    }
    if field not in allowed_fields:
        LOGGER.warning("Attempt to update unsupported field %s", field)
        return

    ensure_user_exists(user_id)
    with get_db_connection() as conn:
        conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
        conn.commit()


def calc_timezone_offset_minutes(lat: float, lon: float) -> Optional[int]:
    """
    Приблизительное смещение часового пояса от UTC в минутах по долготе.
    Без timezonefinder/pytz, без учета DST (летнего времени).
    Округляем до ближайших 30 минут, чтобы 5:30 => 330 минут и т.п.
    """
    try:
        offset_hours = lon / 15.0
        offset_hours = round(offset_hours * 2) / 2
        return int(offset_hours * 60)
    except Exception:
        return None


def iso_date_to_ddmmyyyy(iso_date: str) -> str:
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return dt.strftime("%d/%m/%Y")


def tz_minutes_to_decimal_hours(offset_minutes: int) -> str:
    hours = offset_minutes / 60.0
    s = f"{hours:.4f}".rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s


def extract_svg_from_response_text(text: str) -> Optional[str]:
    raw = text.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            candidate = data.get("response") or data.get("data")
            if isinstance(candidate, str):
                raw = candidate.strip()
    except Exception:
        pass

    if "<svg" in raw:
        return raw
    return None


def vedicastro_get_chart_svg(
    *,
    dob_ddmmyyyy: str,
    tob_hhmm: str,
    lat: float,
    lon: float,
    tz_decimal_hours: str,
    api_key: str,
    div: str = VEDIC_DEFAULT_DIV,
    style: str = VEDIC_DEFAULT_STYLE,
    color: str = VEDIC_DEFAULT_COLOR,
    lang: str = VEDIC_DEFAULT_LANG,
    timeout_sec: int = 25,
) -> str:
    if not api_key:
        raise Exception("VEDICASTRO_API_KEY пустой. Добавь ключ в .env и перезапусти бота.")

    params = {
        "dob": dob_ddmmyyyy,
        "tob": tob_hhmm,
        "lat": str(lat),
        "lon": str(lon),
        "tz": tz_decimal_hours,
        "div": div,
        "style": style,
        "color": color,
        "lang": lang,
        "api_key": api_key,
    }

    url = VEDIC_CHART_IMAGE_URL + "?" + urllib.parse.urlencode(params, safe=":/")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read()
            try:
                text = body.decode("utf-8")
            except Exception:
                text = body.decode("latin-1", errors="replace")
    except Exception as e:
        raise Exception(f"Ошибка запроса к VedicAstroAPI: {e}")

    svg = extract_svg_from_response_text(text)
    if not svg:
        snippet = text[:300].replace("\n", " ")
        raise Exception(f"VedicAstroAPI вернул неожиданный ответ (не SVG). Пример: {snippet}")

    return svg


def _support_url() -> str:
    url = os.getenv("SUPPORT_CHAT_URL")
    if not url:
        LOGGER.warning("SUPPORT_CHAT_URL is not configured. Falling back to placeholder URL.")
        url = "https://t.me/your_support_chat"
    return url


def _consultation_url() -> str:
    url = os.getenv("CONSULTATION_URL")
    if not url:
        LOGGER.warning("CONSULTATION_URL is not configured. Falling back to placeholder URL.")
        url = "https://t.me/your_consultation_chat"
    return url


def _build_tarot_cards() -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    for idx, name in enumerate(MAJOR_ARCANA_NAMES):
        cards.append(
            {
                "id": idx,
                "name": name,
                "suit": "major",
                "keywords": MAJOR_ARCANA_KEYWORDS.get(idx, ""),
            }
        )

    card_id = len(cards)
    for suit_key, suit_data in SUIT_INFO.items():
        for rank in MINOR_RANKS:
            cards.append(
                {
                    "id": card_id,
                    "name": f"{rank} {suit_data['name']}",
                    "suit": suit_key,
                    "keywords": suit_data["keywords"],
                }
            )
            card_id += 1

    return cards


TAROT_CARDS: List[Dict[str, Any]] = _build_tarot_cards()

YES_MAJOR = {1, 3, 6, 7, 10, 14, 17, 19, 21}
NO_MAJOR = {12, 13, 15, 16, 18}
INTUITION_MAJOR = {0, 2, 5, 8, 9, 11, 20, 4}

OVERRIDE_NO = {63, 58, 72}
OVERRIDE_INTUITION = {2, 9, 11, 12, 14, 55, 46}


def build_tarot_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚖️ Да / Нет", callback_data="tarot:yesno")],
            [InlineKeyboardButton(text=SUPPORT_BUTTON_TEXT, url=_support_url())],
        ]
    )


def build_main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚖️ Да / Нет", callback_data="tarot:yesno"),
                InlineKeyboardButton(text="🪐 Натальная карта", callback_data="natal_chart"),
            ],
            [InlineKeyboardButton(text=SUPPORT_BUTTON_TEXT, url=_support_url())],
        ]
    )


yesno_cancel_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="yn:cancel")],
        [InlineKeyboardButton(text="⬅️ Назад к Таро", callback_data="yn:back")],
    ]
)

yesno_after_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📝 Ещё вопрос", callback_data="tarot:yesno")],
        [InlineKeyboardButton(text="⬅️ Назад к Таро", callback_data="yn:back")],
    ]
)


def get_yesno_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🪄 Расскрыть карту", callback_data="yn:reveal")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="yn:cancel")],
            [InlineKeyboardButton(text="⬅️ Назад к Таро", callback_data="yn:back")],
        ]
    )


def _set_yesno_state(user_id: int, state: str) -> None:
    get_user_context(user_id)[YESNO_STATE_KEY] = state


def _clear_yesno_state(user_id: int) -> None:
    ctx = get_user_context(user_id)
    ctx.pop(YESNO_STATE_KEY, None)
    ctx.pop(YESNO_DATA_KEY, None)


def _set_yesno_data(user_id: int, data: Dict[str, Any]) -> None:
    get_user_context(user_id)[YESNO_DATA_KEY] = data


def _get_yesno_data(user_id: int) -> Dict[str, Any]:
    return get_user_context(user_id).get(YESNO_DATA_KEY, {})


async def magic_loading_3_steps(message: Message) -> None:
    for step in ["🔮 Тасуем карты...", "✨ Слушаем интуицию...", "🃏 Карта выбрана"]:
        await message.answer(step)
        await asyncio.sleep(2.0)


def get_user_today(_: int) -> date:
    return date.today()


def pick_yesno_card_id(user_id: int, question: str, target_day: date) -> int:
    q = " ".join((question or "").lower().split())
    key = f"yesno:{user_id}:{target_day.isoformat()}:{q}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    num = int.from_bytes(digest[:4], "big")
    return num % 78


def yesno_answer_for_card(card_id: int, card: Dict[str, Any]) -> str:
    suit = (card.get("suit") or "").lower()

    if card_id in OVERRIDE_INTUITION:
        return "intuition"
    if card_id in OVERRIDE_NO:
        return "no"

    if suit == "major" or 0 <= card_id <= 21:
        if card_id in YES_MAJOR:
            return "yes"
        if card_id in NO_MAJOR:
            return "no"
        if card_id in INTUITION_MAJOR:
            return "intuition"
        return "intuition"

    if suit == "swords":
        return "no"
    if suit in ("wands", "cups", "pentacles"):
        return "yes"

    return "intuition"


def answer_code_to_text(code: str) -> str:
    if code == "yes":
        return "✅ Да"
    if code == "no":
        return "❌ Нет"
    return "🌓 Неоднозначно — прислушайся к интуиции"


def _pick_keywords(keywords: str, n: int = 3) -> str:
    parts = [p.strip() for p in (keywords or "").split(",") if p.strip()]
    return ", ".join(parts[:n]) if parts else ""


def build_yesno_card_text(question: str, card_id: int) -> str:
    card = TAROT_CARDS[card_id]
    name = card.get("name", f"Карта #{card_id}")
    keywords = card.get("keywords", "")
    k3 = _pick_keywords(keywords, 3)
    code = yesno_answer_for_card(card_id, card)
    answer = answer_code_to_text(code)

    if code == "yes":
        meaning = (
            "Эта карта усиливает вероятность благоприятного исхода. "
            f"В твоём вопросе она подсвечивает темы: {k3 or 'важные внутренние акценты'}. "
            "Сейчас лучше двигаться вперёд, но не на автопилоте — действуй осознанно и по шагам."
        )
        tilt = (
            "• Склоняет к: ✅ Да\n"
            "• Как действовать: сделай один конкретный шаг уже сегодня.\n"
            "• На что обратить внимание: не распыляйся, держи фокус.\n"
            "• Совет: будь честен с собой — карта поддерживает смелое решение."
        )
    elif code == "no":
        meaning = (
            "Эта карта предупреждает: вероятнее всего, ответ сейчас отрицательный или ситуация небезопасна. "
            f"Вопрос упирается в темы: {k3 or 'напряжение и ограничения'}. "
            "Лучше не давить и не форсировать — сначала снизь риски и проверь факты."
        )
        tilt = (
            "• Склоняет к: ❌ Нет / не сейчас\n"
            "• Как действовать: остановись и пересобери план.\n"
            "• На что обратить внимание: где ты игнорируешь красные флаги.\n"
            "• Совет: смени подход или подожди — иначе можно потерять больше."
        )
    else:
        meaning = (
            "Эта карта не даёт прямого «да/нет». "
            "Она говорит, что многое зависит от нюансов и твоего внутреннего выбора. "
            f"Ключевые темы: {k3 or 'интуиция и тонкие сигналы'}. "
            "Сейчас важно слушать ощущения и не принимать решение на эмоциях или страхе."
        )
        tilt = (
            "• Склоняет к: 🌓 Интуиция / неоднозначно\n"
            "• Как действовать: задай себе 2–3 уточняющих вопроса и собери факты.\n"
            "• На что обратить внимание: что внутри «сжимается», а что даёт спокойствие.\n"
            "• Совет: если есть сомнение — возьми паузу и вернись к вопросу позже."
        )

    return (
        "⚖️ <b>Да / Нет</b>\n"
        f"❓ Вопрос: <i>{question}</i>\n\n"
        f"🃏 <b>{name}</b>\n"
        + (f"🔑 Ключевые слова: {keywords}\n\n" if keywords else "\n")
        + f"🔮 <b>Ответ карты:</b> {answer}\n\n"
        f"✨ <b>Что говорит карта:</b>\n{meaning}\n\n"
        f"{tilt}"
    )


def add_yesno_history(user_id: int, question: str, answer_code: str) -> None:
    history = get_user_context(user_id).setdefault(YESNO_HISTORY_KEY, [])
    history.append(
        {
            "question": question,
            "answer_code": answer_code,
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
        }
    )


def _format_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _generate_referral_code(user_id: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if user_id <= 0:
        user_id = abs(user_id) + 1
    base = len(alphabet)
    code = ""
    while user_id:
        user_id, remainder = divmod(user_id, base)
        code = alphabet[remainder] + code
    return code or "0"


async def _bot_username(bot: Bot) -> str:
    me = await bot.get_me()
    return me.username or os.getenv("BOT_USERNAME", "your_bot")


def _ensure_profile(user_id: int) -> dict:
    profile = get_user_context(user_id).setdefault(
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


async def _personal_area_text(user_id: int, bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
    profile = _ensure_profile(user_id)
    name = profile.get("name") or "не указано"
    gender = profile.get("gender") or "не указано"
    age = profile.get("age") or "не указано"
    free_tokens = profile.get("free_tokens", 0)
    free_tokens_limit = profile.get("free_tokens_limit", 50_000)
    paid_tokens = profile.get("paid_tokens", 0)
    subscription = profile.get("subscription", 0)
    referral_code = profile.get("ref_code") or _generate_referral_code(user_id)
    username = await _bot_username(bot)
    referral_link = f"https://t.me/{username}?start={referral_code}"

    text = (
        "🧑‍💼 *Личный кабинет*\n\n"
        "📋 *Твой профиль*\n"
        f"ID: `{user_id}`\n"
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
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=PERSONAL_AREA_BACK_CALLBACK)],
            [InlineKeyboardButton(text="👤 Начать общение", url=_support_url())],
            [InlineKeyboardButton(text="️ Изменить имя", callback_data=PERSONAL_AREA_EDIT_NAME_CALLBACK)],
            [InlineKeyboardButton(text="🎂 Изменить возраст", callback_data=PERSONAL_AREA_EDIT_AGE_CALLBACK)],
            [InlineKeyboardButton(text="🗓 Записаться на консультацию", url=_consultation_url())],
        ]
    )

    return text, keyboard


async def support(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=SUPPORT_BUTTON_TEXT, url=_support_url())],
            [InlineKeyboardButton(text=PERSONAL_AREA_BUTTON_TEXT, callback_data=PERSONAL_AREA_CALLBACK_DATA)],
        ]
    )

    await message.answer(SUPPORT_MESSAGE, reply_markup=keyboard)


async def _remember_personal_area_message(user_id: int, chat_id: int, message_id: int) -> None:
    get_user_context(user_id)["personal_area_message"] = {
        "chat_id": chat_id,
        "message_id": message_id,
    }


async def _send_personal_area_message(
    *,
    bot: Bot,
    user_id: int,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
    reply_to: Message | None = None,
) -> None:
    if reply_to is not None:
        sent = await reply_to.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await _remember_personal_area_message(user_id, sent.chat.id, sent.message_id)


async def show_personal_area(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer()
    user_id = callback.from_user.id
    text, keyboard = await _personal_area_text(user_id, callback.message.bot)
    message = callback.message
    if message is None:
        return

    try:
        await message.edit_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        await _remember_personal_area_message(user_id, message.chat.id, message.message_id)
    except Exception:
        await _send_personal_area_message(
            bot=callback.message.bot,
            user_id=user_id,
            chat_id=message.chat.id,
            text=text,
            keyboard=keyboard,
            reply_to=message,
        )


async def show_personal_area_command(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    text, keyboard = await _personal_area_text(user.id, message.bot)
    await _send_personal_area_message(
        bot=message.bot,
        user_id=user.id,
        chat_id=message.chat.id,
        text=text,
        keyboard=keyboard,
        reply_to=message,
    )


async def personal_area_back(callback: CallbackQuery) -> None:
    if callback.message is None or callback.from_user is None:
        return
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    get_user_context(callback.from_user.id).pop("personal_area_message", None)


async def _prompt_for_input(callback: CallbackQuery, field: str, prompt_text: str) -> None:
    if callback.message is None or callback.from_user is None:
        return
    await callback.answer()

    get_user_context(callback.from_user.id)[AWAITING_INPUT_KEY] = {
        "field": field,
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
    }

    await callback.message.answer(prompt_text)


async def personal_area_edit_name(callback: CallbackQuery) -> None:
    await _prompt_for_input(callback, "name", "Введите новое имя:")


async def personal_area_edit_age(callback: CallbackQuery) -> None:
    await _prompt_for_input(callback, "age", "Введите ваш возраст (числом):")


async def _refresh_personal_area_message(user_id: int, bot: Bot, update_message: Message) -> None:
    target = get_user_context(user_id).get("personal_area_message")
    if not target:
        return
    try:
        text, keyboard = await _personal_area_text(user_id, bot)
        await bot.edit_message_text(
            chat_id=target["chat_id"],
            message_id=target["message_id"],
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        try:
            await bot.delete_message(chat_id=target["chat_id"], message_id=target["message_id"])
        except Exception:
            pass
        await _send_personal_area_message(bot=bot, user_id=user_id, chat_id=update_message.chat.id, text=text, keyboard=keyboard)


async def personal_area_text_input(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    user_id = user.id
    awaiting = get_user_context(user_id).get(AWAITING_INPUT_KEY)
    if not awaiting:
        return

    text_value = (message.text or "").strip()
    field = awaiting.get("field")
    profile = _ensure_profile(user_id)

    if field == "name":
        profile["name"] = text_value
        confirmation = f"Имя обновлено на «{text_value}»."
    elif field == "age":
        digits = "".join(filter(str.isdigit, text_value))
        if not digits:
            await message.answer("Пожалуйста, введите возраст числом.")
            return
        profile["age"] = digits
        confirmation = f"Возраст обновлен на {digits}."
    else:
        confirmation = "Изменений не внесено."

    await message.answer(confirmation)
    get_user_context(user_id).pop(AWAITING_INPUT_KEY, None)
    await _refresh_personal_area_message(user_id, message.bot, message)


async def send_main_menu(message: Message) -> None:
    await message.answer("🏠 Главное меню\n\nВыбери действие:", reply_markup=build_main_menu_kb())


async def send_tarot_menu(message: Message) -> None:
    await message.answer("🔮 Расклад таро\n\nВыбери действие:", reply_markup=build_tarot_menu_kb())


async def start(message: Message) -> None:
    await send_main_menu(message)


async def on_natal_chart(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    user_id = callback.from_user.id

    user = get_user(user_id)
    birth_date = user.get("birth_date")
    birth_time = user.get("birth_time")
    lat = user.get("lat")
    lon = user.get("lon")
    tz_offset_minutes_raw = user.get("tz_offset_minutes")

    if not birth_date or not birth_time or lat is None or lon is None:
        await callback.message.answer(
            "🪐 Чтобы построить натальную карту, сначала заполни:\n"
            "📅 дату и время рождения\n"
            "📍 место рождения (координаты)\n\n"
            "Зайди: 👤 Мой аккаунт → 📁 Данные → 📅 Данные рождения"
        )
        return

    tz_offset_minutes: Optional[int]
    try:
        tz_offset_minutes = int(tz_offset_minutes_raw)
    except Exception:
        tz_offset_minutes = None

    if tz_offset_minutes is None:
        try:
            approx = calc_timezone_offset_minutes(float(lat), float(lon))
        except Exception:
            approx = None
        if approx is not None:
            tz_offset_minutes = approx
            update_user_field(user_id, "tz_offset_minutes", tz_offset_minutes)

    if tz_offset_minutes is None:
        await callback.message.answer(
            "⚠️ Не получилось определить часовой пояс (tz) даже приближённо.\n"
            "Попробуй заново отправить место рождения (геолокацию)."
        )
        return

    loading_msg = await callback.message.answer("✨ Составляю натальную карту…")
    await asyncio.sleep(2)

    try:
        dob = iso_date_to_ddmmyyyy(str(birth_date))
        tz_decimal = tz_minutes_to_decimal_hours(int(tz_offset_minutes))

        svg = vedicastro_get_chart_svg(
            dob_ddmmyyyy=dob,
            tob_hhmm=str(birth_time),
            lat=float(lat),
            lon=float(lon),
            tz_decimal_hours=tz_decimal,
            api_key=VEDICASTRO_API_KEY,
            div=VEDIC_DEFAULT_DIV,
            style=VEDIC_DEFAULT_STYLE,
            color=VEDIC_DEFAULT_COLOR,
            lang=VEDIC_DEFAULT_LANG,
        )

        svg_bytes = svg.encode("utf-8", errors="replace")
        doc = BufferedInputFile(svg_bytes, filename="natal_chart.svg")

        await callback.message.answer_document(document=doc, caption="🪐 Натальная карта готова (SVG-файл).")

        try:
            await loading_msg.delete()
        except Exception:
            pass

    except Exception as e:
        try:
            await loading_msg.edit_text(f"❌ Не удалось построить натальную карту.\n\n{e}")
        except Exception:
            await callback.message.answer(f"❌ Не удалось построить натальную карту.\n\n{e}")


async def on_yesno_start(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    user_id = callback.from_user.id
    _clear_yesno_state(user_id)
    _set_yesno_state(user_id, YesNoStates.waiting_question)

    await callback.message.answer(
        "⚖️ Да / Нет\n\n"
        "Напиши свой вопрос одним сообщением.\n"
        "Пример: «Получится ли у меня договориться сегодня?»",
        reply_markup=yesno_cancel_kb,
    )


async def on_yesno_question(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    user_id = user.id
    if get_user_context(user_id).get(YESNO_STATE_KEY) != YesNoStates.waiting_question:
        return

    question = (message.text or "").strip()

    if not question:
        await message.answer("Напиши вопрос текстом 🙂", reply_markup=yesno_cancel_kb)
        return

    if len(question) > 300:
        await message.answer("Слишком длинно. Сократи вопрос до 1–2 предложений.", reply_markup=yesno_cancel_kb)
        return

    today = get_user_today(user_id)
    card_id = pick_yesno_card_id(user_id, question, today)

    _set_yesno_data(user_id, {"yn_question": question, "yn_card_id": card_id, "yn_day": today.isoformat()})
    _set_yesno_state(user_id, YesNoStates.waiting_reveal)

    if not BACK_IMAGE_PATH.exists():
        await message.answer(f"❌ Не найден файл рубашки: {BACK_IMAGE_PATH}")
        return

    await magic_loading_3_steps(message)

    await message.answer_photo(
        photo=FSInputFile(str(BACK_IMAGE_PATH)),
        caption="🔮 Карта выбрана. Нажми «Расскрыть карту».",
        reply_markup=get_yesno_back_kb(),
    )


async def on_yesno_reveal(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    user_id = callback.from_user.id
    data = _get_yesno_data(user_id)
    question = data.get("yn_question")
    card_id = data.get("yn_card_id")

    if question is None or card_id is None:
        await callback.message.answer("❗️Сценарий устарел. Нажми «⚖️ Да / Нет» и задай вопрос ещё раз.", reply_markup=build_tarot_menu_kb())
        return

    try:
        card_id_int = int(card_id)
    except Exception:
        await callback.message.answer("❌ Не удалось прочитать карту. Попробуй ещё раз.")
        return

    face_path = FACES_DIR / f"{card_id_int}.png"
    if not face_path.exists():
        await callback.message.answer(f"❌ Не найден файл карты: {face_path}")
        return

    card = TAROT_CARDS[card_id_int]
    answer_code = yesno_answer_for_card(card_id_int, card)
    add_yesno_history(user_id, question, answer_code)
    caption = build_yesno_card_text(question, card_id_int)

    await callback.message.answer_photo(
        photo=FSInputFile(str(face_path)),
        caption=caption,
        reply_markup=yesno_after_kb,
        parse_mode=ParseMode.HTML,
    )
    _clear_yesno_state(user_id)


async def on_yesno_cancel(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    _clear_yesno_state(callback.from_user.id)
    await callback.message.answer("Сценарий отменён.", reply_markup=build_tarot_menu_kb())


async def on_yesno_back(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    _clear_yesno_state(callback.from_user.id)
    await callback.message.answer("⬅️ Возвращаю в меню таро.", reply_markup=build_tarot_menu_kb())


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(start, Command("start"))
    dp.message.register(support, Command("support"))
    dp.message.register(show_personal_area_command, Command("cab"))
    dp.callback_query.register(on_natal_chart, F.data == "natal_chart")
    dp.callback_query.register(on_yesno_start, F.data == "tarot:yesno")
    dp.callback_query.register(on_yesno_reveal, F.data == "yn:reveal")
    dp.callback_query.register(on_yesno_cancel, F.data == "yn:cancel")
    dp.callback_query.register(on_yesno_back, F.data == "yn:back")
    dp.callback_query.register(show_personal_area, F.data == PERSONAL_AREA_CALLBACK_DATA)
    dp.callback_query.register(personal_area_back, F.data == PERSONAL_AREA_BACK_CALLBACK)
    dp.callback_query.register(personal_area_edit_name, F.data == PERSONAL_AREA_EDIT_NAME_CALLBACK)
    dp.callback_query.register(personal_area_edit_age, F.data == PERSONAL_AREA_EDIT_AGE_CALLBACK)

    dp.message.register(on_yesno_question, F.text)
    dp.message.register(personal_area_text_input, F.text)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
