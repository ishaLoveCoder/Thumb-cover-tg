import logging
import os
import re
import requests
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

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("thumbnail_bot_ptb.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Conversation states
SETTINGS_MENU = range(1)

# URL pattern for image detection
URL_PATTERN = re.compile(
    r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+\.(?:jpg|jpeg|png|webp|bmp)(?:\?.*)?',
    re.IGNORECASE
)

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user_id = update.message.from_user.id
    logger.info(f"Start command received from user {user_id}")
    welcome_text = """
🤖 <b>Thumbnail Cover Changer Bot</b>

I can change video thumbnails/covers! Here's how to use me:

<b>Step 1: Send me a thumbnail image (as photo or URL)</b>
<b>Step 2: Send me a video file</b>
<b>Step 3: I'll apply your thumbnail and send back the video</b>

<b>Commands:</b>
<b>/start - Show this help message</b>
<b>/thumb - View your current saved thumbnail</b>
<b>/clear - Clear your saved thumbnail</b>
<b>/settings - Configure caption styles</b>
    """
    await update.message.reply_text(welcome_text, parse_mode='HTML')
    logger.info(f"Start message sent to user {user_id}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /settings command"""
    user_id = update.message.from_user.id
    logger.info(f"Settings command received from user {user_id}")
    
    # Set default caption style to bold if not set
    if 'caption_style' not in context.user_data:
        context.user_data['caption_style'] = 'bold'
    
    # Check thumbnail status
    thumb_status = "✅ Saved" if context.user_data.get("thumb_file_id") else "❌ Not Saved"
    current_style = context.user_data.get('caption_style', 'bold')
    
    settings_text = f"""
⚙️ <b>Settings Menu</b>

👤 <b>User ID:</b> <code>{user_id}</code>
🖼️ <b>Thumbnail Status:</b> {thumb_status}
📝 <b>Current Caption Style:</b> {current_style.title()}

<b>Choose your preferred caption style:</b>
    """
    
    keyboard = [
        [InlineKeyboardButton("𝐁𝐨𝐥𝐝", callback_data="style_bold")],
        [InlineKeyboardButton("𝘐𝘵𝘢𝘭𝘪𝘤", callback_data="style_italic")],
        [InlineKeyboardButton("𝙼𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎", callback_data="style_monospace")],
        [InlineKeyboardButton("🗑️ Clear Style", callback_data="style_clear")],
        [InlineKeyboardButton("✅ Done", callback_data="style_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(settings_text, reply_markup=reply_markup, parse_mode='HTML')
    return SETTINGS_MENU

async def settings_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses in settings menu"""
    query = update.callback_query
    await query.answer()
    
    user_data = context.user_data
    user_id = query.from_user.id
    
    if query.data == "style_bold":
        user_data['caption_style'] = 'bold'
        style_text = "𝐁𝐨𝐥𝐝"
    elif query.data == "style_italic":
        user_data['caption_style'] = 'italic'
        style_text = "𝘐𝘵𝘢𝘭𝘪𝘤"
    elif query.data == "style_monospace":
        user_data['caption_style'] = 'monospace'
        style_text = "𝙼𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎"
    elif query.data == "style_clear":
        user_data['caption_style'] = 'none'
        style_text = "Normal"
    elif query.data == "style_done":
        await query.edit_message_text("✅ <b>Settings saved successfully!</b>", parse_mode='HTML')
        logger.info(f"Settings saved for user {user_id}")
        return ConversationHandler.END
    
    # Update the settings menu with new style
    thumb_status = "✅ Saved" if user_data.get("thumb_file_id") else "❌ Not Saved"
    current_style = user_data.get('caption_style', 'bold')
    
    settings_text = f"""
⚙️ <b>Settings Menu</b>

👤 <b>User ID:</b> <code>{user_id}</code>
🖼️ <b>Thumbnail Status:</b> {thumb_status}
📝 <b>Current Caption Style:</b> {current_style.title()}

✅ <b>Caption style set to: {style_text}</b>

<b>Choose your preferred caption style:</b>
    """
    
    keyboard = [
        [InlineKeyboardButton("𝐁𝐨𝐥𝐝", callback_data="style_bold")],
        [InlineKeyboardButton("𝘐𝘵𝘢𝘭𝘪𝘤", callback_data="style_italic")],
        [InlineKeyboardButton("𝙼𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎", callback_data="style_monospace")],
        [InlineKeyboardButton("🗑️ Clear Style", callback_data="style_clear")],
        [InlineKeyboardButton("✅ Done", callback_data="style_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(settings_text, reply_markup=reply_markup, parse_mode='HTML')
    logger.info(f"Caption style changed to {current_style} for user {user_id}")
    return SETTINGS_MENU

async def view_thumb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /thumb command to view current thumbnail"""
    thumb_file_id = context.user_data.get("thumb_file_id")
    if thumb_file_id:
        try:
            await update.message.reply_photo(
                thumb_file_id,
                caption="📷 <b>Your Current Thumbnail</b>\n\nSend a video to apply this thumbnail!",
                parse_mode='HTML'
            )
            logger.info("Thumbnail sent to user")
        except Exception as e:
            logger.error(f"Error sending thumbnail: {e}")
            await update.message.reply_text("❌ Error displaying thumbnail. Please set a new one.")
    else:
        await update.message.reply_text("📷 <b>No Thumbnail Saved</b>\n\nPlease send me a photo first!", parse_mode='HTML')

async def clear_thumb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command to remove saved thumbnail"""
    context.user_data.pop("thumb_file_id", None)
    await update.message.reply_text("✅ Thumbnail cleared successfully!")
    logger.info("Thumbnail cleared")

# Save photo as thumbnail
async def save_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["thumb_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Thumbnail saved! Now send a video to apply it.")

# Handle URL thumbnails
async def handle_url_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image URLs for thumbnails"""
    url = update.message.text
    user_id = update.message.from_user.id
    
    try:
        # Validate URL pattern
        if not URL_PATTERN.match(url):
            await update.message.reply_text("❌ Please send a valid image URL (jpg, jpeg, png, webp, bmp)")
            return
        
        # Download image
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            await update.message.reply_text("❌ URL does not point to a valid image")
            return
        
        # Send image to Telegram to get file_id
        message = await update.message.reply_photo(
            photo=response.content,
            caption="🖼️ Downloaded image from URL..."
        )
        
        # Get the file_id from the sent photo
        thumb_file_id = message.photo[-1].file_id
        context.user_data["thumb_file_id"] = thumb_file_id
        
        await update.message.reply_text("✅ Thumbnail saved from URL! Now send a video to apply it.")
        logger.info(f"Thumbnail saved from URL for user {user_id}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"URL download error for user {user_id}: {e}")
        await update.message.reply_text("❌ Failed to download image from URL. Please check the link and try again.")
    except Exception as e:
        logger.error(f"URL thumbnail error for user {user_id}: {e}")
        await update.message.reply_text("❌ Error processing URL. Please try a different image URL.")

# Send video with saved cover and styled caption
async def send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thumb_file_id = context.user_data.get("thumb_file_id")
    if not thumb_file_id:
        await update.message.reply_text("⚠️ Please send a thumbnail first.")
        return

    video_file_id = update.message.video.file_id
    original_caption = update.message.caption or ""
    
    # Apply caption style
    caption_style = context.user_data.get('caption_style', 'bold')
    if caption_style == 'bold' and original_caption:
        styled_caption = f"<b>{original_caption}</b>"
    elif caption_style == 'italic' and original_caption:
        styled_caption = f"<i>{original_caption}</i>"
    elif caption_style == 'monospace' and original_caption:
        styled_caption = f"<code>{original_caption}</code>"
    else:
        styled_caption = original_caption

    await context.bot.send_video(
        chat_id=update.message.chat_id,
        video=video_file_id,
        caption=styled_caption,
        cover=thumb_file_id,  # ✅ Apply custom cover
        parse_mode='HTML'
    )
    
    # Delete the original video message
    try:
        await update.message.delete()
        logger.info(f"Original video message deleted for user {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Failed to delete original video message for user {update.message.from_user.id}: {e}")

async def cancel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the settings conversation"""
    await update.message.reply_text("❌ Settings menu closed.")
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables. Exiting.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Handlers ---
    
    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("thumb", view_thumb_command))
    application.add_handler(CommandHandler("clear", clear_thumb_command))
    
    # Settings Conversation Handler
    settings_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("settings", settings_command)],
        states={
            SETTINGS_MENU: [
                CommandHandler("settings", settings_command),
                CallbackQueryHandler(settings_button_handler)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_settings)]
    )
    application.add_handler(settings_conv_handler)

    # Message Handlers
    application.add_handler(MessageHandler(filters.PHOTO, save_thumb))
    application.add_handler(MessageHandler(filters.VIDEO, send_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_thumb))

    # Start the Bot
    logger.info("Starting Thumbnail Cover Changer Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

