#!/usr/bin/env python3

import logging
import os
import time
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

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.getenv("TG_BOT_TOKEN")
if not TOKEN:
    TOKEN = "8305490732:AAHhV5MceF35nmbGjvC23tajpWOY1zrYspg"
    if TOKEN == "8305490732:AAHhV5MceF35nmbGjvC23tajpWOY1zrYspg":
        logging.error("⚠️ Используется хардкодный токен! Создайте новый через @BotFather")

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "888140003"))
PAYMENTS_PROVIDER_TOKEN = os.getenv("PAYMENTS_PROVIDER_TOKEN", "")
CURRENCY = "RUB"

EMOJI_PRIMARY = "🔵"
EMOJI_SECONDARY = "⚪️"

# ========== ЛОГГИРОВАНИЕ ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== СОСТОЯНИЯ РАЗГОВОРА ==========
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

# ========== ЦЕНЫ В РУБЛЯХ ==========
BASE_PRICES = {
    "Задание": 199,
    "Лабораторная/Контрольная": 499,
    "Экзаменационный вопрос": 599,
    "Практика": 2999,
    "Курсовая": 6999,
    "Дипломная": 19999,
    "Презентация для курсовой": 1999,
    "Презентация для диплома": 4999,
}

# ========== ЦЕНЫ В ЕВРО ==========
BASE_PRICES_EUR = {k: v // 100 for k, v in BASE_PRICES.items()}

# ========== ДОПЛАТА ЗА ОБЪЯСНЕНИЯ ==========
EXPLAIN_SURCHARGES = {
    "default": 1999,
    "Курсовая": 3999,
    "Дипломная": 9999,
    "Практика": 999,
}

# ========== ПЕРЕВОДЫ ТИПОВ РАБОТ ==========
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

# ========== ГЕНЕРАЦИЯ ПРАЙС-ЛИСТА ==========
price_lines = []
for work_type, rub_price in BASE_PRICES.items():
    en_type = WORK_TYPES_TRANSLATIONS.get(work_type, work_type)
    eur_price = BASE_PRICES_EUR[work_type]
    price_lines.append(f"• {work_type} — {rub_price}₽ / {eur_price}€ ({en_type})")

price_list_text = "\n".join(price_lines)

# ========== ФУНКЦИИ ==========
def calculate_price(selection: Dict[str, Any]) -> Dict[str, Any]:
    t = selection["type"]
    explain = selection.get("explain", False)
    days = int(selection.get("days", 0))
    extra_count = int(selection.get("extra_count", 1))

    breakdown_rub = []
    breakdown_eur = []
    total_rub = 0
    total_eur = 0

    if t in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        base_rub = BASE_PRICES[t] * extra_count
        base_eur = BASE_PRICES_EUR[t] * extra_count
        en_name = WORK_TYPES_TRANSLATIONS[t]
        breakdown_rub.append(f"{t} — {BASE_PRICES[t]}₽ × {extra_count} = {base_rub}₽")
        breakdown_eur.append(f"{en_name} — {BASE_PRICES_EUR[t]}€ × {extra_count} = {base_eur}€")
        total_rub += base_rub
        total_eur += base_eur
    else:
        base_rub = BASE_PRICES[t]
        base_eur = BASE_PRICES_EUR[t]
        en_name = WORK_TYPES_TRANSLATIONS[t]
        breakdown_rub.append(f"{t} = {base_rub}₽")
        breakdown_eur.append(f"{en_name} = {base_eur}€")
        total_rub += base_rub
        total_eur += base_eur

    if explain:
        surcharge_rub = EXPLAIN_SURCHARGES.get(t, EXPLAIN_SURCHARGES["default"])
        surcharge_eur = surcharge_rub // 100
        breakdown_rub.append(f"За объяснения = +{surcharge_rub}₽")
        breakdown_eur.append(f"For explanations = +{surcharge_eur}€")
        total_rub += surcharge_rub
        total_eur += surcharge_eur

    urgency_rub = 0
    urgency_eur = 0
    if days > 0:
        if t in ("Задание", "Лабораторная/Контрольная"):
            urgency_rub = max(1000 - 100 * (days - 1), 0)
        elif t == "Экзаменационный вопрос":
            urgency_rub = max(1500 - 100 * (days - 1), 0)
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
        urgency_eur = urgency_rub // 100

        if urgency_rub > 0:
            breakdown_rub.append(f"Срочность ({days} дн) = +{urgency_rub}₽")
            breakdown_eur.append(f"Urgency ({days} days) = +{urgency_eur}€")
            total_rub += urgency_rub
            total_eur += urgency_eur
        else:
            breakdown_rub.append(f"Срочность ({days} дн) = +0₽")
            breakdown_eur.append(f"Urgency ({days} days) = +0€")
    else:
        if days == 0:
            breakdown_rub.append("Срочность = +0₽")
            breakdown_eur.append("Urgency = +0€")

    return {
        "total_rub": total_rub,
        "total_eur": total_eur,
        "breakdown_rub": breakdown_rub,
        "breakdown_eur": breakdown_eur,
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
    if not text:
        return ""
    clean = text.strip()
    if clean.startswith(EMOJI_PRIMARY) or clean.startswith(EMOJI_SECONDARY):
        clean = clean[1:].strip()
    if " / " in clean:
        clean = clean.split(" / ")[0].strip()
    return clean

# ========== ТЕКСТЫ СООБЩЕНИЙ ==========
PHRASES = {
    "start_welcome": (
        f"{EMOJI_PRIMARY} <b>Заходи за решением! / Come in for a solution!</b>\n\n"
        "Привет! Я помогу вам оперативно и качественно решить учебные задания.\n"
        "Hi! I'll help you solve your academic assignments quickly and reliably.\n\n"
        "<b>Прайс-лист / Price List</b> 💰\n\n"
        f"{price_list_text}"
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
        "За +1999₽ (за задания) / +3999₽ (за Курсовую) / +999₽ (за Практику) / +9999₽ (за Дипломную) — я подробно объясню каждое задание и весь ход решения.\n\n"
        "Need detailed explanations?\n"
        "For +20€ (Assignments) / +40€ (Coursework) / +10€ (Practice) / +100€ (Thesis) — I'll explain each task and the entire solution process in detail."
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
        "{breakdown_eur}\n"
        "\n<b>Итого / Total: {total_rub}₽ / {total_eur}€</b>"
    ),
    "confirm_button": "✅ Подтвердить и оплатить / Confirm & Pay",
    "cancel_button": "❌ Отменить заказ / Cancel Order",
    "payment_prompt": (
        "✅ Оплата заказа:\n\n"
        "<b>Переведите {total_rub} ₽ ({total_eur}€)</b> на карту:\n"
        "<code>2200 7013 9298 5914</code>\n\n"
        "⚠️ После оплаты отправьте сюда <b>скриншот чека</b> (фото или документ) — я уведомлю администратора, и заказ будет подтверждён.\n\n"
        "❗ Срок выполнения начинается с момента получения чека.\n\n"
        "✅ Payment:\n\n"
        "<b>Transfer {total_rub} ₽ ({total_eur}€)</b> to card:\n"
        "<code>2200 7013 9298 5914</code>\n\n"
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
}

# ========== ОБРАБОТЧИКИ ==========
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Ошибка: {context.error}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Команда /start от {update.effective_user.username}")
    context.user_data.clear()
    context.user_data["order"] = {}
    await update.message.reply_html(PHRASES["start_welcome"])
    types = list(BASE_PRICES.keys())
    await update.message.reply_text(PHRASES["start_types"], reply_markup=make_reply_markup(types))
    return TYPE_CHOICE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(PHRASES["cancel_order"])
    return ConversationHandler.END

async def type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text
    logger.info(f"Пользователь выбрал: {user_text}")
    
    if "отмен" in user_text.lower() or "❌" in user_text:
        return await cancel(update, context)
    
    text = parse_choice_text(user_text)
    
    if text not in BASE_PRICES:
        logger.warning(f"Неизвестный тип: {text}")
        await update.message.reply_text(PHRASES["invalid_input"])
        return TYPE_CHOICE
    
    context.user_data["order"]["type"] = text
    en_text = WORK_TYPES_TRANSLATIONS.get(text, text)
    
    await update.message.reply_text(
        PHRASES["type_chosen"].format(ru=text, en=en_text),
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("❌ Отменить заказ / Cancel order")]], 
            resize_keyboard=True
        ),
        parse_mode="HTML"
    )
    
    await update.message.reply_text(PHRASES["send_file_prompt"], parse_mode="HTML")
    return SEND_FILE

