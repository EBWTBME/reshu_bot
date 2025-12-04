#!/usr/bin/env python3

import logging
import os
from typing import Dict, Any

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    Application,
)
from telegram.error import Forbidden, TelegramError

TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "888140003"))
PAYMENTS_PROVIDER_TOKEN = os.getenv("PAYMENTS_PROVIDER_TOKEN", "")
CURRENCY = "RUB"

EMOJI_PRIMARY = "🔵"
EMOJI_SECONDARY = "⚪️"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

logging.getLogger("httpx").setLevel(logging.WARNING)

from warnings import filterwarnings
from telegram.warnings import PTBUserWarning
filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)

(
    TYPE_CHOICE,
    SEND_FILE,
    EXPLAIN_CHOICE,
    DEADLINE_CHOICE,
    EXTRA_PARAMS,
    CONFIRM_ORDER,
    PAYMENT,
    WAITING_FOR_RECEIPT,
) = range(8)

BASE_PRICES = {
    "Задание": 299,
    "Лабораторная/Контрольная": 999,
    "Экзаменационный вопрос": 999,
    "Практика": 4999,
    "Курсовая": 9999,
    "Дипломная": 25999,
    "Презентация для курсовой": 1999,
    "Презентация для диплома": 4999,
}

BASE_PRICES_USD = {
    "Задание": 5,
    "Лабораторная/Контрольная": 12,
    "Экзаменационный вопрос": 12,
    "Практика": 59,
    "Курсовая": 119,
    "Дипломная": 299,
    "Презентация для курсовой": 99,
    "Презентация для диплома": 199,
}

EXPLAIN_SURCHARGES = {
    "default": 2999,
    "Курсовая": 5999,
    "Дипломная": 15999,
    "Практика": 1999,
}

WORK_TYPES_TRANSLATIONS = {
    "Задание": "Assignment",
    "Лабораторная/Контрольная": "Lab / Quiz",
    "Экзаменационный вопрос": "Exam Question",
    "Практика": "Practice",
    "Курсовая": "Coursework",
    "Дипломная": "Thesis",
    "Презентация для курсовой": "Presentation for Coursework",
    "Презентация для диплома": "Presentation for Thesis",
}

def format_price_rub_usd(rub: int, usd: int) -> str:
    return f"{rub}₽ / ${usd}"

def calculate_price(selection: Dict[str, Any]) -> Dict[str, Any]:
    t = selection["type"]
    explain = selection.get("explain", False)
    days = int(selection.get("days", 0))
    extra_count = int(selection.get("extra_count", 1))

    breakdown_rub = []
    breakdown_usd = []
    total_rub = 0
    total_usd = 0

    if t in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        base_rub = BASE_PRICES[t] * extra_count
        base_usd = BASE_PRICES_USD[t] * extra_count
        en_name = WORK_TYPES_TRANSLATIONS[t]
        breakdown_rub.append(f"{t} — {BASE_PRICES[t]}₽ × {extra_count} = {base_rub}₽")
        breakdown_usd.append(f"{en_name} — ${BASE_PRICES_USD[t]} × {extra_count} = ${base_usd}")
        total_rub += base_rub
        total_usd += base_usd
    else:
        base_rub = BASE_PRICES[t]
        base_usd = BASE_PRICES_USD[t]
        en_name = WORK_TYPES_TRANSLATIONS[t]
        breakdown_rub.append(f"{t} = {base_rub}₽")
        breakdown_usd.append(f"{en_name} = ${base_usd}")
        total_rub += base_rub
        total_usd += base_usd

    if explain:
        surcharge_rub = EXPLAIN_SURCHARGES.get(t, EXPLAIN_SURCHARGES["default"])
        surcharge_usd = round(surcharge_rub / 90)
        breakdown_rub.append(f"За объяснения = +{surcharge_rub}₽")
        breakdown_usd.append(f"For explanations = +${surcharge_usd}")
        total_rub += surcharge_rub
        total_usd += surcharge_usd

    urgency_rub = 0
    if days > 0:
        if t in ("Задание", "Лабораторная/Контрольная"):
            urgency_rub = max(1500 - 100 * (days - 1), 0)
        elif t == "Экзаменационный вопрос":
            urgency_rub = max(2000 - 200 * (days - 1), 0)
        elif t == "Практика":
            urgency_rub = max(4000 - 250 * (days - 1), 0)
        elif t in ("Курсовая", "Презентация для курсовой"):
            urgency_rub = max(6000 - 250 * (days - 1), 0)
        elif t in ("Дипломная", "Презентация для диплома"):
            base = BASE_PRICES[t]
            max_urgency = 2 * base
            urgency_val = max_urgency - 250 * (days - 1)
            urgency_rub = max(urgency_val, base) - base

        urgency_rub = int(max(urgency_rub, 0))
        urgency_usd = round(urgency_rub / 90)
        if urgency_rub > 0:
            breakdown_rub.append(f"Срочность ({days} дн) = +{urgency_rub}₽")
            breakdown_usd.append(f"Urgency ({days} days) = +${urgency_usd}")
            total_rub += urgency_rub
            total_usd += urgency_usd
        else:
            breakdown_rub.append(f"Срочность ({days} дн) = +0₽")
            breakdown_usd.append(f"Urgency ({days} days) = +$0")
    else:
        if days == 0:
            breakdown_rub.append("Срочность = +0₽")
            breakdown_usd.append("Urgency = +$0")

    return {
        "total_rub": total_rub,
        "total_usd": total_usd,
        "breakdown_rub": breakdown_rub,
        "breakdown_usd": breakdown_usd,
    }

