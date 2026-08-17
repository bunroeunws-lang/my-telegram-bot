import os
import sqlite3
import logging
from datetime import datetime
from flask import Flask
from threading import Thread

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

logging.basicConfig(level=logging.INFO)

# ==================== FLASK WEB SERVER (FOR RENDER FREE TIER) ====================
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is running 24/7 on Render Web Service!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# ==================== SETTINGS ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8879562109:AAEcmze51iluEkaLTPBjyy7qcUk7By6gQlQ")

# 👥 Multi-Admin Support
ADMIN_IDS = [8613183394]

DB_NAME = "bot_users.db"
WAITING_BROADCAST_MSG = 1

# 🤖 Auto-Reply Keywords Dictionary
KEYWORDS_REPLY = {
    ("លេខទូរស័ព្ទ", "លេខ", "លេខទំនាក់ទំនង", "ចង់បើក"): "📞 **ទំនាក់ទំនង៖** 012 345 678 / 098 765 432",
    ("contact", "phone number", "number", "phone"): "📞 **Contact:** 012 345 678 / 098 765 432"
}

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            is_replied INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            last_active TIMESTAMP,
            message_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def add_or_update_user(user_id, first_name, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute('''
            UPDATE users 
            SET first_name = ?, username = ?, last_active = ?, message_count = message_count + 1 
            WHERE user_id = ?
        ''', (first_name, username, now, user_id))
    else:
        cursor.execute('''
            INSERT INTO users (user_id, first_name, username, is_replied, is_blocked, last_active, message_count)
            VALUES (?, ?, ?, 0, 0, ?, 1)
        ''', (user_id, first_name, username, now))
        
    conn.commit()
    conn.close()

def block_user_db(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def unblock_user_db(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def is_user_blocked(user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        pass
        
    cursor.execute('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row[0]) if row and row[0] else False

def set_replied_status(user_id, status: bool):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_replied = ? WHERE user_id = ?', (1 if status else 0, user_id))
    conn.commit()
    conn.close()

def is_replied_status(user_id) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT is_replied FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row[0]) if row else False

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE is_blocked = 0')
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE datetime(last_active) >= datetime('now', '-1 day')")
    active_24h = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(message_count) FROM users')
    total_messages = cursor.fetchone()[0] or 0
    
    conn.close()
    return total_users, active_24h, total_messages

# ==================== BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_user_blocked(user.id):
        return

    add_or_update_user(user.id, user.first_name, user.username)

    if user.id in ADMIN_IDS:
        keyboard = [["📢 ផ្ញើសារប្រកាស (Broadcast)", "📊 ស្ថិតិប្រព័ន្ធ"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"👑 **សួស្តី Admin {user.first_name}!**\n\n"
            f"សូមជ្រើសរើសផ្ទាំងបញ្ជាខាងក្រោមសម្រាប់គ្រប់គ្រងប្រព័ន្ធ ឬវាយ `/admin` ដើម្បីបើក Menu Panel៖",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        inline_keyboard = [
            [
                InlineKeyboardButton("📞 ទំនាក់ទំនង", callback_data="info_contact"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)

        welcome_text = (
            f"👋 **ជម្រាបសួរ {user.first_name}!**\n\n"
            f"សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទំនាក់ទំនងរបស់យើងខ្ញុំ! 🤖\n\n"
        )

        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

# ADMIN CONTROL PANEL
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    keyboard = [
        [InlineKeyboardButton("📦 ទាញយក Database (Backup)", callback_data="download_backup")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚙️ **Admin Control Panel**\nសូមជ្រើសរើសមុខងារខាងក្រោម៖",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def inline_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if is_user_blocked(query.from_user.id):
        return

    await query.answer()

    if query.data == "info_contact":
        text = "📞 **ព័ត៌មានទំនាក់ទំនង៖**\n• ទូរស័ព្ទ៖ 012 345 678 / 098 765 432\n• Telegram: @admin"
    else:
        return

    await query.message.reply_text(text, parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if is_user_blocked(user_id):
        return

    await query.answer()

    # 1. Handle Inline Info Buttons
    if query.data.startswith("info_"):
        if query.data == "info_contact":
            text = "📞 **ព័ត៌មានទំនាក់ទំនង៖**\n• ទូរស័ព្ទ៖ 012 345 678 / 098 765 432\n• Telegram: @admin"
        else:
            return
        await query.message.reply_text(text, parse_mode="Markdown")

    # 2. Handle Block User via Inline Button
    elif query.data.startswith("block_"):
        if user_id not in ADMIN_IDS:
            return
        target_id = int(query.data.split("_")[1])
        block_user_db(target_id)
        await query.edit_message_text(
            text=f"{query.message.text}\n\n🚫 **[Admin បាន Block User នេះរួចរាល់]**",
            parse_mode="Markdown"
        )

    # 3. Handle Download Database Backup Button
    elif query.data == "download_backup":
        if user_id not in ADMIN_IDS:
            return
        if not os.path.exists(DB_NAME):
            await query.message.reply_text("❌ រកមិនឃើញ File Database ឡើយ!")
            return

        try:
            with open(DB_NAME, "rb") as db_file:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=db_file,
                    caption="📦 **File Database (Backup)**\nទិន្នន័យ User ទាំងអស់ត្រូវបាន Backup រួចរាល់!"
                )
        except Exception as e:
            await query.message.reply_text(f"❌ កើតមានបញ្ហា៖ {e}")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    total_users, active_24h, total_messages = get_stats()
    stats_msg = (
        f"📊 **ស្ថិតិអ្នកប្រើប្រាស់ (Bot Statistics)**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• **User សរុប៖** `{total_users}` នាក់\n"
        f"• **User សកម្ម (២៤ម៉ោង)៖** `{active_24h}` នាក់\n"
        f"• **សារឆ្លងឆ្លើយសរុប៖** `{total_messages}` សារ\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(stats_msg, parse_mode="Markdown")

# 🚫 BLOCK COMMAND
async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if context.args:
        try:
            target_id = int(context.args[0])
            block_user_db(target_id)
            await update.message.reply_text(f"🚫 **បាន Block User ID:** `{target_id}` រួចរាល់!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ **ទម្រង់ខុស!** ឧទាហរណ៍៖ `/block 123456789`", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ **សូមបញ្ជាក់ ID!** ឧទាហរណ៍៖ `/block 123456789`", parse_mode="Markdown")

# ✅ UNBLOCK COMMAND
async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if context.args:
        try:
            target_id = int(context.args[0])
            unblock_user_db(target_id)
            await update.message.reply_text(f"✅ **បាន Unblock User ID:** `{target_id}` រួចរាល់!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ **ទម្រង់ខុស!** ឧទាហរណ៍៖ `/unblock 123456789`", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ **សូមបញ្ជាក់ ID!** ឧទាហរណ៍៖ `/unblock 123456789`", parse_mode="Markdown")

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ មុខងារនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("❌ បោះបង់", callback_data="cancel_broadcast")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📢 **សូមផ្ញើសារ/រូបភាព/វីដេអូ ដែលអ្នកចង់ Broadcast ទៅកាន់ User ទាំងអស់៖**",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return WAITING_BROADCAST_MSG

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return ConversationHandler.END

    users = get_all_users()
    success_count, fail_count = 0, 0

    await update.message.reply_text(f"⏳ កំពុង Broadcast ទៅកាន់មនុស្ស {len(users)} នាក់...")

    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            success_count += 1
        except Exception:
            fail_count += 1

    await update.message.reply_text(
        f"✅ **Broadcast រួចរាល់!**\n\n"
        f"• ជោគជ័យ៖ `{success_count}` នាក់\n"
        f"• បរាជ័យ៖ `{fail_count}` នាក់",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ បានបោះបង់ការ Broadcast រួចរាល់!")
    return ConversationHandler.END

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return False

    if update.message.reply_to_message:
        reply_to_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        
        if "🆔 ID:" in reply_to_text:
            try:
                target_user_id = int(reply_to_text.split("🆔 ID:")[1].split("\n")[0].strip().replace("`", ""))

                if update.message.text:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"💬 **សារពី Admin:**\n{update.message.text}",
                        parse_mode="Markdown"
                    )
                else:
                    await context.bot.copy_message(
                        chat_id=target_user_id,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )

                set_replied_status(target_user_id, True)
                await update.message.reply_text("✅ បានផ្ញើតបទៅកាន់ User រួចរាល់!")
                return True
            except Exception as e:
                await update.message.reply_text(f"❌ បរាជ័យក្នុងការផ្ញើ៖ {e}")
                return True
    return False

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # 🛑 ឆែកមើលថា User ត្រូវ Block ដែរឬទេ
    if is_user_blocked(user.id):
        return

    if user.id in ADMIN_IDS:
        if update.message.text == "📊 ស្ថិតិប្រព័ន្ធ":
            await show_stats(update, context)
            return
        is_handled = await handle_admin_reply(update, context)
        if is_handled:
            return

    if update.message.text in ["📢 ផ្ញើសារប្រកាស (Broadcast)", "📊 ស្ថិតិប្រព័ន្ធ"]:
        await update.message.reply_text(
            "⚠️ មុខងារនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    add_or_update_user(user.id, user.first_name, user.username)

    user_text = update.message.text.strip().lower() if update.message.text else ""
    keyword_matched = False

    for keywords_tuple, response in KEYWORDS_REPLY.items():
        for kw in keywords_tuple:
            if kw in user_text:
                await update.message.reply_text(response, parse_mode="Markdown")
                keyword_matched = True
                break
        if keyword_matched:
            break

    username_str = f"@{user.username}" if user.username else "គ្មាន"
    
    # Inline Keyboard ភ្ជាប់ប៊ូតុង Block User សម្រាប់ផ្ញើទៅ Admin
    block_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Block User នេះ", callback_data=f"block_{user.id}")]
    ])

    for admin_id in ADMIN_IDS:
        try:
            if update.message.text:
                combined_text = (
                    f"📩 **សារថ្មីចូល!**\n"
                    f"👤 **ពី៖** {user.first_name} ({username_str})\n"
                    f"🆔 ID: `{user.id}`\n\n"
                    f"💬 **សារ៖** {update.message.text}"
                )
                await context.bot.send_message(
                    chat_id=admin_id, 
                    text=combined_text, 
                    parse_mode="Markdown",
                    reply_markup=block_markup
                )
            else:
                caption_text = (
                    f"📩 **សារថ្មីចូល (Media)!**\n"
                    f"👤 **ពី៖** {user.first_name} ({username_str})\n"
                    f"🆔 ID: `{user.id}`\n\n"
                    f"💬 **Caption:** {update.message.caption or 'គ្មាន'}"
                )
                await context.bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id,
                    caption=caption_text,
                    parse_mode="Markdown",
                    reply_markup=block_markup
                )
        except Exception:
            pass

    if not keyword_matched and not is_replied_status(user.id):
        auto_msg = "📥 ទទួលបានសាររបស់អ្នកហើយ! ក្រុមការងារនឹងឆ្លើយតបក្នុងពេលឆាប់ៗ។"
        await update.message.reply_text(auto_msg)

# ==================== MAIN ====================

if __name__ == '__main__':
    init_db()
    
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()
    
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    broadcast_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📢 ផ្ញើសារប្រកាស \(Broadcast\)$'), start_broadcast)],
        states={
            WAITING_BROADCAST_MSG: [
                CallbackQueryHandler(cancel_broadcast_callback, pattern="^cancel_broadcast$"),
                MessageHandler(filters.ALL & ~filters.COMMAND, send_broadcast)
            ]
        },
        fallbacks=[CallbackQueryHandler(cancel_broadcast_callback, pattern="^cancel_broadcast$")]
    )

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("admin", admin_panel))
    bot_app.add_handler(CommandHandler("stats", show_stats))
    bot_app.add_handler(CommandHandler("block", block_command))
    bot_app.add_handler(CommandHandler("unblock", unblock_command))
    bot_app.add_handler(broadcast_handler)
    
    # Callback Query Handler សម្រាប់ចាប់ប៊ូតុងទាំងអស់
    bot_app.add_handler(CallbackQueryHandler(callback_handler))
    bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_user_message))
    
    print("🚀 Bot និង Web Server កំពុងដំណើរការ...")
    bot_app.run_polling()
