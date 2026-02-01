import logging
import os
import re
import aiohttp
import asyncio
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ───────────────── CONFIG ─────────────────

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
JISSHU_API = "https://jisshuapis.vercel.app/api.php?query="

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# user_id → state
USERS = {}

# ───────────────── HELPERS ─────────────────

def extract_title(caption: str) -> str:
    caption = caption.replace(".", " ")
    caption = re.sub(r"\(.*?\)", "", caption)
    caption = re.sub(
        r"\b(720p|1080p|2160p|web|bluray|nf|amzn|ddp|x264|x265|hevc|s\d+e\d+).*",
        "",
        caption,
        flags=re.I
    )
    return caption.strip()

async def fetch_posters(title: str) -> list:
    query = title.replace(" ", "+")
    url = JISSHU_API + query

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=6) as r:
            if r.status != 200:
                return []

            data = await r.json()
            posters = []

            for key in ["jisshu-2", "jisshu-3", "jisshu-4"]:
                posters.extend(data.get(key, []))

            return list(dict.fromkeys(posters))[:10]

# ───────────────── COMMANDS ─────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup(
        [["Manual Mode", "Auto Mode"]],
        resize_keyboard=True
    )

    USERS[update.effective_user.id] = {
        "mode": None,
        "thumb": None,
        "posters": [],
        "idx": 0,
        "videos": []
    }

    await update.message.reply_text(
        "🤖 *Thumbnail Cover Bot*\n\n"
        "Choose Mode:\n"
        "• Manual – thumbnail → video\n"
        "• Auto – video → poster auto",
        parse_mode="Markdown",
        reply_markup=kb
    )

# ───────────────── MODE SELECT ─────────────────

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.lower()

    if uid not in USERS:
        return

    if "manual" in text:
        USERS[uid]["mode"] = "manual"
        await update.message.reply_text("✅ Manual Mode ON\nSend thumbnail first.")
    elif "auto" in text:
        USERS[uid]["mode"] = "auto"
        await update.message.reply_text("✅ Auto Mode ON\nSend video directly.")

# ───────────────── MANUAL MODE ─────────────────

async def save_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if USERS.get(uid, {}).get("mode") != "manual":
        return

    USERS[uid]["thumb"] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Thumbnail saved. Now send video.")

async def manual_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = USERS.get(uid)

    if not data or data["mode"] != "manual":
        return

    if not data["thumb"]:
        await update.message.reply_text("❌ Send thumbnail first.")
        return

    await context.bot.send_video(
        chat_id=update.effective_chat.id,
        video=update.message.video.file_id,
        cover=data["thumb"],
        caption=update.message.caption
    )
    await update.message.delete()

# ───────────────── AUTO MODE ─────────────────

async def auto_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = USERS.get(uid)

    if not data or data["mode"] != "auto":
        return

    caption = update.message.caption or ""
    title = extract_title(caption)

    if not title:
        await update.message.reply_text("❌ Caption se title nahi mila.")
        return

    posters = await fetch_posters(title)
    if not posters:
        await update.message.reply_text("❌ Poster nahi mila.")
        return

    data["posters"] = posters
    data["idx"] = 0
    data["videos"].append(update.message.video.file_id)

    await show_poster(update.effective_chat.id, uid, context)

# ───────────────── POSTER UI ─────────────────

async def show_poster(chat_id: int, uid: int, context: ContextTypes.DEFAULT_TYPE):
    data = USERS[uid]
    idx = data["idx"]

    kb = []
    row = []

    if idx > 0:
        row.append(InlineKeyboardButton("⬅ Prev", callback_data=f"prev:{uid}"))
    row.append(InlineKeyboardButton(f"{idx+1}/{len(data['posters'])}", callback_data="noop"))
    if idx < len(data["posters"]) - 1:
        row.append(InlineKeyboardButton("Next ➡", callback_data=f"next:{uid}"))

    kb.append(row)
    kb.append([InlineKeyboardButton("✅ Apply to All", callback_data=f"apply:{uid}")])

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=data["posters"][idx],
        caption="Choose poster",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ───────────────── CALLBACKS ─────────────────

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, uid = q.data.split(":")
    uid = int(uid)

    if q.from_user.id != uid:
        return

    data = USERS[uid]

    if action == "prev":
        data["idx"] -= 1
    elif action == "next":
        data["idx"] += 1
    elif action == "apply":
        poster_url = data["posters"][data["idx"]]

        msg = await context.bot.send_photo(q.message.chat.id, poster_url)
        cover_id = msg.photo[-1].file_id

        for vid in data["videos"]:
            await context.bot.send_video(
                q.message.chat.id,
                vid,
                cover=cover_id,
                caption="🎬 Auto Poster Applied"
            )

        data["videos"].clear()
        await q.message.delete()
        return

    await q.message.delete()
    await show_poster(q.message.chat.id, uid, context)

# ───────────────── MAIN ─────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(Manual Mode|Auto Mode)$"), set_mode))

    app.add_handler(MessageHandler(filters.PHOTO, save_thumbnail))
    app.add_handler(MessageHandler(filters.VIDEO & filters.Caption(True), auto_video))
    app.add_handler(MessageHandler(filters.VIDEO, manual_video))

    app.add_handler(CallbackQueryHandler(callbacks))

    logger.info("Bot running…")
    app.run_polling()

if __name__ == "__main__":
    main()
