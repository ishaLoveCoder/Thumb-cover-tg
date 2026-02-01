import os
import re
import logging
import requests
import aiohttp
from dotenv import load_dotenv
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

# ================= CONFIG =================

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

JISSHU_API = "https://jisshuapis.vercel.app/api.php?query="

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ================= STORAGE =================
# user_id -> data
USERS = {}

# ================= HELPERS =================

def extract_title_year(text: str):
    """
    Examples:
    Spring Fever (2025) S01E08 720p
    Haq (2025) 720p NF WEBRip
    """
    if not text:
        return None, None

    m = re.search(r"(.+?)\s*\((\d{4})\)", text)
    if m:
        return m.group(1).strip(), int(m.group(2))

    # fallback: first 5 words
    words = re.split(r"[.\-|_ ]+", text)
    title = " ".join(words[:5])
    return title.strip(), None


async def fetch_posters(title: str, year=None):
    query = f"{title} {year}" if year else title
    query = re.sub(r"[^\w\s]", "", query).replace(" ", "+")
    url = JISSHU_API + query

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=6) as r:
                if r.status != 200:
                    return []

                data = await r.json()

        posters = []
        for k in ("jisshu-2", "jisshu-3", "jisshu-4"):
            posters.extend(data.get(k, []))

        # unique + limit
        posters = list(dict.fromkeys(posters))[:10]
        return posters

    except Exception as e:
        logger.error(f"Poster fetch error: {e}")
        return []


# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup(
        [["Manual Mode", "Auto Mode"]],
        resize_keyboard=True
    )

    USERS[update.effective_user.id] = {
        "mode": None,
        "thumb_file_id": None,
        "videos": [],
        "posters": [],
        "idx": 0,
    }

    await update.message.reply_text(
        "🤖 *Thumbnail Cover Bot*\n\n"
        "Manual → Thumbnail bhejo → Video\n"
        "Auto → Sirf video bhejo (poster auto)\n\n"
        "Mode select karo 👇",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.lower()

    if uid not in USERS:
        return

    if "manual" in text:
        USERS[uid]["mode"] = "manual"
        await update.message.reply_text("✅ Manual mode ON\nThumbnail bhejo")

    elif "auto" in text:
        USERS[uid]["mode"] = "auto"
        await update.message.reply_text("✅ Auto mode ON\nAb video bhejo")


# ================= MANUAL MODE =================

async def save_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if USERS.get(uid, {}).get("mode") != "manual":
        return

    if update.message.photo:
        USERS[uid]["thumb_file_id"] = update.message.photo[-1].file_id
        await update.message.reply_text("✅ Thumbnail saved. Ab video bhejo")


async def handle_manual_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid)

    if not user or user["mode"] != "manual":
        return

    if not user["thumb_file_id"]:
        await update.message.reply_text("⚠️ Pehle thumbnail bhejo")
        return

    await context.bot.send_video(
        chat_id=update.effective_chat.id,
        video=update.message.video.file_id,
        cover=user["thumb_file_id"],
        caption=update.message.caption or ""
    )
    await update.message.delete()


# ================= AUTO MODE =================

async def handle_auto_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = USERS.get(uid)

    if not user or user["mode"] != "auto":
        return

    caption = update.message.caption or ""
    title, year = extract_title_year(caption)

    if not title:
        await update.message.reply_text("❌ Caption se title nahi mila")
        return

    posters = await fetch_posters(title, year)
    if not posters:
        await update.message.reply_text("❌ Poster nahi mila")
        return

    user["posters"] = posters
    user["idx"] = 0
    user["videos"].append(update.message.video.file_id)

    await show_poster(update, context)


async def show_poster(update_or_query, context):
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        uid = update_or_query.effective_user.id
    else:
        chat_id = update_or_query.message.chat.id
        uid = update_or_query.from_user.id

    user = USERS[uid]
    idx = user["idx"]
    total = len(user["posters"])

    buttons = []
    if idx > 0:
        buttons.append(InlineKeyboardButton("⬅ Prev", callback_data="prev"))
    if idx < total - 1:
        buttons.append(InlineKeyboardButton("Next ➡", callback_data="next"))

    buttons2 = [
        InlineKeyboardButton("✅ Apply", callback_data="apply")
    ]

    kb = InlineKeyboardMarkup([buttons, buttons2])

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=user["posters"][idx],
        caption=f"Poster {idx+1}/{total}",
        reply_markup=kb
    )


async def poster_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = USERS.get(uid)

    if not user:
        return

    if q.data == "prev":
        user["idx"] -= 1
    elif q.data == "next":
        user["idx"] += 1
    elif q.data == "apply":
        url = user["posters"][user["idx"]]
        img = requests.get(url).content

        for vid in user["videos"]:
            await context.bot.send_video(
                chat_id=q.message.chat.id,
                video=vid,
                cover=img,
                caption="✅ Auto poster applied"
            )

        user["videos"].clear()
        await q.message.delete()
        return

    await q.message.delete()
    await show_poster(q, context)


# ================= MAIN =================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(Manual Mode|Auto Mode)$"), set_mode))

    app.add_handler(MessageHandler(filters.PHOTO, save_thumbnail))
    app.add_handler(MessageHandler(filters.VIDEO & filters.Caption(True), handle_auto_video))
    app.add_handler(MessageHandler(filters.VIDEO, handle_manual_video))

    app.add_handler(CallbackQueryHandler(poster_buttons))

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
