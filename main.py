import os
import logging
from datetime import datetime
from flask import Flask
from threading import Thread
import psycopg2

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

logging.basicConfig(level=logging.INFO)

# ==================== SETTINGS & CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8879562109:AAEcmze51iluEkaLTPBjyy7qcUk7By6gQlQ")
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Admin ដើមដំបូងគេបង្អស់ (Owner)
OWNER_ID = 8613183394
WAITING_BROADCAST_MSG = 1

KEYWORDS_REPLY = {
    ("លេខទូរស័ព្ទ", "លេខ", "លេខទំនាក់ទំនង", "ចង់បើក"): "📞 **ទំនាក់ទំនង៖** 012 345 678 / 098 765 432",
    ("contact", "phone number", "number", "phone"): "📞 **Contact:** 012 345 678 / 098 765 432"
}

# ==================== FLASK WEB SERVER ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# ==================== DATABASE (POSTGRESQL) ====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        print("⚠️ មិនទាន់កំណត់ DATABASE_URL នៅក្នុង Environment Variables ទេ!")
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            is_replied INT DEFAULT 0,
            is_blocked INT DEFAULT 0,
            last_active TIMESTAMP,
            message_count INT DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            admin_id BIGINT PRIMARY KEY
        )
    ''')
    
    cursor.execute('''
        INSERT INTO admins (admin_id) VALUES (%s)
        ON CONFLICT (admin_id) DO NOTHING
    ''', (OWNER_ID,))
    
    conn.commit()
    cursor.close()
    conn.close()

def get_admin_ids() -> list:
    if not DATABASE_URL:
        return [OWNER_ID]
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT admin_id FROM admins')
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [row[0] for row in rows]
    except Exception:
        return [OWNER_ID]

def add_admin_db(admin_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO admins (admin_id) VALUES (%s) ON CONFLICT DO NOTHING', (admin_id,))
    conn.commit()
    cursor.close()
    conn.close()

def remove_admin_db(admin_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM admins WHERE admin_id = %s', (admin_id,))
    conn.commit()
    cursor.close()
    conn.close()

def add_or_update_user(user_id, first_name, username):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute('''
        INSERT INTO users (user_id, first_name, username, is_replied, is_blocked, last_active, message_count)
        VALUES (%s, %s, %s, 0, 0, %s, 1)
        ON CONFLICT (user_id) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username,
            last_active = EXCLUDED.last_active,
            message_count = users.message_count + 1
    ''', (user_id, first_name, username, now))
    conn.commit()
    cursor.close()
    conn.close()

def block_user_db(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = 1 WHERE user_id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

def unblock_user_db(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = 0 WHERE user_id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

def is_user_blocked(user_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_blocked FROM users WHERE user_id = %s', (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(row[0]) if row and row[0] else False

def set_replied_status(user_id, status: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_replied = %s WHERE user_id = %s', (1 if status else 0, user_id))
    conn.commit()
    cursor.close()
    conn.close()

def is_replied_status(user_id) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_replied FROM users WHERE user_id = %s', (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(row[0]) if row else False

def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE is_blocked = 0')
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row[0] for row in rows]

def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '1 DAY'")
    active_24h = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(message_count) FROM users')
    total_messages = cursor.fetchone()[0] or 0
    cursor.close()
    conn.close()
    return total_users, active_24h, total_messages

# ==================== ADMIN MANAGEMENT COMMANDS ====================

async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
        return
    if context.args:
        try:
            new_admin_id = int(context.args[0])
            add_admin_db(new_admin_id)
            
            # ១. ផ្ញើសារប្រាប់ Admin ដែលជាអ្នកបន្ថែម
            await update.message.reply_text(f"✅ **បានបន្ថែម Admin ថ្មីជោគជ័យ!**\nID: `{new_admin_id}`", parse_mode="Markdown")
            
            # ២. ផ្ញើសារ និងលោតប៊ូតុង Menu ទៅកាន់ Admin ថ្មីដោយស្វ័យប្រវត្តិ
            keyboard = [["📢 ផ្ញើសារប្រកាស (Broadcast)", "📊 ស្ថិតិប្រព័ន្ធ"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            try:
                await context.bot.send_message(
                    chat_id=new_admin_id,
                    text="🎉 **អ្នកត្រូវបានស្ថាបនិកបន្ថែមជា Admin រួចរាល់ហើយ!**\nឥឡូវនេះអ្នកអាចទទួលសារពី User និងគ្រប់គ្រងប្រព័ន្ធបាន។",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        except ValueError:
            await update.message.reply_text("⚠️ **ទម្រង់ខុស!** ឧទាហរណ៍៖ `/addadmin 123456789`", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ **សូមបញ្ជាក់ ID!** ឧទាហរណ៍៖ `/addadmin 123456789`", parse_mode="Markdown")

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
        return
    if context.args:
        try:
            target_id = int(context.args[0])
            if target_id == OWNER_ID:
                await update.message.reply_text("❌ មិនអាចលុប Owner ID បានទេ!")
                return
            
            # ១. លុបចេញពី Database
            remove_admin_db(target_id)
            
            # ២. ផ្ញើសារប្រាប់ Admin ដែលជាអ្នកលុប
            await update.message.reply_text(f"🗑️ **បានលុប Admin ID:** `{target_id}` រួចរាល់!", parse_mode="Markdown")
            
            # ៣. ផ្ញើសារទៅលុបប៊ូតុង Admin ចេញពី Chat របស់គេភ្លាមៗ
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="❌ **សិទ្ធិជា Admin របស់អ្នកត្រូវបានដកហូតវិញហើយ!**",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        except ValueError:
            await update.message.reply_text("⚠️ **ទម្រង់ខុស!** ឧទាហរណ៍៖ `/deladmin 123456789`", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ **សូមបញ្ជាក់ ID!** ឧទាហរណ៍៖ `/deladmin 123456789`", parse_mode="Markdown")

async def list_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
        return
    admins = get_admin_ids()
    admin_list_text = "👑 **បញ្ជីឈ្មោះ Admin ទាំងអស់៖**\n" + "\n".join([f"• `{a}`" for a in admins])
    await update.message.reply_text(admin_list_text, parse_mode="Markdown")

# ==================== BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_user_blocked(user.id):
        return

    add_or_update_user(user.id, user.first_name, user.username)

    if user.id in get_admin_ids():
        keyboard = [["📢 ផ្ញើសារប្រកាស (Broadcast)", "📊 ស្ថិតិប្រព័ន្ធ"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"👑 **សួស្តី Admin {user.first_name}!**\n\n"
            f"💡 **បញ្ជាសម្រាប់គ្រប់គ្រង Admin:**\n"
            f"• `/addadmin [ID]` - បន្ថែម Admin ថ្មី\n"
            f"• `/deladmin [ID]` - លុប Admin\n"
            f"• `/admins` - មើលបញ្ជី Admin",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        inline_keyboard = [[InlineKeyboardButton("📞 ទំនាក់ទំនង", callback_data="info_contact")]]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        welcome_text = f"👋 **ជម្រាបសួរ {user.first_name}!**\n\nសូមស្វាគមន៍មកកាន់ប្រព័ន្ធទំនាក់ទំនងរបស់យើងខ្ញុំ! 🤖"
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if is_user_blocked(user_id):
        return

    await query.answer()

    if query.data.startswith("info_"):
        if query.data == "info_contact":
            text = "📞 **ព័ត៌មានទំនាក់ទំនង៖**\n• ទូរស័ព្ទ៖ 012 345 678 / 098 765 432\n• Telegram: @admin"
            await query.message.reply_text(text, parse_mode="Markdown")

    elif query.data.startswith("block_"):
        if user_id not in get_admin_ids():
            return
        target_id = int(query.data.split("_")[1])
        block_user_db(target_id)
        await query.edit_message_text(
            text=f"{query.message.text}\n\n🚫 **[Admin បាន Block User នេះរួចរាល់]**",
            parse_mode="Markdown"
        )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
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

async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
        return
    if context.args:
        try:
            target_id = int(context.args[0])
            block_user_db(target_id)
            await update.message.reply_text(f"🚫 **បាន Block User ID:** `{target_id}` រួចរាល់!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ **ទម្រង់ខុស!** ឧទាហរណ៍៖ `/block 123456789`", parse_mode="Markdown")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
        return
    if context.args:
        try:
            target_id = int(context.args[0])
            unblock_user_db(target_id)
            await update.message.reply_text(f"✅ **បាន Unblock User ID:** `{target_id}` រួចរាល់!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ **ទម្រង់ខុស!** ឧទាហរណ៍៖ `/unblock 123456789`", parse_mode="Markdown")

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_admin_ids():
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
    if update.effective_user.id not in get_admin_ids():
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
    if user_id not in get_admin_ids():
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

    if is_user_blocked(user.id):
        return

    if user.id in get_admin_ids():
        if update.message.text == "📊 ស្ថិតិប្រព័ន្ធ":
            await show_stats(update, context)
            return
        is_handled = await handle_admin_reply(update, context)
        if is_handled:
            return

    if update.message.text in ["📢 ផ្ញើសារប្រកាស (Broadcast)", "📊 ស្ថិតិប្រព័ន្ធ"]:
        await update.message.reply_text("⚠️ មុខងារនេះសម្រាប់តែ Admin ប៉ុណ្ណោះ!", reply_markup=ReplyKeyboardRemove())
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
    block_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Block User នេះ", callback_data=f"block_{user.id}")]
    ])

    for admin_id in get_admin_ids():
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
        auto_msg = "📥 ទទួលបានសាររបស់អ្នកហើយ! ក្រុមការងារនឹងឆ្លើយតបក្នុងពេលឆាប់ៗ"
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
    bot_app.add_handler(CommandHandler("stats", show_stats))
    bot_app.add_handler(CommandHandler("block", block_command))
    bot_app.add_handler(CommandHandler("unblock", unblock_command))
    bot_app.add_handler(CommandHandler("addadmin", add_admin_command))
    bot_app.add_handler(CommandHandler("deladmin", remove_admin_command))
    bot_app.add_handler(CommandHandler("admins", list_admins_command))
    bot_app.add_handler(broadcast_handler)
    bot_app.add_handler(CallbackQueryHandler(callback_handler))
    bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_user_message))
    
    print("🚀 Bot និង Web Server កំពុងដំណើរការ...")
    bot_app.run_polling()
