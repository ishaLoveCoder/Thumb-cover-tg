import logging
import os
import re
import requests
from dotenv import load_dotenv
from typing import Optional   # ← Yeh line add karo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("thumbnail_bot_ptb.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN not found in .env")
    exit(1)

# URL pattern for image detection
URL_PATTERN = re.compile(
    r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+\.(?:jpg|jpeg|png|webp|bmp)(?:\?.*)?',
    re.IGNORECASE
)

# Conversation states
SETTINGS_MENU = range(1)

# Global user data (production mein database use karo)
user_data = {}  # user_id → {'mode': 'manual'/'auto', 'thumb_file_id': str, 'posters': list, 'current_idx': 0, 'videos': list}

# --- Helper Functions ---

def extract_title_year(caption: str):
    match = re.search(r'(.+?)\s*\((\d{4})\)', caption, re.IGNORECASE)
    if match:
        return match.group(1).strip(), int(match.group(2))
    words = caption.split()
    title = " ".join(words[:6]).strip()
    return title, None

def fetch_posters(title: str, year: Optional[int] = None) -> list:
    query = f"{title}+{year}" if year else title
    query = query.replace(" ", "+").replace(":", "").replace("(", "").replace(")", "")
    url = f"https://jisshuapis.vercel.app/api.php?query={query}"
    
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            logger.error(f"API Error: HTTP {r.status_code}")
            return []
        data = r.json()
        
        posters = []
        for key in ["jisshu-2", "jisshu-3", "jisshu-4"]:
            if key in data and isinstance(data[key], list):
                posters.extend(data[key])
        
        posters = list(dict.fromkeys(posters))[:10]
        return posters
    except Exception as e:
        logger.error(f"Poster fetch error: {e}")
        return []

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    welcome_text = """
🤖 <b>Thumbnail Cover Changer Bot</b>

Modes:
• <b>Manual</b>: Thumbnail bhejo → Video bhejo
• <b>Auto</b>: Sirf video bhejo → Main poster dhund ke laga dunga

<b>Commands:</b>
/start - Yeh message
/thumb - Current thumbnail dekho
/clear - Thumbnail hatao
/settings - Caption style change karo
    """
    keyboard = [["Manual Mode", "Auto Mode"]]
    reply_markup = types.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=reply_markup)

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.lower()
    
    mode = "manual" if "manual" in text else "auto"
    msg = "Manual mode ON! Thumbnail bhejo (photo/URL), fir video bhejo." if mode == "manual" else "Auto mode ON! Bas video bhejo – main poster dhund ke laga dunga."
    
    user_data[user_id] = {
        'mode': mode,
        'thumb_file_id': None,
        'posters': [],
        'current_idx': 0,
        'videos': []
    }
    await update.message.reply_text(msg)

# Save photo as thumbnail (Manual mode)
async def save_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data or user_data[user_id]['mode'] != "manual":
        return
    
    file_id = update.message.photo[-1].file_id
    user_data[user_id]['thumb_file_id'] = file_id
    await update.message.reply_text("✅ Thumbnail saved! Ab video bhejo.")

# Handle URL thumbnails (Manual mode)
async def handle_url_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data or user_data[user_id]['mode'] != "manual":
        return
    
    url = update.message.text
    if not URL_PATTERN.match(url):
        return
    
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        # Send to Telegram to get file_id
        msg = await update.message.reply_photo(photo=r.content)
        user_data[user_id]['thumb_file_id'] = msg.photo[-1].file_id
        await update.message.reply_text("✅ Thumbnail from URL saved! Ab video bhejo.")
    except Exception as e:
        await update.message.reply_text(f"URL se thumbnail nahi laga paya: {str(e)}")

# Video handler
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        await update.message.reply_text("Pehle /start karo aur mode select karo!")
        return

    video = update.message.video
    caption = update.message.caption or ""
    
    mode = user_data[user_id]['mode']
    
    if mode == "manual":
        thumb_file_id = user_data[user_id].get('thumb_file_id')
        if not thumb_file_id:
            await update.message.reply_text("Pehle thumbnail bhejo!")
            return
        
        await context.bot.send_video(
            chat_id=update.effective_chat.id,
            video=video.file_id,
            cover=thumb_file_id,
            caption=caption,
            supports_streaming=True
        )
        await update.message.delete()
        return

    # Auto mode
    title, year = extract_title_year(caption)
    if not title:
        await update.message.reply_text("Caption se title nahi mila. Manual mode use karo.")
        return

    posters = fetch_posters(title, year)
    if not posters:
        await update.message.reply_text(f"'{title}' ke liye poster nahi mila")
        return

    user_data[user_id]['posters'] = posters
    user_data[user_id]['current_idx'] = 0
    user_data[user_id]['videos'] = user_data[user_id].get('videos', []) + [video.file_id]

    await show_poster_selection(update.effective_chat.id, user_id)

# Poster selection with buttons
async def show_poster_selection(chat_id: int, user_id: int):
    data = user_data.get(user_id)
    if not data or not data.get('posters'):
        return
    
    idx = data['current_idx']
    url = data['posters'][idx]
    
    markup = InlineKeyboardMarkup(row_width=3)
    if idx > 0:
        markup.add(InlineKeyboardButton("<< Prev", callback_data=f"prev_{user_id}"))
    markup.add(InlineKeyboardButton(f"{idx+1}/{len(data['posters'])}", callback_data="dummy"))
    if idx < len(data['posters'])-1:
        markup.add(InlineKeyboardButton("Next >>", callback_data=f"next_{user_id}"))
    
    markup.add(InlineKeyboardButton("✅ Choose & Apply to All", callback_data=f"apply_{user_id}_{idx}"))
    
    await bot.send_photo(
        chat_id=chat_id,
        photo=url,
        caption=f"Poster {idx+1}/{len(data['posters'])}\n\nChoose karo ya next/prev karo",
        reply_markup=markup
    )

# Callback handler
async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith(('prev_', 'next_', 'apply_')):
        return
    
    parts = data.split('_')
    action = parts[0]
    user_id = int(parts[1])
    
    if query.from_user.id != user_id:
        await query.answer("Yeh button aapka nahi hai!")
        return
    
    if action == "prev":
        user_data[user_id]['current_idx'] = max(0, user_data[user_id]['current_idx'] - 1)
    elif action == "next":
        user_data[user_id]['current_idx'] = min(len(user_data[user_id]['posters']) - 1, user_data[user_id]['current_idx'] + 1)
    
    elif action == "apply":
        idx = int(parts[2])
        poster_url = user_data[user_id]['posters'][idx]
        
        try:
            r = requests.get(poster_url, timeout=10)
            r.raise_for_status()
            poster_bytes = r.content
        except:
            await query.answer("Poster download fail hua")
            return
        
        for video_file_id in user_data[user_id].get('videos', []):
            await bot.send_video(
                query.message.chat.id,
                video=video_file_id,
                cover=poster_bytes,
                caption="Auto Poster Applied!"
            )
        
        await query.answer("Applied to all videos!")
        user_data[user_id]['videos'] = []
        await query.message.delete()
        return
    
    await query.message.delete()
    await show_poster_selection(query.message.chat.id, user_id)

# Cancel settings
async def cancel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Settings menu closed.")
    return ConversationHandler.END

def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    
    # Mode selection (using text messages)
    application.add_handler(MessageHandler(filters.Regex("^(Manual Mode|Auto Mode)$"), set_mode))
    
    # Message Handlers
    application.add_handler(MessageHandler(filters.PHOTO, save_thumb))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_thumb))
    
    # Callback handler for buttons
    application.add_handler(CallbackQueryHandler(callback_query))

    logger.info("Starting Thumbnail Cover Changer Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
