import locale
# Пробуем установить локаль, игнорируем, если нет
try:
    locale.setlocale(locale.LC_ALL, "C.UTF-8")
except locale.Error:
    pass

import requests
import random
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
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

# === НАСТРОЙКИ (БЕРЕМ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ) ===
# Здесь мы говорим боту: "Ищи эти данные в настройках Render"
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# --- НАЧАЛО: ФЭЙКОВЫЙ СЕРВЕР ДЛЯ RENDER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

def start_fake_server():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()
# --- КОНЕЦ: ФЭЙКОВЫЙ СЕРВЕР ---

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
    await update.message.reply_text("👋 Привет! Выбери действие:", reply_markup=get_main_keyboard
