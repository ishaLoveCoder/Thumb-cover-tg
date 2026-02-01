import os
import re
import logging
import aiohttp
import requests
from dotenv import load_dotenv
from typing import Optional, List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ───────────────────────────
# ENV + LOGGING
# ───────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ───────────────────────────
# CONSTANTS
# ───────────────────────────
JISSHU_API = "https://jisshuapis.vercel.app/api.php?query="

IMAGE_URL_RE = re.compile(
    r"https?://.*\.(jpg|jpeg|png|webp)", re.IGNORECASE
)

# ───────────────────────────
# IN-MEMORY USER STORE
# ───────────────────────────
users = {}
# user_id → {
#   mode, thumb_file_id, posters, poster_index, pending_videos
# }

# ───────────────────────────
# HELPERS
# ───────────────────────────
def extract_title_year(caption: str):
    """
    Spring Fever (2025) S01E08 720p → Spring Fever, 2025
    """
    if not caption:
        return None, None

    caption = caption.replace(".", " ")
    m = re.search(r"(.+?)\s*\((\d{4})\)", caption)
    if m:
        return m.group(1).strip(), int(m.group(2))

    words = caption.split()
    return " ".join(words[:5]).strip(), None


async def fetch_posters(title: str, year: Optional[int]) -> List[str]:
    query = f"{title} {year}" if year else title
    query = query.replace(" ", "+")

    url = JISSHU_API + query
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=8) as r:
            if r.status != 200:
                return []
            data = await r.json()

    posters = []
    for k in ("jisshu-2", "jisshu-3", "jisshu-4"):
        posters += data.get(k, [])

    return list(dict.fromkeys(posters))[:10]


def poster_keyboard(uid: int, idx: int, total: int):
    btns = []
    if idx > 0:
        btns.append(InlineKeyboardButton("⬅ Prev", callback_data=f"prev:{uid}"))
    btns.append(InlineKeyboardButton(f"{idx+1}/{total}", callback_data="noop"))
    if idx < total - 1:
        btns.append(InlineKeyboardButton("Next ➡", callback_data=f"next:{uid}"))

    return InlineKeyboardMarkup([
        btns,
        [InlineKeyboardButton("✅ Apply to all", callback_data=f"apply:{uid}")]
    ])

# ───────────────────────────
# COMMANDS
# ───────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    users[uid] = {
        "mode": None,
        "thumb_file_id": None,
        "posters": [],
        "poster_index": 0,
        "pending_videos": [],
    }

    kb = ReplyKeyboardMarkup(
        [["Manual Mode", "Auto Mode"]],
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🤖 *Thumbnail Cover Bot*\n\n"
        "Manual → thumbnail bhejo → video bhejo\n"
        "Auto → sirf video bhejo (caption ke basis pe poster)\n",
        parse_mode="Markdown",
        reply_markup=kb
    )


async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        return

    text = update.message.text.lower()
    if "manual" in text:
        users[uid]["mode"] = "manual"
        await update.message.reply_text("✅ Manual mode ON\nThumbnail bhejo.")
    elif "auto" in text:
        users[uid]["mode"] = "auto"
        await update.message.reply_text("✅ Auto mode ON\nVideo bhejo.")

# ───────────────────────────
# MANUAL MODE
# ───────────────────────────
async def save_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if users.get(uid, {}).get("mode") != "manual":
        return

    users[uid]["thumb_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text("🖼 Thumbnail saved. Ab video bhejo.")


async def manual_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = users.get(uid)

    if not data or data["mode"] != "manual":
        return

    thumb = data.get("thumb_file_id")
    if not thumb:
        await update.message.reply_text("⚠ Pehle thumbnail bhejo.")
        return

    await context.bot.send_video(
        chat_id=update.effective_chat.id,
        video=update.message.video.file_id,
        cover=thumb,
        caption=update.message.caption or "",
        supports_streaming=True
    )

    await update.message.delete()

# ───────────────────────────
# AUTO MODE
# ───────────────────────────
async def auto_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = users.get(uid)

    if not data or data["mode"] != "auto":
        return

    title, year = extract_title_year(update.message.caption or "")
    if not title:
        await update.message.reply_text("❌ Caption me title nahi mila.")
        return

    posters = await fetch_posters(title, year)
    if not posters:
        await update.message.reply_text("❌ Poster nahi mila.")
        return

    data["posters"] = posters
    data["poster_index"] = 0
    data["pending_videos"].append(update.message.video.file_id)

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=posters[0],
        caption=f"Poster for *{title}*",
        parse_mode="Markdown",
        reply_markup=poster_keyboard(uid, 0, len(posters))
    )

# ───────────────────────────
# CALLBACKS
# ───────────────────────────
async def poster_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, uid = q.data.split(":")
    uid = int(uid)
    data = users.get(uid)

    if not data:
        return

    if action == "prev":
        data["poster_index"] -= 1
    elif action == "next":
        data["poster_index"] += 1
    elif action == "apply":
        poster_url = data["posters"][data["poster_index"]]
        img = requests.get(poster_url).content

        for vid in data["pending_videos"]:
            await context.bot.send_video(
                chat_id=q.message.chat.id,
                video=vid,
                cover=img,
                supports_streaming=True
            )

        data["pending_videos"].clear()
        await q.message.delete()
        return

    idx = data["poster_index"]
    await q.message.edit_media(
        media=q.message.photo[-1].copy(photo=data["posters"][idx]),
        reply_markup=poster_keyboard(uid, idx, len(data["posters"]))
    )

# ───────────────────────────
# MAIN
# ───────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(Manual Mode|Auto Mode)$"), set_mode))

    # MANUAL
    app.add_handler(MessageHandler(filters.PHOTO, save_thumbnail))
    app.add_handler(MessageHandler(filters.VIDEO & ~filters.CAPTION, manual_video))

    # AUTO (IMPORTANT FIX)
    app.add_handler(MessageHandler(filters.VIDEO & filters.CAPTION, auto_video))

    app.add_handler(CallbackQueryHandler(poster_callback))

    logger.info("Bot started ✅")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
