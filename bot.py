import os
import random
import string
from datetime import datetime, timedelta
from flask import Flask
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
import requests
import threading
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
SHORTNER_API = os.getenv("SHORTNER_API")
BASE_URL = os.getenv("FLASK_URL", "https://yourdomain.com")
HOW_TO_VERIFY_URL = os.getenv("HOW_TO_VERIFY_URL", "https://your-help-link.com")
LIKE_API_URL = os.getenv("LIKE_API_URL", "https://your-like-api.com/like?uid={uid}")

client = MongoClient(MONGO_URI)
db = client['likebot']
verifications = db['verifications']

flask_app = Flask(__name__)
bot = None


# === Send Like and Edit Message ===
async def send_verification_success(user_id, uid, chat_id=None, message_id=None):
    try:
        like_response = requests.get(LIKE_API_URL.format(uid=uid)).json()
        status = like_response.get("status")

        if status == 1:
            text = (
                f"✅ *Like Sent Successfully!*\n\n"
                f"👤 Player: `{like_response['PlayerNickname']}`\n"
                f"📇 UID: `{like_response['UID']}`\n"
                f"👍 Likes Before: `{like_response['LikesbeforeCommand']}`\n"
                f"👍 Likes After: `{like_response['LikesafterCommand']}`\n"
                f"🚀 Likes Given: `{like_response['LikesGivenByAPI']}`"
            )
        elif status == 2:
            text = (
                f"❌️ *Maxed Likes Reached for UID `{uid}`*\n\n"
                f"👤 Player: `{like_response['PlayerNickname']}`\n"
                f"👍 Total Likes: `{like_response['LikesafterCommand']}`"
            )
        else:
            text = "❌ Failed to send likes. Please try again later."
    except Exception as e:
        print(f"❌ Error sending like: {e}")
        text = "❌ Error during like process."

    try:
        if chat_id and message_id:
            await bot.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode='Markdown'
            )
        else:
            await bot.bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
    except Exception as e:
        print(f"❌ Error sending/editing message: {e}")


# === Verification Endpoint ===
@flask_app.route("/verify/<code>")
def verify(code):
    try:
        user = verifications.find_one({"code": code})
        if not user:
            return "❌ Invalid or expired verification link.", 400

        if datetime.utcnow() > user.get("expires_at"):
            return "⏱️ This verification link has expired. Please request a new one.", 400

        if user.get("verified"):
            return (
                "<h3 style='color:orange;'>⚠️ You have already verified.</h3>"
                f"<p>User ID: {user['user_id']}</p>"
            )

        verifications.update_one(
            {"code": code},
            {"$set": {"verified": True, "verified_at": datetime.utcnow()}}
        )

        def async_task():
            asyncio.run(
                send_verification_success(
                    user_id=user['user_id'],
                    uid=user['uid'],
                    chat_id=user.get("chat_id"),
                    message_id=user.get("message_id")
                )
            )

        threading.Thread(target=async_task).start()

        return (
            "<h2 style='color:green;'>✅ Verification successful!</h2>"
            f"<p>User ID: <b>{user['user_id']}</b><br>Now you can return to Telegram.</p>"
        )

    except Exception as e:
        print(f"🚨 Verify error: {e}")
        return "❌ Internal server error.", 500


# === /like Command ===
async def like_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ Use format: /like <region> <uid>")
        return

    uid = context.args[1]
    username = user.first_name or "User"
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    verify_url = f"{BASE_URL}/verify/{code}"

    try:
        # Always create fresh short link
        short_api = f"https://shortner.in/api?api={SHORTNER_API}&url={verify_url}"
        response = requests.get(short_api).json()
        short_link = response.get("shortenedUrl", verify_url)
    except Exception as e:
        print(f"❌ URL Shortening failed: {e}")
        short_link = verify_url

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Verify Now", url=short_link)],
        [InlineKeyboardButton("❓ How to Verify?", url=HOW_TO_VERIFY_URL)]
    ])
    msg = (
        f"🔒 *Verification Required*\n\n"
        f"Hello {username},\n\n"
        f"Please verify to get 1 free like.\n"
        f"🔗 {short_link}\n\n"
        f"⏱️ *Link expires in 10 minutes.*"
    )
    sent_msg = await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='Markdown')

    # Save verification data with 10-minute expiry
    verifications.insert_one({
        "user_id": user.id,
        "username": username,
        "uid": uid,
        "code": code,
        "verified": False,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
        "chat_id": sent_msg.chat_id,
        "message_id": sent_msg.message_id
    })


# === Run Flask + Bot ===
def run():
    global bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot = app
    app.add_handler(CommandHandler("like", like_command))

    # Start Flask server in separate thread
    threading.Thread(target=flask_app.run, kwargs={"host": "0.0.0.0", "port": 5000}).start()

    print("✅ Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    run()