def make_reply_markup(options: list, include_cancel=True) -> ReplyKeyboardMarkup:
    buttons = []
    for opt in options:
        en_opt = WORK_TYPES_TRANSLATIONS.get(opt, opt)
        buttons.append([KeyboardButton(f"{EMOJI_PRIMARY} {opt} / {en_opt}")])
    if include_cancel:
        buttons.append([KeyboardButton("❌ Отменить заказ / Cancel order")])
    return ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True)

def parse_choice_text(text: str) -> str:
    clean = text.strip().lstrip(EMOJI_PRIMARY).lstrip(EMOJI_SECONDARY).strip()
    if " / " in clean:
        clean = clean.split(" / ")[0]
    return clean

PHRASES = {
    "start_welcome": (
        f"{EMOJI_PRIMARY} <b>Заходи за решением! / Come in for a solution! </b>\n\n"
        "Привет! Я помогу вам оперативно и качественно решить учебные задания.\n"
        "Hi! I'll help you solve your academic assignments quickly and reliably.\n\n"
        "<b>Прайс-лист / Price List</b> 💰"
    ),
    "start_types": "Выберите тип работы / Choose work type:",
    "type_chosen": "Вы выбрали: {ru} / You have chosen: {en}.",
    "send_file_prompt": (
        "📌 Пришлите, пожалуйста, <b>фото, файл или текст с заданием</b>.\n"
        "Можно добавить пояснения в подпись (caption) к файлу или фото.\n\n"
        "📌 Please send <b>photo, file or text with your assignment</b>.\n"
        "Caption allowed."
    ),
    "file_received": "✅ Файл задания получен. Теперь выберите: нужны ли объяснения?\n✅ Assignment file received. Need explanations?",
    "photo_received": "✅ Фото задания получено. Теперь выберите: нужны ли объяснения?\n✅ Assignment photo received. Need explanations?",
    "text_received": "✅ Текст задания получен. Теперь выберите: нужны ли объяснения?\n✅ Assignment text received. Need explanations?",
    "send_file_error": (
        "Пожалуйста, отправьте задание в виде текста, фото или файла (можно с подписью).\n"
        "Please send assignment as text, photo or file (caption allowed)."
    ),
    "explain_prompt": (
        "Нужны ли подробные объяснения каждого шага решения?\n"
        "За +2999₽ (за задания) / +5999₽ (за Курсовую) / +2999₽ (за Практику) / +20000₽ (за Дипломную) — я подробно объясню каждое задание и весь ход решения.\n\n"
        "Need detailed explanations?\n"
        "For +$35 (for Assignments) / +$70 (for Coursework) / +$35 (for Practice) / +$222 (for Thesis) — I'll explain each task and the entire solution process in detail."
    ),
    "explain_yes": "✅ Объяснения включены.\n✅ Explanations enabled.",
    "explain_no": "✅ Объяснения отключены.\n✅ Explanations disabled.",
    "explain_error": (
        "Пожалуйста, нажмите «Да / Yes» или «Нет / No».\n"
        "Please press «Да / Yes» or «Нет / No»."
    ),
    "deadline_prompt": (
        "Укажите срок выполнения в днях (целое число). Пример: 3\n"
        "(минимум 1 день).\n\n"
        "Specify deadline in days (integer). Example: 3\n"
        "(minimum 1 day)."
    ),
    "extra_params_prompt": (
        "Укажите количество заданий (целое число). Пример: 3\n"
        "Specify number of tasks (integer). Example: 3"
    ),
    "confirmation_summary": (
        "<b>Итог заказа / Order Summary</b>\n"
        "Тип / Type: {type}\n"
        "Объяснения / Explanations: {explain}\n"
        "Срок / Deadline: {days} дн / days\n"
        "{extra_count_line}"
        "\n<b>Детализация / Breakdown:</b>\n"
        "{breakdown_rub}\n"
        "{breakdown_usd}\n"
        "\n<b>Итого / Total: {total_rub}₽ / ${total_usd}</b>"
    ),
    "confirm_button": "✅ Подтвердить и оплатить / Confirm & Pay",
    "cancel_button": "❌ Отменить заказ / Cancel Order",
    "payment_prompt": (
        "✅ Оплата заказа:\n\n"
        "<b>Переведите {total_rub} ₽ / ${total_usd}</b> на карту:\n"
        "<code>{card_number}</code>\n\n"
        "⚠️ После оплаты отправьте сюда <b>скриншот чека</b> (фото или документ) — я уведомлю администратора, и заказ будет подтверждён.\n\n"
        "❗ Срок выполнения начинается с момента получения чека.\n\n"
        "✅ Payment:\n\n"
        "<b>Transfer {total_rub} ₽ / ${total_usd}</b> to card:\n"
        "<code>{card_number}</code>\n\n"
        "⚠️ After payment, send a <b>screenshot</b> (photo/document) — I'll notify admin, and order will be confirmed.\n\n"
        "❗ Deadline starts when payment is confirmed."
    ),
    "successful_payment": (
        "✅ Оплата получена! Спасибо!\n\n"
        "Администратор скоро свяжется с вами.\n"
        "💬 <b>Вся дальнейшая работа — правки, уточнения, сдача — будет вестись напрямую с исполнителем в личных сообщениях.</b>\n\n"
        "Хотите сделать ещё один заказ? Нажмите /start 👇\n\n"
        "✅ Payment received! Thank you!\n\n"
        "The administrator will contact you soon.\n"
        "💬 <b>All further work — revisions, clarifications, submission — will be done directly with the executor in private messages.</b>\n\n"
        "Want another order? Press /start 👇"
    ),
    "waiting_for_receipt_prompt": (
        "📎 Пожалуйста, отправьте **скриншот чека об оплате** в виде **фото или документа**.\n\n"
        "Текст, голосовые, стикеры, аудио и другие форматы не принимаются.\n\n"
        "📎 Please send **payment screenshot** as **photo or document**.\n\n"
        "Text, voice, stickers, audio and other formats are not accepted."
    ),
    "receipt_received": (
        "✅ Скриншот чека получен!\n\n"
        "Администратор проверит оплату и скоро свяжется с вами.\n"
        "💬 <b>Вся дальнейшая работа — правки, уточнения, сдача — будет вестись напрямую с исполнителем в личных сообщениях.</b>\n\n"
        "Хотите сделать ещё один заказ? Нажмите /start 👇\n\n"
        "✅ Payment screenshot received!\n\n"
        "Admin will verify payment and contact you soon.\n"
        "💬 <b>All further work — revisions, clarifications, submission — will be done directly with the executor in private messages.</b>\n\n"
        "Want another order? Press /start 👇"
    ),
    "cancel_order": (
        "Заказ отменён. Если хотите — начните заново командой /start.\n"
        "Order cancelled. Start again with /start."
    ),
    "invalid_input": (
        "Пожалуйста, используйте кнопки ниже.\n"
        "Please use the buttons below."
    ),
    "invalid_days": (
        "Пожалуйста, введите целое число дней (например: 1, 2, 3).\n"
        "Please enter integer days (e.g.: 1, 2, 3)."
    ),
    "invalid_count": (
        "Пожалуйста, введите целое количество заданий (например: 1, 2, 5).\n"
        "Please enter integer number of tasks (e.g.: 1, 2, 5)."
    ),
    "admin_notification": (
        "<b>Новый заказ / New Order</b>\n"
        "Клиент / Client: {full_name} (@{username}) id={id}\n"
        "Тип / Type: {type}\n"
        "Объяснения / Explanations: {explain}\n"
        "Срок / Deadline: {days} дн / days\n"
        "{extra_count_line}"
        "\n<b>Детализация / Breakdown:</b>\n"
        "{breakdown_rub}\n"
        "{breakdown_usd}\n"
        "\n<b>Итого / Total: {total_rub}₽ / ${total_usd}</b>\n"
        "{status}"
    ),
}

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update is not None:
        logger.error(f"Ошибка при обработке обновления {update.update_id}: {context.error}")
    else:
        logger.error(f"Ошибка вне обновления: {context.error}")

    if isinstance(context.error, Forbidden):
        if "bot was blocked by the user" in context.error.message:
            user_id = update.effective_user.id if update.effective_user else "Unknown"
            logger.info(f"Бот был заблокирован пользователем ID: {user_id}")
            if update.effective_user and context.user_data:
                context.user_data.clear()
            return
        elif "user is deactivated" in context.error.message:
            user_id = update.effective_user.id if update.effective_user else "Unknown"
            logger.info(f"Аккаунт пользователя ID: {user_id} деактивирован.")
            if update.effective_user and context.user_data:
                context.user_data.clear()
            return
        elif "chat not found" in context.error.message:
            chat_id = update.effective_chat.id if update.effective_chat else "Unknown"
            logger.info(f"Чат с ID: {chat_id} не найден.")
            if update.effective_user and context.user_data:
                context.user_data.clear()
            return

    if isinstance(context.error, TelegramError):
        logger.warning(f"Telegram ошибка: {context.error}")
        return

    logger.error(f"Произошла непредвиденная ошибка: {context.error}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_html(PHRASES["start_welcome"])
    types = list(BASE_PRICES.keys())
    await update.message.reply_text(PHRASES["start_types"], reply_markup=make_reply_markup(types))
    context.user_data["order"] = {}
    return TYPE_CHOICE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("order", None)
    await update.message.reply_text(PHRASES["cancel_order"])
    return ConversationHandler.END

async def type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = parse_choice_text(update.message.text)
    if text == "Отменить заказ" or text.startswith("❌"):
        return await cancel(update, context)
    if text not in BASE_PRICES:
        await update.message.reply_text(PHRASES["invalid_input"])
        return TYPE_CHOICE
    context.user_data["order"]["type"] = text

    en_text = WORK_TYPES_TRANSLATIONS.get(text, text)
    await update.message.reply_text(
        PHRASES["type_chosen"].format(ru=text, en=en_text),
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отменить заказ / Cancel order")]], one_time_keyboard=True, resize_keyboard=True),
        parse_mode="HTML"
    )
    await update.message.reply_text(PHRASES["send_file_prompt"], parse_mode="HTML")
    return SEND_FILE

async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    caption_for_admin = f"📩 Задание от {user.full_name} (@{user.username} | id={user.id})"

    if update.message.document:
        file_id = update.message.document.file_id
        filename = update.message.document.file_name
        caption_text = update.message.caption or ""
        full_caption = f"{caption_for_admin}\n\n📝 Подпись: {caption_text}" if caption_text else caption_for_admin
        await context.bot.send_document(ADMIN_CHAT_ID, document=file_id, caption=full_caption[:1024])
        await update.message.reply_text(PHRASES["file_received"])
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        caption_text = update.message.caption or ""
        full_caption = f"{caption_for_admin}\n\n📝 Подпись: {caption_text}" if caption_text else caption_for_admin
        await context.bot.send_photo(ADMIN_CHAT_ID, photo=file_id, caption=full_caption[:1024])
        await update.message.reply_text(PHRASES["photo_received"])
    elif update.message.text:
        if "отмен" in update.message.text.lower() or update.message.text.startswith("❌"):
            return await cancel(update, context)
        await context.bot.send_message(ADMIN_CHAT_ID, text=f"{caption_for_admin}:\n\n{update.message.text}")
        await update.message.reply_text(PHRASES["text_received"])
    else:
        await update.message.reply_text(PHRASES["send_file_error"])
        return SEND_FILE

    context.user_data["order"]["file"] = True
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton(f"{EMOJI_PRIMARY} Да / Yes"), KeyboardButton(f"{EMOJI_SECONDARY} Нет / No")],
         [KeyboardButton("❌ Отменить заказ / Cancel order")]],
        one_time_keyboard=True, resize_keyboard=True
    )
    await update.message.reply_text(PHRASES["explain_prompt"], reply_markup=kb)
    return EXPLAIN_CHOICE