async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    
    if update.message.text and ("отмен" in update.message.text.lower() or "❌" in update.message.text):
        return await cancel(update, context)

    if update.message.document:
        file_id = update.message.document.file_id
        caption_text = update.message.caption or ""
        
        # СОХРАНЯЕМ задание локально, НЕ отправляем админу
        context.user_data["order"]["assignment"] = {
            "type": "document",
            "file_id": file_id,
            "caption": caption_text,
            "full_caption": f"📩 Задание от {user.full_name} (@{user.username} | id={user.id})\n\n📝 Подпись: {caption_text}" if caption_text else f"📩 Задание от {user.full_name} (@{user.username} | id={user.id})"
        }
        await update.message.reply_text(PHRASES["file_received"])
        
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        caption_text = update.message.caption or ""
        
        # СОХРАНЯЕМ задание локально, НЕ отправляем админу
        context.user_data["order"]["assignment"] = {
            "type": "photo",
            "file_id": file_id,
            "caption": caption_text,
            "full_caption": f"📩 Задание от {user.full_name} (@{user.username} | id={user.id})\n\n📝 Подпись: {caption_text}" if caption_text else f"📩 Задание от {user.full_name} (@{user.username} | id={user.id})"
        }
        await update.message.reply_text(PHRASES["photo_received"])
        
    elif update.message.text:
        # Проверка на отмену
        if "отмен" in update.message.text.lower() or "❌" in update.message.text:
            return await cancel(update, context)
        
        # СОХРАНЯЕМ задание локально, НЕ отправляем админу
        context.user_data["order"]["assignment"] = {
            "type": "text",
            "content": update.message.text,
            "full_caption": f"📩 Задание от {user.full_name} (@{user.username} | id={user.id}):\n\n{update.message.text}"
        }
        await update.message.reply_text(PHRASES["text_received"])
    else:
        await update.message.reply_text(PHRASES["send_file_error"])
        return SEND_FILE

    kb = ReplyKeyboardMarkup(
        [
            [KeyboardButton(f"{EMOJI_PRIMARY} Да / Yes"), KeyboardButton(f"{EMOJI_SECONDARY} Нет / No")],
            [KeyboardButton("❌ Отменить заказ / Cancel order")]
        ],
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    await update.message.reply_text(PHRASES["explain_prompt"], reply_markup=kb)
    return EXPLAIN_CHOICE

async def explain_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "отмен" in update.message.text.lower() or "❌" in update.message.text:
        return await cancel(update, context)
    
    text = update.message.text.lower()
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
    if "отмен" in update.message.text.lower() or "❌" in update.message.text:
        return await cancel(update, context)
    
    try:
        days = int(update.message.text.strip())
        if days < 1:
            raise ValueError
        context.user_data["order"]["days"] = days
    except (ValueError, AttributeError):
        await update.message.reply_text(PHRASES["invalid_days"])
        return DEADLINE_CHOICE

    if context.user_data["order"]["type"] in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        await update.message.reply_text(PHRASES["extra_params_prompt"])
        return EXTRA_PARAMS
    else:
        return await show_confirmation(update, context)

async def extra_params(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "отмен" in update.message.text.lower() or "❌" in update.message.text:
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
    total_eur = calc["total_eur"]
    breakdown_rub = "\n".join(calc["breakdown_rub"])
    breakdown_eur = "\n".join(calc["breakdown_eur"])

    extra_count_line = ""
    if order.get("type") in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
        extra_count_line = f"Количество заданий / Quantity: {order['extra_count']}\n"

    summary_text = PHRASES["confirmation_summary"].format(
        type=order['type'],
        explain="Да" if order.get('explain') else "Нет",
        days=order['days'],
        extra_count_line=extra_count_line,
        breakdown_rub=breakdown_rub,
        breakdown_eur=breakdown_eur,
        total_rub=total_rub,
        total_eur=total_eur
    )

    buttons = [
        [InlineKeyboardButton(PHRASES["confirm_button"], callback_data="confirm_pay")],
        [InlineKeyboardButton(PHRASES["cancel_button"], callback_data="cancel")],
    ]
    
    await update.message.reply_html(
        summary_text, 
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    
    return CONFIRM_ORDER

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        context.user_data.clear()
        await query.edit_message_text(PHRASES["cancel_order"])
        return ConversationHandler.END

    order = context.user_data.get("order", {})
    calc = calculate_price(order)
    total_rub = calc["total_rub"]
    total_eur = calc["total_eur"]
    
    # НЕ уведомляем админа на этом этапе
    
    provider_token = PAYMENTS_PROVIDER_TOKEN.strip()
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

    payment_text = PHRASES["payment_prompt"].format(
        total_rub=total_rub,
        total_eur=total_eur
    )
    await query.edit_message_text(payment_text, parse_mode="HTML")
    return WAITING_FOR_RECEIPT

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка успешной оплаты через Telegram Payments"""
    user = update.effective_user
    order = context.user_data.get("order", {})
    calc = calculate_price(order)
    
    # ОТПРАВЛЯЕМ админу ВСЮ информацию ОДНИМ сообщением
    await send_complete_notification_to_admin(context, user, order, calc, payment_method="telegram_payments")

    keyboard = [[KeyboardButton("/start")]]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    
    await update.message.reply_text(
        PHRASES["successful_payment"], 
        reply_markup=reply_markup, 
        parse_mode="HTML"
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def waiting_for_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка скриншота чека для ручной оплаты"""
    user = update.effective_user
    
    if update.message.photo or update.message.document:
        # Сохраняем информацию о чеке
        if update.message.photo:
            receipt_file_id = update.message.photo[-1].file_id
            receipt_type = "photo"
        else:
            receipt_file_id = update.message.document.file_id
            receipt_type = "document"
        
        # Сохраняем в user_data
        context.user_data["order"]["receipt"] = {
            "type": receipt_type,
            "file_id": receipt_file_id,
            "caption": f"📸 Чек от {user.full_name} (@{user.username} | id={user.id})"
        }
        
        order = context.user_data.get("order", {})
        if order:
            calc = calculate_price(order)
            # ОТПРАВЛЯЕМ админу ВСЮ информацию ОДНИМ сообщением
            await send_complete_notification_to_admin(context, user, order, calc, payment_method="manual")

        keyboard = [[KeyboardButton("/start")]]
        reply_markup = ReplyKeyboardMarkup(
            keyboard, 
            resize_keyboard=True, 
            one_time_keyboard=True
        )
        
        await update.message.reply_text(
            PHRASES["receipt_received"], 
            reply_markup=reply_markup, 
            parse_mode="HTML"
        )

        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(PHRASES["waiting_for_receipt_prompt"])
    return WAITING_FOR_RECEIPT

async def send_complete_notification_to_admin(context, user, order, calc, payment_method="manual"):
    """Отправка полной информации администратору одним сообщением"""
    try:
        # 1. Сначала отправляем задание (если есть файл/фото)
        assignment = order.get("assignment", {})
        if assignment:
            if assignment.get("type") == "document":
                await context.bot.send_document(
                    ADMIN_CHAT_ID, 
                    document=assignment["file_id"], 
                    caption=assignment["full_caption"][:1024]
                )
            elif assignment.get("type") == "photo":
                await context.bot.send_photo(
                    ADMIN_CHAT_ID, 
                    photo=assignment["file_id"], 
                    caption=assignment["full_caption"][:1024]
                )
            elif assignment.get("type") == "text":
                await context.bot.send_message(
                    ADMIN_CHAT_ID, 
                    text=assignment["full_caption"]
                )
        
        # 2. Отправляем чек (если есть)
        receipt = order.get("receipt", {})
        if receipt:
            if receipt.get("type") == "photo":
                await context.bot.send_photo(
                    ADMIN_CHAT_ID,
                    photo=receipt["file_id"],
                    caption=receipt["caption"]
                )
            elif receipt.get("type") == "document":
                await context.bot.send_document(
                    ADMIN_CHAT_ID,
                    document=receipt["file_id"],
                    caption=receipt["caption"]
                )
        
        # 3. Отправляем детали заказа одним сообщением
        lines = [
            "=" * 40,
            "🎉 <b>НОВЫЙ ОПЛАЧЕННЫЙ ЗАКАЗ</b> 🎉",
            "=" * 40,
            "",
            "<b>👤 Клиент:</b>",
            f"• Имя: {user.full_name}",
            f"• Username: @{user.username}" if user.username else "• Username: не указан",
            f"• ID: {user.id}",
            "",
            "<b>📋 Детали заказа:</b>",
            f"• Тип: {order.get('type')}",
            f"• Объяснения: {'ДА ✅' if order.get('explain') else 'НЕТ ❌'}",
            f"• Срок: {order.get('days')} дней",
        ]
        
        if order.get("type") in ("Задание", "Лабораторная/Контрольная", "Экзаменационный вопрос"):
            lines.append(f"• Количество заданий: {order.get('extra_count')}")
        
        lines.extend([
            "",
            "<b>💰 Стоимость:</b>",
            "<i>Рубли:</i>"
        ])
        
        # Добавляем детализацию в рублях
        for line in calc["breakdown_rub"]:
            lines.append(f"  {line}")
        
        lines.extend([
            f"  <b>Итого: {calc['total_rub']}₽</b>",
            "",
            "<i>Евро:</i>"
        ])
        
        # Добавляем детализацию в евро
        for line in calc["breakdown_eur"]:
            lines.append(f"  {line}")
        
        lines.extend([
            f"  <b>Итого: {calc['total_eur']}€</b>",
            "",
            "<b>💳 Способ оплаты:</b>",
            f"• {'Telegram Payments' if payment_method == 'telegram_payments' else 'Ручной перевод'}",
            "• Статус: ✅ ОПЛАЧЕНО",
            "",
            "=" * 40,
            "🕐 Время получения: " + time.strftime("%d.%m.%Y %H:%M:%S"),
            "=" * 40,
        ])
        
        text = "\n".join(lines)
        
        # Создаем кнопку для связи с клиентом
        keyboard = []
        if user.username:
            keyboard.append([
                InlineKeyboardButton(
                    "💬 Написать клиенту", 
                    url=f"https://t.me/{user.username}"
                )
            ])
        
        # Отправляем общее сообщение
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
        
        logger.info(f"✅ Полное уведомление отправлено администратору от {user.full_name}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

# ========== ЗАПУСК ==========
def main() -> None:
    """Главная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("ЗАПУСК ТЕЛЕГРАМ БОТА")
    logger.info(f"Токен: {'***' + TOKEN[-4:] if TOKEN else 'НЕ УСТАНОВЛЕН'}")
    logger.info(f"Admin ID: {ADMIN_CHAT_ID}")
    logger.info("=" * 50)

    if not TOKEN:
        logger.error("❌ Токен бота не установлен!")
        logger.error("Добавьте переменную окружения TG_BOT_TOKEN в Bothost")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
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
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        allow_reentry=True,
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_error_handler(error_handler)

    # Проверяем, работает ли на Bothost
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    if WEBHOOK_URL and "bothost" in WEBHOOK_URL:
        port = int(os.getenv("PORT", 8080))
        logger.info(f"Запуск в режиме WEBHOOK для Bothost: {WEBHOOK_URL}")
        
        try:
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path="/webhook",
                webhook_url=WEBHOOK_URL,
                drop_pending_updates=True,
            )
        except Exception as e:
            logger.error(f"Ошибка при запуске webhook: {e}")
            logger.info("Пробую запустить polling...")
            app.run_polling(drop_pending_updates=True)
    else:
        logger.info("Запуск в режиме POLLING")
        app.run_polling(
            drop_pending_updates=True,
            close_loop=False
        )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        time.sleep(5)

