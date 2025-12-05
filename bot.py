import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# --- Configuration ---

# IMPORTANT: Replace with your actual bot token from BotFather
BOT_TOKEN = "8291087862:AAHrKcGMhyuiGEPCuiQnrH3J5Ghsn-7lF8Q"

# The list of Telegram User IDs (integers) who are authorized to approve/reject submissions.
# These are the IDs you provided: 8043989028 (Creator) and 5342990150 (Admin)
ADMIN_IDS = [8043989028, 5342990150]

# The target channel username or ID where accepted messages will be posted.
# If using a username (e.g., "@modery_85"), the bot must be an administrator in the channel.
# If using an ID (e.g., -1001234567890), the bot must also be an administrator.
CHANNEL_CHAT_ID = "@modery_85"

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the command /start is issued."""
    await update.message.reply_text(
        "Привет! Отправь мне сообщение, которое ты хочешь предложить для публикации в канале."
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forwards the user's message to all admins for approval."""
    user_message = update.message
    user_id = user_message.chat_id
    
    # We need to store the message text and the original user's ID for the callback.
    # We will encode this information in the callback data.
    # Format: "ACTION|USER_ID|MESSAGE_TEXT" (MESSAGE_TEXT will be truncated for safety)
    
    # Get the text content. Handle different message types (text, photo caption, etc.)
    if user_message.text:
        message_text = user_message.text
    elif user_message.caption:
        message_text = user_message.caption
    else:
        # For simplicity, we only handle text and captioned media.
        # For other media, we'll just send a generic text for approval.
        message_text = "Сообщение содержит медиафайл без подписи."
        
    # Truncate the message text for callback data (max 64 bytes)
    # We will use context.user_data to store the full message for now,
    # and only pass a unique ID in the callback data.
    
    # Generate a unique ID for this submission
    submission_id = str(user_message.message_id) + "_" + str(user_id)
    
    # Store the full message object (or relevant parts) in a temporary storage
    context.bot_data[submission_id] = {
        "user_id": user_id,
        "text": message_text,
        "message_id": user_message.message_id,
        "chat_id": user_message.chat_id,
        "is_processed": False,
        "full_message": user_message.to_dict() # Store the full message for forwarding
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

    # Send the message to all admins
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Could not send message to admin {admin_id}: {e}")

    # Inform the user that their message has been sent for review
    await user_message.reply_text(
        "Твоё сообщение отправлено на рассмотрение администраторам. Ожидай ответа."
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the admin's button press (Accept/Reject)."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    # Check if the user is an authorized admin
    admin_id = query.from_user.id
    if admin_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет прав для выполнения этого действия.")
        return

    # Parse the callback data: "ACTION|SUBMISSION_ID"
    action, submission_id = query.data.split("|")

    # Retrieve the submission data
    submission_data = context.bot_data.get(submission_id)
    
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
    context.bot_data[submission_id] = submission_data # Update the storage

    original_user_id = submission_data["user_id"]
    
    # --- Process Action ---
    if action == "accept":
        try:
            # 1. Post the message to the channel
            # We use the full_message dictionary to re-send the original content (text, photo, etc.)
            full_message = submission_data["full_message"]
            
            # The original message was sent from the user to the bot.
            # We need to re-send the content to the channel.
            
            # For simplicity and to handle various media types, we will use a simple text post for now.
            # For a more robust solution, we would need to check for photo, video, etc., and use the corresponding send_ methods.
            
            # For now, we will just post the text/caption.
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
            context.bot_data[submission_id] = submission_data
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

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start_command))

    # on non-command messages - forward to admins
    # We use filters.TEXT to only process text messages for simplicity, 
    # but a more complex filter could be used to handle media with captions.
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message))

    # on callback queries (button presses)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot started. Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Check if the token is still the placeholder
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("!!! WARNING: Please replace 'YOUR_BOT_TOKEN_HERE' in bot.py with your actual bot token.")
        print("The bot will not run until the token is updated.")
    else:
        main()