async def explain_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "отмен" in update.message.text.lower() or update.message.text.startswith("❌"):
        return await cancel(update, context)
    text = update.message.text.strip().lower()
    if "да" in text or "yes" in text:
        context.user_data["order"]["explain"] = True
        await update.message.reply_text(PHRASES["explain_yes"])
    elif "нет" in text or "no" in text:
        context.user_data["order"]["explain"] = False
        await update.message.reply_text(PHRASES["explain_no"])
    else:
        await update.message.reply_text(PHRASES["explain_error"])
        return EXPLAIN_CHOICE

    await update.message.reply_text(PHRASES["deadline_prompt"])
    return DEADLINE_CHOICE

async def deadline_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "отмен" in update.message.text.lower() or update.message.text.startswith("❌"):
        return await cancel(update, context)
    try:
        days = int(update.message.text.strip())
        if days < 1:
            raise ValueError
        context.user_data["order"]["days"] = days
    except (ValueError, AttributeError):
        await update.message.reply_text(PHRASES["invalid_days"])
        return DEADLINE_CHOICE

    t = context.user_data["order"]["type"]
    if t in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        await update.message.reply_text(PHRASES["extra_params_prompt"])
        return EXTRA_PARAMS
    else:
        return await show_confirmation(update, context)

async def extra_params(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "отмен" in update.message.text.lower() or update.message.text.startswith("❌"):
        return await cancel(update, context)
    try:
        count = int(update.message.text.strip())
        if count < 1:
            raise ValueError
        context.user_data["order"]["extra_count"] = count
    except (ValueError, AttributeError):
        await update.message.reply_text(PHRASES["invalid_count"])
        return EXTRA_PARAMS

    return await show_confirmation(update, context)

async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    order = context.user_data.get("order", {})
    if "extra_count" not in order:
        order["extra_count"] = 1

    calc = calculate_price(order)
    total_rub = calc["total_rub"]
    total_usd = calc["total_usd"]
    breakdown_rub = "\n".join(calc["breakdown_rub"])
    breakdown_usd = "\n".join(calc["breakdown_usd"])

    extra_count_line = ""
    if order.get("type") in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        extra_count_line = f"Количество заданий / Quantity: {order.get('extra_count')}\n"

    summary_text = PHRASES["confirmation_summary"].format(
        type=order.get('type'),
        explain="Да" if order.get('explain') else "Нет",
        days=order.get('days'),
        extra_count_line=extra_count_line,
        breakdown_rub=breakdown_rub,
        breakdown_usd=breakdown_usd,
        total_rub=total_rub,
        total_usd=total_usd
    )

    buttons = [
        [InlineKeyboardButton(PHRASES["confirm_button"], callback_data="confirm_pay")],
        [InlineKeyboardButton(PHRASES["cancel_button"], callback_data="cancel")],
    ]
    await update.message.reply_html(summary_text, reply_markup=InlineKeyboardMarkup(buttons))
    return CONFIRM_ORDER

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        context.user_data.pop("order", None)
        await query.edit_message_text(PHRASES["cancel_order"])
        return ConversationHandler.END

    order = context.user_data.get("order", {})
    calc = calculate_price(order)
    total_rub = calc["total_rub"]
    total_usd = calc["total_usd"]
    provider_token = PAYMENTS_PROVIDER_TOKEN.strip()

    await notify_admin_new_order(context, update.effective_user, order, calc, paid=False)

    if provider_token:
        try:
            await context.bot.send_invoice(
                chat_id=update.effective_chat.id,
                title="Оплата заказа — Решу бот",
                description=f"{order.get('type')} — оплата услуги",
                payload=f"order_{update.effective_user.id}_{order.get('type')}",
                provider_token=provider_token,
                currency=CURRENCY,
                prices=[LabeledPrice(label="Итого", amount=int(total_rub) * 100)],
                start_parameter="pay_reshemu",
            )
            await query.edit_message_text("Счёт отправлен. Пожалуйста, оплатите через окно оплаты Telegram.")
            return PAYMENT
        except Exception as e:
            logger.exception("Ошибка отправки инвойса")

    card_number = "2200 7013 9298 5914"
    payment_text = PHRASES["payment_prompt"].format(total_rub=total_rub, total_usd=total_usd, card_number=card_number)
    await query.edit_message_text(payment_text, parse_mode="HTML")
    return WAITING_FOR_RECEIPT

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    order = context.user_data.get("order", {})
    calc = calculate_price(order)
    await notify_admin_new_order(context, user, order, calc, paid=True, payment=update.message.successful_payment)

    keyboard = [[KeyboardButton("/start")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(PHRASES["successful_payment"], reply_markup=reply_markup, parse_mode="HTML")
    context.user_data.pop("order", None)
    return ConversationHandler.END

async def waiting_for_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if update.message.photo or update.message.document:
        caption = f"📸 Чек от {user.full_name} (@{user.username} | id={user.id})"
        try:
            if update.message.photo:
                await context.bot.send_photo(ADMIN_CHAT_ID, photo=update.message.photo[-1].file_id, caption=caption)
            elif update.message.document:
                await context.bot.send_document(ADMIN_CHAT_ID, document=update.message.document.file_id, caption=caption)

            order = context.user_data.get("order", {})
            if order:
                calc = calculate_price(order)
                await notify_admin_new_order(context, user, order, calc, paid=True)

            keyboard = [[KeyboardButton("/start")]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(PHRASES["receipt_received"], reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка при пересылке чека: {e}")
            await update.message.reply_text("❌ Не удалось передать скриншот. Попробуйте ещё раз.")
        context.user_data.pop("order", None)
        return ConversationHandler.END

    await update.message.reply_text(PHRASES["waiting_for_receipt_prompt"])
    return WAITING_FOR_RECEIPT

async def notify_admin_new_order(context, user, order, calc, paid, payment=None):
    lines = [
        "<b>Новый заказ / New Order</b>",
        f"Клиент / Client: {user.full_name} (@{user.username}) id={user.id}",
        f"Тип / Type: {order.get('type')}",
        f"Объяснения / Explanations: {'Да' if order.get('explain') else 'Нет'}",
        f"Срок / Deadline: {order.get('days')} дн / days",
    ]
    if order.get("type") in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        lines.append(f"Количество заданий / Quantity: {order.get('extra_count')}")
    lines.append("")
    lines.append("<b>Детализация / Breakdown:</b>")
    lines.extend(calc["breakdown_rub"])
    lines.extend(calc["breakdown_usd"])
    lines.append(f"\n<b>Итого / Total: {calc['total_rub']}₽ / ${calc['total_usd']}</b>")
    if paid:
        lines.append("✅ Статус: ОПЛАЧЕН / Status: PAID")
    else:
        lines.append("⏳ Статус: ЖДУ ОПЛАТУ / Status: AWAITING PAYMENT")

    text = "\n".join(lines)
    keyboard = []
    if user.username:
        keyboard.append([InlineKeyboardButton("💬 Написать клиенту / Message Client", url=f"https://t.me/{user.username}")])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
        logger.info(f"Уведомление админу отправлено: {user.full_name}")
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора: {e}")

def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    # --- Обработчики ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))

    conv_handler = ConversationHandler(
        entry_points=[],
        states={
            TYPE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_choice)],
            SEND_FILE: [MessageHandler((filters.Document.ALL | filters.PHOTO | filters.TEXT) & ~filters.COMMAND, send_file)],
            EXPLAIN_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, explain_choice)],
            DEADLINE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deadline_choice)],
            EXTRA_PARAMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, extra_params)],
            CONFIRM_ORDER: [CallbackQueryHandler(confirm_callback)],
            PAYMENT: [MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler)],
            WAITING_FOR_RECEIPT: [MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, waiting_for_receipt)],
        },
        fallbacks=[],
        allow_reentry=False,
    )

    app.add_handler(conv_handler)
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_error_handler(error_handler)

    # --- Режим запуска (Polling или Webhook) ---
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    if WEBHOOK_URL:
        # Webhook режим для Railway
        port = int(os.getenv("PORT", 8000))
        
        logger.info(f"Запуск webhook на {WEBHOOK_URL}, порт {port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=WEBHOOK_URL,
            drop_pending_updates=True,
        )
    else:
        # Polling режим для локальной разработки
        logger.info("WEBHOOK_URL не установлен, запускаю в режиме polling")
        app.run_polling(drop_pending_updates=True)


