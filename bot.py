import os
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- Configuration ---

# IMPORTANT: Replace with your actual bot token from BotFather
BOT_TOKEN = "8291087862:AAHrKcGMhyuiGEPCuiQnrH3J5Ghsn-7lF8Q"

# The target channel username or ID where accepted messages will be posted.
CHANNEL_CHAT_ID = "@modery_85"

# Webhook configuration for Render
PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL") # Render automatically provides this

# --- Admin Configuration (Using a separate JSON file for flexibility) ---
# This file will store the mapping: {"@username": 1234567890}
ADMIN_CONFIG_FILE = "admin_config.json"

def load_admin_ids():
    """Loads admin IDs from the configuration file."""
    try:
        with open(ADMIN_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Filter out None values (for users who haven't started the bot yet)
            return {username: user_id for username, user_id in config.items() if user_id is not None}
    except FileNotFoundError:
        logger.error(f"Admin config file not found: {ADMIN_CONFIG_FILE}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {ADMIN_CONFIG_FILE}")
        return {}

def save_admin_id(username, user_id):
    """Saves a new admin ID to the configuration file."""
    try:
        with open(ADMIN_CONFIG_FILE, 'r+') as f:
            config = json.load(f)
            config[username] = user_id
            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
    except FileNotFoundError:
        # If file doesn't exist, create it with the new user
        with open(ADMIN_CONFIG_FILE, 'w') as f:
            json.dump({username: user_id}, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving admin ID for {username}: {e}")

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and registers the user's ID if they are a configured admin."""
    user = update.effective_user
    
    # Check if the user is a configured admin (by username)
    # NOTE: This requires the admin to have a public username set.
    if user.username and f"@{user.username}" in context.application.bot_data.get("admin_usernames", []):
        # Save the ID for future use
        save_admin_id(f"@{user.username}", user.id)
        logger.info(f"Registered admin ID for @{user.username}: {user.id}")
        
    await update.message.reply_text(
        "Привет! Отправь мне сообщение, которое ты хочешь предложить для публикации в канале."
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forwards the user's message to all registered admins for approval."""
    # Filter to ensure it's a private message
    if update.message.chat.type != "private":
        return

    user_message = update.message
    user_id = user_message.chat_id
    
    # Get the text content. Handle different message types (text, photo caption, etc.)
    if user_message.text:
        message_text = user_message.text
    elif user_message.caption:
        message_text = user_message.caption
    else:
        message_text = "Сообщение содержит медиафайл без подписи."
        
    # Generate a unique ID for this submission
    submission_id = str(user_message.message_id) + "_" + str(user_id)
    
    # Store the full message object (or relevant parts) in a temporary storage
    context.application.bot_data[submission_id] = {
        "user_id": user_id,
        "text": message_text,
        "message_id": user_message.message_id,
        "chat_id": user_message.chat_id,
        "is_processed": False,
        "full_message": user_message.to_dict()
    }

    # Create the inline keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"accept|{submission_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{submission_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Prepare the message to be sent to admins
    admin_message_text = (
        f"**НОВАЯ ПРЕДЛОЖКА**\n"
        f"От пользователя: `{user_id}`\n"
        f"Текст:\n---\n{message_text}\n---"
    )

    admin_ids = list(context.application.bot_data.get("admin_ids", {}).values())
    sent_count = 0
    failed_admins = []
    
    # Send the message to all registered admin IDs
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Could not send message to admin {admin_id}: {e}")
            failed_admins.append(str(admin_id))

    # --- DIAGNOSTIC ADDITION ---
    # The creator's ID is the first one in the config file.
    creator_id = next(iter(admin_ids), None)
    
    if sent_count == 0 and user_id != creator_id and creator_id is not None:
        diagnostic_message = (
            "⚠️ **ДИАГНОСТИКА: СБОЙ ОТПРАВКИ** ⚠️\n\n"
            "Бот не смог отправить сообщение для утверждения ни одному администратору.\n"
            f"Неудачные ID: {', '.join(failed_admins)}\n"
            "Наиболее вероятная причина: **Неверный ID** или администратор **не написал боту /start**.\n"
            "Пожалуйста, проверьте ID администраторов."
        )
        try:
            await context.bot.send_message(
                chat_id=creator_id,
                text=diagnostic_message,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Could not send diagnostic message to creator {creator_id}: {e}")
    # --- END DIAGNOSTIC ADDITION ---

    # Inform the user that their message has been sent for review
    await user_message.reply_text(
        "Твоё сообщение отправлено на рассмотрение администраторам. Ожидай ответа."
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the admin's button press (Accept/Reject)."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    admin_ids = list(context.application.bot_data.get("admin_ids", {}).values())
    
    # Check if the user is an authorized admin
    admin_id = query.from_user.id
    if admin_id not in admin_ids:
        await query.edit_message_text("❌ У вас нет прав для выполнения этого действия.")
        return

    # Parse the callback data: "ACTION|SUBMISSION_ID"
    action, submission_id = query.data.split("|")

    # Retrieve the submission data
    submission_data = context.application.bot_data.get(submission_id)
    
    if not submission_data:
        await query.edit_message_text("❌ Ошибка: Данные предложения не найдены.")
        return

    # Check if the submission has already been processed
    if submission_data.get("is_processed"):
        await query.edit_message_text(
            f"⚠️ Это предложение уже было обработано {submission_data.get('processed_by_name', 'другим администратором')} ({submission_data.get('processed_action', 'неизвестно')})."
        )
        return

    # Mark as processed
    submission_data["is_processed"] = True
    submission_data["processed_by_id"] = admin_id
    submission_data["processed_by_name"] = query.from_user.full_name
    submission_data["processed_action"] = "принято" if action == "accept" else "отклонено"
    context.application.bot_data[submission_id] = submission_data # Update the storage

    original_user_id = submission_data["user_id"]
    
    # --- Process Action ---
    if action == "accept":
        try:
            # 1. Post the message to the channel
            await context.bot.send_message(
                chat_id=CHANNEL_CHAT_ID,
                text=submission_data["text"]
            )
            
            # 2. Notify the original user
            await context.bot.send_message(
                chat_id=original_user_id,
                text="✅ Твоё предложение было **принято** и опубликовано в канале!"
            )
            
            # 3. Update the admin's message
            await query.edit_message_text(
                f"✅ **ПРИНЯТО**\n"
                f"Опубликовано в канале: `{CHANNEL_CHAT_ID}`\n"
                f"Администратор: {query.from_user.full_name} (`{admin_id}`)"
            )

        except Exception as e:
            logger.error(f"Error during acceptance process: {e}")
            await query.edit_message_text(f"❌ Ошибка при публикации в канал: {e}")
            # Revert processed status if posting failed
            submission_data["is_processed"] = False
            context.application.bot_data[submission_id] = submission_data
            await context.bot.send_message(
                chat_id=original_user_id,
                text="❌ Произошла ошибка при публикации твоего предложения. Попробуй позже или свяжись с администратором."
            )

    elif action == "reject":
        # 1. Notify the original user
        await context.bot.send_message(
            chat_id=original_user_id,
            text="❌ Твоё предложение было **отклонено** администратором."
        )
        
        # 2. Update the admin's message
        await query.edit_message_text(
            f"❌ **ОТКЛОНЕНО**\n"
            f"Администратор: {query.from_user.full_name} (`{admin_id}`)"
        )

# --- Webhook Setup ---

# Initialize FastAPI app
app = FastAPI()

# Initialize Telegram Application
application = Application.builder().token(BOT_TOKEN).build()

# Add handlers to the application
application.add_handler(CommandHandler("start", start_command))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message))
application.add_handler(CallbackQueryHandler(handle_callback_query))

@app.on_event("startup")
async def on_startup():
    """Set the webhook URL on startup and load admin config."""
    # Load admin config
    admin_config = load_admin_ids()
    application.bot_data["admin_ids"] = admin_config
    application.bot_data["admin_usernames"] = list(admin_config.keys())
    
    if WEBHOOK_URL:
        await application.bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")
    else:
        logger.error("RENDER_EXTERNAL_URL environment variable not set. Bot will not work.")

@app.on_event("shutdown")
async def on_shutdown():
    """Remove the webhook on shutdown."""
    await application.bot.delete_webhook()
    logger.info("Webhook deleted.")

@app.post("/")
async def telegram_webhook(update: dict):
    """Handle incoming Telegram updates."""
    await application.update_queue.put(Update.de_json(update, application.bot))
    return {"message": "OK"}

def main() -> None:
    """Start the bot using uvicorn to serve the FastAPI app."""
    # The Application must be run in a separate thread/process for the webhook to work
    application.start()
    
    # We run the FastAPI app with uvicorn, binding to the port provided by the environment
    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("!!! WARNING: Please replace 'YOUR_BOT_TOKEN_HERE' in bot.py with your actual bot token.")
    elif not WEBHOOK_URL:
        print("!!! WARNING: RENDER_EXTERNAL_URL environment variable is not set. This is expected during local testing.")
    else:
        main()
