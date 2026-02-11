from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import yt_dlp
import os, shutil, asyncio, re, json
from flask import Flask
from threading import Thread

# ===== Flask =====
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot is running!"

def run():
    app_flask.run(host='0.0.0.0', port=8080)

Thread(target=run).start()

# ===== Config =====
TOKEN = "5895987032:AAGFbgibi8_nm7bVHXmsEj3r8dTo8o3R3Qk"
AUTHORIZED_USERS = {5592226317}
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_SIZE = 50 * 1024 * 1024

queue = asyncio.Queue()

DOWNLOADED_FILE = "downloaded_links.txt"
ERROR_FILE = "error_list.json"
PENDING_FILE = "pending_links.json"

downloaded_links = set(open(DOWNLOADED_FILE).read().split()) if os.path.exists(DOWNLOADED_FILE) else set()
error_list = json.load(open(ERROR_FILE)) if os.path.exists(ERROR_FILE) else {}
pending_links = json.load(open(PENDING_FILE)) if os.path.exists(PENDING_FILE) else []

def save_downloaded():
    with open(DOWNLOADED_FILE, "w") as f:
        for l in downloaded_links:
            f.write(l + "\n")

def save_errors():
    json.dump(error_list, open(ERROR_FILE, "w"), indent=2)

def save_pending():
    json.dump(pending_links, open(PENDING_FILE, "w"), indent=2)

def extract_links(text):
    return re.findall(r'(https?://[^\s]+)', text)

def get_artist(info):
    return info.get('artist') or info.get('uploader') or "Unknown Artist"

ydl_opts = {
    'format': 'bestaudio[abr<=320]/bestaudio',  # Max 320kbps
    'quiet': True,
    'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',
    'postprocessors': [
        {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
        {'key': 'FFmpegMetadata'}
    ]
}

# ===== Commands =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/error /redownload /pending /status")

async def handle_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    links = extract_links(update.message.text)

    added = 0
    for link in links:
        if link in downloaded_links or link in pending_links:
            continue
        pending_links.append(link)
        await queue.put((chat_id, link))
        added += 1

    save_pending()
    await update.message.reply_text(f"✅ {added} link(s) added to queue")

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Status\n"
        f"✅ {len(downloaded_links)}\n"
        f"❌ {len(error_list)}\n"
        f"⏳ {len(pending_links)}"
    )

async def show_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not error_list:
        return await update.message.reply_text("No error")
    await update.message.reply_text("\n".join(error_list.keys()))

async def redownload_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for link in list(error_list.keys()):
        if link not in pending_links:
            pending_links.append(link)
        await queue.put((chat_id, link))
        del error_list[link]

    save_errors()
    save_pending()
    await update.message.reply_text("🔄 Retrying error links")

async def show_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not pending_links:
        return await update.message.reply_text("No pending")
    kb = [[InlineKeyboardButton("🔄 Retry Pending", callback_data="retry_pending")]]
    await update.message.reply_text("\n".join(pending_links), reply_markup=InlineKeyboardMarkup(kb))

# ===== Worker =====
async def worker(app):
    while True:
        chat_id, url = await queue.get()
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                mp3 = ydl.prepare_filename(info).rsplit('.', 1)[0] + ".mp3"

                if os.path.exists(mp3) and os.path.getsize(mp3) <= MAX_SIZE:
                    await app.bot.send_audio(
                        chat_id=chat_id,
                        audio=open(mp3, 'rb'),
                        title=info.get('title', 'Unknown'),
                        performer=get_artist(info)
                    )
                    downloaded_links.add(url)
                    save_downloaded()
                    os.remove(mp3)

            if url in pending_links:
                pending_links.remove(url)
                save_pending()

        except Exception as e:
            error_list[url] = str(e)
            if url in pending_links:
                pending_links.remove(url)
            save_errors()
            save_pending()

        queue.task_done()

# ===== Callback =====
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "retry_pending":
        chat_id = update.effective_chat.id
        for link in pending_links:
            await queue.put((chat_id, link))
        await update.callback_query.edit_message_text("⏳ Retrying pending")

# ===== Bot =====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("error", show_errors))
app.add_handler(CommandHandler("redownload", redownload_errors))
app.add_handler(CommandHandler("pending", show_pending))
app.add_handler(CommandHandler("status", show_status))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_links))
app.add_handler(CallbackQueryHandler(callback_handler))

async def start_worker(app):
    app.create_task(worker(app))

app.post_init = start_worker
app.run_polling()