import locale
try:
    locale.setlocale(locale.LC_ALL, "C.UTF-8")
except locale.Error:
    pass

import requests
import random
import os
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode

# === НАСТРОЙКИ ===
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# ВАЖНО: Эту переменную нужно будет добавить в настройки Render (см. инструкцию ниже)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") 

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# --- ЛОГИКА БОТА ОСТАЛАСЬ ПРЕЖНЕЙ ---

last_sent_reel = {}
TEXT_INPUT = range(1)

def split_text(text, max_length=1800):
    parts = []
    while len(text) > max_length:
        split_pos = text.rfind(" ", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    parts.append(text)
    return parts

def get_ready_reels():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {"filter": {"property": "Статус", "select": {"equals": "Готов"}}}
    res = requests.post(url, headers=headers, json=payload)
    res.raise_for_status()
    data = res.json()
    if not data["results"]:
        return None
    return random.choice(data["results"])

def extract_reel_info(page):
    props = page["properties"]
    video = props["Видео"]["title"][0]["text"]["content"] if props["Видео"]["title"] else ""
    hook = "".join([part["text"]["content"] for part in props["Хук"]["rich_text"]])
    desc = "".join([part["text"]["content"] for part in props["Описание"]["rich_text"]])
    return video, hook, desc, page["id"]

def update_status(page_id, status="Залит"):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": {"Статус": {"select": {"name": status}}}}
    res = requests.patch(url, headers=headers, json=payload)
    res.raise_for_status()

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Получить рилс", callback_data="get_reel")],
        [InlineKeyboardButton("📊 Счётчик готовых", callback_data="score")],
        [InlineKeyboardButton("➕ Добавить рилс", callback_data="start_add")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_after_reel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Ещё рилс", callback_data="get_reel")],
        [InlineKeyboardButton("↩️ Вернуть статус", callback_data="undo")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_score_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Получить рилс", callback_data="get_reel")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_keyboard():
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_add")]]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Выбери действие:", reply_markup=get_main_keyboard())

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👋 Главное меню:", reply_markup=get_main_keyboard())

async def send_reel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = get_ready_reels()
    except Exception as e:
        await query.edit_message_text(f"⚠️ Ошибка Notion: {e}\n(Проверь, добавлен ли бот в таблицу через Connections)", reply_markup=get_main_keyboard())
        return

    if not page:
        await query.edit_message_text("❌ Нет доступных Reels со статусом 'Готов'.", reply_markup=get_main_keyboard())
        return
    video, hook, desc, page_id = extract_reel_info(page)
    try:
        update_status(page_id, "Залит")
    except Exception as e:
        await query.edit_message_text(f"⚠️ Ошибка обновления статуса: {e}", reply_markup=get_main_keyboard())
        return
    if not hook.strip():
        await query.edit_message_text(f"⚠️ Запись {page_id[:8]} без хука, пропускаем.", reply_markup=get_after_reel_keyboard())
        return
    uid = update.effective_user.id
    last_sent_reel[uid] = {"hook": hook, "desc": desc, "page_id": page_id}
    await context.bot.send_message(chat_id=query.message.chat_id, text="━━━━━━━━━━━━━━━\n📤 **РИЛС**\n━━━━━━━━━━━━━━━", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_message(chat_id=query.message.chat_id, text=f"`{hook}`", parse_mode=ParseMode.MARKDOWN)
    if desc.strip():
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"`{desc}`", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Рилс отправлен. Что дальше?", reply_markup=get_after_reel_keyboard())

async def send_reel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        page = get_ready_reels()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка Notion: {e}", reply_markup=get_main_keyboard())
        return
        
    if not page:
        await update.message.reply_text("❌ Нет доступных Reels со статусом 'Готов'.", reply_markup=get_main_keyboard())
        return
    video, hook, desc, page_id = extract_reel_info(page)
    try:
        update_status(page_id, "Залит")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка обновления статуса: {e}", reply_markup=get_main_keyboard())
        return
    if not hook.strip():
        await update.message.reply_text(f"⚠️ Запись {page_id[:8]} без хука, пропускаем.", reply_markup=get_after_reel_keyboard())
        return
    uid = update.effective_user.id
    last_sent_reel[uid] = {"hook": hook, "desc": desc, "page_id": page_id}
    await update.message.reply_text("━━━━━━━━━━━━━━━\n📤 **РИЛС**\n━━━━━━━━━━━━━━━", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(f"`{hook}`", parse_mode=ParseMode.MARKDOWN)
    if desc.strip():
        await update.message.reply_text(f"`{desc}`", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text("✅ Рилс отправлен. Что дальше?", reply_markup=get_after_reel_keyboard())

async def get_score_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        payload = {"filter": {"property": "Статус", "select": {"equals": "Готов"}}}
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        data = res.json()
        count = len(data["results"])
        await query.edit_message_text(f"📊 Сейчас {count} Reels со статусом 'Готов'.", reply_markup=get_score_keyboard())
    except Exception as e:
        await query.edit_message_text(f"⚠️ Ошибка Notion: {e}", reply_markup=get_main_keyboard())

async def get_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        payload = {"filter": {"property": "Статус", "select": {"equals": "Готов"}}}
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        data = res.json()
        count = len(data["results"])
        await update.message.reply_text(f"📊 Сейчас {count} Reels со статусом 'Готов'.", reply_markup=get_score_keyboard())
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка Notion: {e}", reply_markup=get_main_keyboard())

async def undo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    if uid not in last_sent_reel or "page_id" not in last_sent_reel[uid]:
        await query.edit_message_text("❌ Нечего откатывать.", reply_markup=get_main_keyboard())
        return
    page_id = last_sent_reel[uid]["page_id"]
    try:
        update_status(page_id, "Готов")
        await query.edit_message_text("✅ Статус возвращён в 'Готов'.", reply_markup=get_main_keyboard())
    except Exception as e:
        await query.edit_message_text(f"⚠️ Ошибка: {e}", reply_markup=get_main_keyboard())

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in last_sent_reel or "page_id" not in last_sent_reel[uid]:
        await update.message.reply_text("❌ Нечего откатывать.", reply_markup=get_main_keyboard())
        return
    page_id = last_sent_reel[uid]["page_id"]
    try:
        update_status(page_id, "Готов")
        await update.message.reply_text("✅ Статус возвращён в 'Готов'.", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {e}", reply_markup=get_main_keyboard())

def add_to_notion(hook, description, video):
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Видео": {"title": [{"text": {"content": str(video)}}]},
            "Хук": {"rich_text": [{"text": {"content": part}} for part in split_text(str(hook))]},
            "Описание": {"rich_text": [{"text": {"content": part}} for part in split_text(str(description))]},
            "Статус": {"select": {"name": "Готов"}}
        }
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()

async def start_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 Введи хук и описание в одном сообщении.\n\nПервый абзац — хук, остальное — описание.\nРазделяй двойным переносом строки (Enter два раза).", reply_markup=get_cancel_keyboard())
    return TEXT_INPUT

async def start_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введи хук и описание в одном сообщении.\n\nПервый абзац — хук, остальное — описание.\nРазделяй двойным переносом строки (Enter два раза).", reply_markup=get_cancel_keyboard())
    return TEXT_INPUT

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    parts = message.split("\n\n", 1)
    hook = parts[0].strip() if len(parts) > 0 else ""
    description = parts[1].strip() if len(parts) > 1 else ""
    if len(hook) < 10:
        await update.message.reply_text("⚠️ Хук слишком короткий (минимум 10 символов).\nПопробуй ещё раз:", reply_markup=get_cancel_keyboard())
        return TEXT_INPUT
    try:
        add_to_notion(hook, description, "")
        await update.message.reply_text("✅ Запись добавлена в таблицу.", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при добавлении: {e}", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def cancel_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Добавление отменено.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def cancel_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Добавление отменено.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

if __name__ == '__main__':
    # === НОВАЯ СИСТЕМА ЗАПУСКА ЧЕРЕЗ WEBHOOK ===
    
    # 1. Берем адрес из переменной окружения, которую ты задашь в Render
    if not WEBHOOK_URL:
        print("ОШИБКА: Не задана переменная WEBHOOK_URL в настройках Render!")
        sys.exit(1)

    # 2. Render дает нам порт через переменную PORT
    PORT = int(os.environ.get("PORT", 10000))

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Добавляем хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", send_reel_command))
    app.add_handler(CommandHandler("score", get_score_command))
    app.add_handler(CommandHandler("undo", undo_command))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(send_reel_callback, pattern="^get_reel$"))
    app.add_handler(CallbackQueryHandler(get_score_callback, pattern="^score$"))
    app.add_handler(CallbackQueryHandler(undo_callback, pattern="^undo$"))
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", start_add_command), CallbackQueryHandler(start_add_callback, pattern="^start_add$")],
        states={TEXT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text)]},
        fallbacks=[CommandHandler("cancel", cancel_add_command), CallbackQueryHandler(cancel_add_callback, pattern="^cancel_add$")]
    )
    app.add_handler(conv_handler)

    print(f"✅ Запуск Webhook на порту {PORT}, URL: {WEBHOOK_URL}")
    
    # 3. ЗАПУСКАЕМ ВЕБХУК
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,  # Секретный путь (чтобы никто левый не слал запросы)
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )
