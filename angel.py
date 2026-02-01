import logging
import os
import re
import requests
import asyncio
import aiohttp
from dotenv import load_dotenv
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

# Jisshu API
JISSHU_API = "https://jisshuapis.vercel.app/api.php?query="

# Conversation states
SETTINGS_MENU = range(1)

# URL pattern for image detection
URL_PATTERN = re.compile(
    r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+\.(?:jpg|jpeg|png|webp|bmp)(?:\?.*)?',
    re.IGNORECASE
)

# User data store (global dict – production mein database use karna)
user_data = {}  # user_id → {'mode': 'manual'/'auto', 'thumb_file_id': str, 'posters': list, 'current_idx': 0, 'videos': list}

# --- Helper Functions ---

def extract_title_year(caption: str):
    """Caption se title aur year nikaalo"""
    match = re.search(r'(.+?)\s*\((\d{4})\)', caption, re.IGNORECASE)
    if match:
        return match.group(1).strip(), int(match.group(2))
    # Agar year nahi mila to pehle 5-6 words title samajh lo
    words = caption.split()
    title = " ".join(words[:6]).strip()
    return title, None

async def fetch_posters(title: str, year: int = None) -> list:
    """Jisshu API se posters dhundho"""
    query = f"{title}+{year}" if year else title
    query = query.replace(" ", "+").replace(":", "").replace("(", "").replace(")", "")
    url = f"{JISSHU_API}{query}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=5) as res:
                if res.status != 200:
                    logger.error(f"API Error: HTTP {res.status}")
                    return []
                data = await res.json()
                
                posters = []
                for key in ["jisshu-2", "jisshu-3", "jisshu-4"]:
                    if key in data and isinstance(data[key], list):
                        posters.extend(data[key])
                
                # Unique kar do aur first 10 le lo
                posters = list(dict.fromkeys(posters))[:10]
                return posters
        except Exception as e:
            logger.error(f"Poster fetch error: {e}")
            return []

async def apply_cover_and_send(chat_id: int, video_file_id: str, thumb_bytes: bytes, caption: str = ""):
    """Video pe cover apply kar ke bhejo"""
    try:
        await bot.send_video(
            chat_id=chat_id,
            video=video_file_id,
            cover=thumb_bytes,
            caption=caption,
            supports_streaming=True
        )
        logger.info(f"Video with cover sent to {chat_id}")
    except Exception as e:
        logger.error(f"Error sending video with cover: {e}")
        await bot.send_message(chat_id, f"Cover apply nahi ho paya: {str(e)}")

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    welcome_text = """
🤖 <b>Thumbnail Cover Changer Bot</b>

Modes:
• <b>Manual</b>: Thumbnail bhejo → Video bhejo
• <b>Auto</b>: Sirf video bhejo → Main poster dhund ke laga dunga (TMDB/Jisshu API se)

<b>Commands:</b>
/start - Yeh message
/thumb - Current thumbnail dekho
/clear - Thumbnail hatao
/settings - Caption style change karo
    """
    keyboard = [
        ["Manual Mode", "Auto Mode"]
    ]
    reply_markup = types.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=reply_markup)

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.lower()
    
    if "manual" in text:
        mode = "manual"
        msg = "Manual mode ON! Thumbnail bhejo (photo/URL), fir video bhejo."
    elif "auto" in text:
        mode = "auto"
        msg = "Auto mode ON! Bas video bhejo – main poster dhund ke laga dunga."
    else:
        return
    
    user_data[user_id] = {
        'mode': mode,
        'thumb_file_id': None,
        'thumb_bytes': None,
        'posters': [],
        'current_idx': 0,
        'videos': []
    }
    await update.message.reply_text(msg)

async def save_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_data or user_data[user_id]['mode'] != "manual":
        return
    
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        user_data[user_id]['thumb_file_id'] = file_id
        await update.message.reply_text("✅ Thumbnail saved! Ab video bhejo.")
        return
    
    # URL thumbnail
    url = update.message.text
    if not URL_PATTERN.match(url):
        return
    
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        user_data[user_id]['thumb_bytes'] = r.content
        await update.message.reply_text("✅ Thumbnail from URL saved! Ab video bhejo.")
    except Exception as e:
        await update.message.reply_text(f"URL se thumbnail nahi laga paya: {str(e)}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_data:
        await update.message.reply_text("Pehle /start karo aur mode select karo!")
        return

    video = update.message.video
    caption = update.message.caption or ""
    
    mode = user_data[user_id]['mode']
    
    if mode == "manual":
        thumb_file_id = user_data[user_id].get('thumb_file_id')
        thumb_bytes = user_data[user_id].get('thumb_bytes')
        
        if not thumb_file_id and not thumb_bytes:
            await update.message.reply_text("Pehle thumbnail bhejo!")
            return
        
        # Apply cover
        if thumb_file_id:
            await context.bot.send_video(
                chat_id=update.message.chat_id,
                video=video.file_id,
                cover=thumb_file_id,
                caption=caption
            )
        elif thumb_bytes:
            await context.bot.send_video(
                chat_id=update.message.chat_id,
                video=video.file_id,
                cover=thumb_bytes,
                caption=caption
            )
        await update.message.delete()  # original delete
        return

    # Auto mode
    title, year = extract_title_year(caption)
    if not title:
        await update.message.reply_text("Caption se title nahi mila. Manual mode use karo ya caption daalo.")
        return

    posters = await fetch_posters(title, year)
    if not posters:
        await update.message.reply_text(f"'{title}' ke liye poster nahi mila")
        return

    # Store posters and video
    user_data[user_id]['posters'] = posters
    user_data[user_id]['current_idx'] = 0
    user_data[user_id]['videos'] = user_data[user_id].get('videos', []) + [video.file_id]

    # Show first poster with buttons
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

# Callback for buttons
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    if not data.startswith(('prev_', 'next_', 'apply_')):
        return
    
    parts = data.split('_')
    action = parts[0]
    user_id = int(parts[1])
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Yeh button aapka nahi hai!")
        return
    
    if action == "prev":
        user_data[user_id]['current_idx'] = max(0, user_data[user_id]['current_idx'] - 1)
    elif action == "next":
        user_data[user_id]['current_idx'] = min(len(user_data[user_id]['posters']) - 1, user_data[user_id]['current_idx'] + 1)
    
    elif action == "apply":
        idx = int(parts[2])
        poster_url = user_data[user_id]['posters'][idx]
        
        # Download poster
        try:
            r = requests.get(poster_url, timeout=10)
            r.raise_for_status()
            poster_bytes = r.content
        except:
            bot.answer_callback_query(call.id, "Poster download fail hua")
            return
        
        # Apply to all queued videos
        for video_file_id in user_data[user_id].get('videos', []):
            bot.send_video(
                call.message.chat.id,
                video=video_file_id,
                cover=poster_bytes,
                caption="Auto Poster Applied!"
            )
        
        bot.answer_callback_query(call.id, "Applied to all videos!")
        user_data[user_id]['videos'] = []  # clear
        bot.delete_message(call.message.chat.id, call.message.message_id)
        return
    
    bot.delete_message(call.message.chat.id, call.message.message_id)
    asyncio.run_coroutine_threadsafe(show_poster_selection(call.message.chat.id, user_id), asyncio.get_event_loop())
    bot.answer_callback_query(call.id)

# Cell 14: Start polling (last cell)
print("Bot starting...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
