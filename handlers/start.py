#!/usr/bin/env python3
# ============================================
# START / HELP / ID HANDLERS (DEBUG VERSION)
# ============================================

import logging
from pyrogram import Client, filters
from pyrogram.types import Message

from config.settings import OWNER_ID
from services.security import (
    ensure_user_registered,
    require_admin,
)
from database.admins import is_admin as db_is_admin
from utils.helpers import html_safe
from utils.logger import log_user, log_admin

logger = logging.getLogger("handlers.start")

# ============================================
# /start COMMAND (DEBUG MODE)
# ============================================

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    try:
        user = message.from_user
        user_id = user.id
        
        logger.info(f"📨 Start command received from user_id={user_id}, username={user.username}")
        
        # Debug: Check if we're reaching here
        await message.reply_text(
            f"👋 Hello! I received your /start command.\n"
            f"Your ID: <code>{user_id}</code>\n"
            f"Checking permissions...",
            parse_mode="html"
        )
        
        # Try to register user (might fail if DB not connected)
        try:
            await ensure_user_registered(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name,
            )
            logger.info(f"✅ User {user_id} registered/checked in DB")
        except Exception as e:
            logger.error(f"❌ DB registration error: {e}")
            await message.reply_text(
                f"⚠️ Database error: {str(e)[:100]}",
                parse_mode="html"
            )
        
        # Check permissions (TEMPORARILY DISABLED FOR DEBUG)
        # Comment this section to test
        """
        is_owner = user_id == OWNER_ID
        is_admin = False
        
        try:
            is_admin = await db_is_admin(user_id)
            logger.info(f"🔐 Admin check: is_owner={is_owner}, is_admin={is_admin}")
        except Exception as e:
            logger.error(f"❌ Admin check error: {e}")
            await message.reply_text(
                f"⚠️ Admin check failed: {str(e)[:100]}",
                parse_mode="html"
            )
        
        if not (is_owner or is_admin):
            await message.reply_text(
                "❌ <b>Access Denied</b>\n\n"
                f"You are not authorized to use this bot.\n"
                f"Your ID: <code>{user_id}</code>\n"
                f"Owner ID: <code>{OWNER_ID}</code>",
                parse_mode="html",
            )
            logger.warning(f"Unauthorized /start attempt | user_id={user_id}")
            return
        """
        
        # TEMPORARY: Allow everyone for testing
        role = "👤 User (Testing Mode)"
        
        text = f"""
🤖 <b>AK KING 👑 – OTP Master Bot</b>

<b>Status:</b> ✅ Running on Heroku
<b>Your Role:</b> {role}
<b>User ID:</b> <code>{user_id}</code>

<b>Features:</b>
• Multiple sites monitoring
• Live OTP forwarding
• Custom SMS templates
• Inline button support

🔧 <i>Bot is in testing mode. All commands available.</i>
"""
        
        await message.reply_text(text, parse_mode="html")
        logger.info(f"✅ Start command completed for user_id={user_id}")
        
    except Exception as e:
        logger.error(f"❌ Start handler error: {e}", exc_info=True)
        await message.reply_text(
            f"❌ Error: {str(e)[:200]}",
            parse_mode="html"
        )

# ============================================
# /ping COMMAND (FOR DEBUGGING)
# ============================================

@Client.on_message(filters.command("ping") & filters.private)
async def ping_handler(client: Client, message: Message):
    """Simple ping command to test if bot is responding"""
    await message.reply_text("🏓 Pong! Bot is alive.")
    logger.info(f"Ping from user_id={message.from_user.id}")

# ============================================
# /status COMMAND
# ============================================

@Client.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    """Check bot status"""
    import psutil
    import os
    
    # Get system info
    process = psutil.Process(os.getpid())
    memory_usage = process.memory_info().rss / 1024 / 1024  # MB
    cpu_percent = process.cpu_percent(interval=1)
    
    text = f"""
📊 <b>Bot Status</b>

<b>Platform:</b> Heroku ({os.environ.get('DYNO', 'Unknown')})
<b>Memory Usage:</b> {memory_usage:.2f} MB
<b>CPU Usage:</b> {cpu_percent:.1f}%
<b>Python:</b> {sys.version.split()[0]}

<b>Commands working:</b> ✅ Ping, Status
"""
    
    await message.reply_text(text, parse_mode="html")

# ============================================
# /help COMMAND (SIMPLIFIED)
# ============================================

@Client.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    text = """
🆘 <b>Help – AK KING 👑</b>

<b>Debug Commands:</b>
/ping – Check if bot is responsive
/status – View bot system status
/id – Get chat ID

<b>Admin Commands:</b>
/addadmin – Add admin (owner only)
/listadmins – List all admins

<b>Site Management:</b>
/addsite – Add a new site
/listsites – List all sites
/enablesite – Enable site polling

<b>Support:</b> Contact owner
"""
    
    await message.reply_text(text, parse_mode="html")
    logger.info(f"Help command from user_id={message.from_user.id}")

# ============================================
# /id COMMAND
# ============================================

@Client.on_message(filters.command("id"))
async def id_handler(client: Client, message: Message):
    user_id = message.from_user.id
    chat = message.chat
    
    text = f"""
📋 <b>Chat Information</b>

<b>Your User ID:</b> <code>{user_id}</code>
<b>Chat ID:</b> <code>{chat.id}</code>
<b>Chat Type:</b> {chat.type}
"""
    
    await message.reply_text(text, parse_mode="html")
    logger.info(f"ID check: user_id={user_id}, chat_id={chat.id}")

# ============================================
# FALLBACK HANDLER (FOR ANY MESSAGE)
# ============================================

@Client.on_message(filters.private & ~filters.command())
async def fallback_handler(client: Client, message: Message):
    """Handle any non-command messages"""
    await message.reply_text(
        "🤔 I didn't understand that.\n"
        "Use /help to see available commands.",
        parse_mode="html"
    )
    logger.info(f"Fallback for user_id={message.from_user.id}, text={message.text[:50]}")

import sys  # Add at top
