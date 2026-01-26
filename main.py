#!/usr/bin/env python3
import os
import re
import time
import json
import asyncio
import logging
import requests
import threading
import html
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ================= CONFIG =================

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "5397621246"))  # Your owner ID
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
CHECK_INTERVAL = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ================= GLOBAL CACHE =================

SITE_SESSIONS = {}
LAST_RESET = None

# ================= DB SETUP WITH INDEXES =================

mongo = MongoClient(MONGO_URI)
db = mongo["master_bot"]
sites_col = db["sites"]
users_col = db["users"]
admins_col = db["admins"]

# Create indexes for performance
try:
    sites_col.create_index("user_id")
    sites_col.create_index("enabled")
    sites_col.create_index("last_uid")
    sites_col.create_index([("user_id", 1), ("enabled", 1)])
    users_col.create_index("user_id", unique=True)
    admins_col.create_index("user_id", unique=True)
    logging.info("✅ MongoDB indexes created/verified")
except Exception as e:
    logging.warning(f"⚠️ Could not create indexes: {e}")

# ================= ADMIN SYSTEM =================

def is_owner(user_id: int) -> bool:
    """Check if user is the owner"""
    return user_id == OWNER_ID

def is_admin(user_id: int) -> bool:
    """Check if user is owner or admin"""
    if is_owner(user_id):
        return True
    return admins_col.find_one({"user_id": user_id}) is not None

# ================= SMS FORMAT SYSTEM =================

DEFAULT_SMS_FORMAT = """📩 <b>LIVE OTP RECEIVED</b>

📞 <b>Number:</b> <code>{number}</code>
🔢 <b>OTP:</b> 🔥 <code>{otp}</code> 🔥
🏷 <b>Service:</b> {service}
🌍 <b>Country:</b> {country}
🕒 <b>Time:</b> {time}

💬 <b>SMS:</b>
{message}

⚡ <b>—͟͟͞͞𝗔𝗞𝗔𝗦𝗛 🥀</b>"""

def render_sms(site: Dict, data: Dict) -> str:
    """Render SMS using site's custom format or default - FIXED ERROR HANDLING"""
    template = site.get("sms_format", {}).get("template", DEFAULT_SMS_FORMAT)
    
    # Ensure all variables are available
    safe_data = {
        "otp": html.escape(data.get("otp", "N/A")),
        "number": html.escape(data.get("number", "N/A")),
        "message": html.escape(data.get("message", "")),
        "time": html.escape(data.get("date", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))),
        "service": html.escape(data.get("service", "Unknown")),
        "country": html.escape(data.get("country", get_country_from_number(data.get("number", ""))))
    }
    
    try:
        return template.format(**safe_data)
    except KeyError as e:
        logging.error(f"Missing variable in SMS template: {e}")
        # FIXED: HTML escaped error message with proper line breaks
        error_msg = f"⚠️ Template Error: Invalid variable {e}"
        return html.escape(error_msg) + "<br><br>" + DEFAULT_SMS_FORMAT.format(**safe_data)
    except Exception as e:
        logging.error(f"Template rendering error: {e}")
        # Additional safety for any other template errors
        return html.escape(f"⚠️ Template Error: {str(e)}") + "<br><br>" + DEFAULT_SMS_FORMAT.format(**safe_data)

# ================= BUTTON SYSTEM =================

DEFAULT_BUTTONS = [
    {"text": "🆘 Support", "url": "t.me/botcasx", "enabled": True},
    {"text": "📲 Numbers", "url": "t.me/numbers", "enabled": True}
]

def build_buttons(site: Dict):
    """Build inline keyboard from site's button configuration"""
    buttons = site.get("buttons", [])
    
    if not buttons:
        # Default buttons if none configured
        return {
            "inline_keyboard": [
                [
                    {"text": "Owner", "url": site.get("owner_url", "t.me/username")},
                    {"text": "🆘 Support", "url": site.get("support_url", "t.me/botcasx")}
                ]
            ]
        }
    
    # Group buttons (max 2 per row)
    keyboard = []
    row = []
    
    for button in buttons[:4]:  # Max 4 buttons
        if button.get("enabled", True):
            row.append({
                "text": button.get("text", "Button"),
                "url": button.get("url", "")
            })
            
            if len(row) == 2:
                keyboard.append(row)
                row = []
    
    if row:
        keyboard.append(row)
    
    return {"inline_keyboard": keyboard} if keyboard else None

# ================= HELPER FUNCTIONS =================

def extract_otp(text: str) -> str:
    """Extract OTP from text - HARDENED VERSION"""
    if not text:
        return "N/A"
    
    patterns = [
        r'(?:OTP|code|verification|password|पासकोड|कोड)[^\d]{0,10}(\d{4,8})',
        r'\b(?!\d{9,})(\d{4,8})\b',
        r'(?:is|का|की)[^\d]{0,5}(\d{4,8})',
        r'[:\-\s]\s*(\d{4,8})\b'
    ]
    
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            otp = m.group(1)
            if 4 <= len(otp) <= 8:
                return otp
    
    fallback_patterns = [
        r'\b(\d{4})\b',
        r'\b(\d{5})\b',
        r'\b(\d{6})\b',
        r'\b(\d{7})\b',
        r'\b(\d{8})\b'
    ]
    
    for pattern in fallback_patterns:
        matches = re.findall(pattern, text)
        if matches:
            for match in matches:
                context = re.search(r'\b\d{9,}\b', text)
                if not context:
                    return match
    
    return "N/A"

def mask_phone_number(number: str) -> str:
    """Mask phone number for privacy"""
    if not number or len(number) < 10:
        return number
    return number[:3] + "*" * (len(number) - 5) + number[-2:]

def get_country_from_number(number: str) -> str:
    """Extract country from phone number"""
    if not number:
        return "Unknown"
    
    prefixes = {
        '1': '🇺🇸 USA',
        '91': '🇮🇳 India',
        '44': '🇬🇧 UK',
        '86': '🇨🇳 China',
        '33': '🇫🇷 France',
        '49': '🇩🇪 Germany',
        '81': '🇯🇵 Japan',
        '7': '🇷🇺 Russia',
        '92': '🇵🇰 Pakistan',
        '880': '🇧🇩 Bangladesh',
        '94': '🇱🇰 Sri Lanka',
        '971': '🇦🇪 UAE',
        '966': '🇸🇦 Saudi Arabia',
        '65': '🇸🇬 Singapore',
        '60': '🇲🇾 Malaysia',
        '63': '🇵🇭 Philippines',
        '62': '🇮🇩 Indonesia',
        '84': '🇻🇳 Vietnam',
        '66': '🇹🇭 Thailand',
        '55': '🇧🇷 Brazil',
        '34': '🇪🇸 Spain',
        '39': '🇮🇹 Italy',
        '61': '🇦🇺 Australia',
        '27': '🇿🇦 South Africa',
    }
    
    for prefix, country in prefixes.items():
        if number.startswith(prefix):
            return country
    
    return "🌍 International"

def get_site_session(site):
    """Create and return a persistent session for the site"""
    s = requests.Session()
    s.headers.update(site.get("headers", {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }))
    s.cookies.update(site.get("cookies", {}))
    return s

# ================= ✅ ENHANCED: Telegram Send Function with Better Error Logging =================

def send_to_telegram(bot_token: str, chat_ids: list, text: str, site: dict):
    """Send message to Telegram with custom buttons - ENHANCED ERROR LOGGING"""
    reply_markup = build_buttons(site)
    success_any = False
    
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            # ✅ FIXED: Telegram expects object, not JSON string
            if reply_markup:
                payload["reply_markup"] = reply_markup
            
            r = requests.post(url, json=payload, timeout=15)
            
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    success_any = True
                    logging.info(f"✅ Sent to chat {chat_id}")
                else:
                    logging.error(
                        f"Telegram API error | chat={chat_id} | response={data}"
                    )
            else:
                # ✅ ENHANCED: Log full Telegram response for debugging
                logging.error(
                    f"Telegram send failed | chat={chat_id} | "
                    f"status={r.status_code} | response={r.text}"
                )
                # 🔍 ADDITIONAL DEBUG INFO
                logging.debug(f"Full Telegram response: {r.text}")
                logging.debug(f"Bot token (first 10 chars): {bot_token[:10]}...")
                logging.debug(f"Chat ID type: {type(chat_id)}")
            
        except Exception as e:
            logging.error(f"Telegram send exception | chat={chat_id} | {e}", exc_info=True)
    
    return success_any

def reset_daily_stats():
    """Reset daily statistics at midnight UTC"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    result = sites_col.update_many(
        {"stats.last_day": {"$ne": today}},
        {
            "$set": {
                "stats.today": 0,
                "stats.last_day": today
            }
        }
    )
    
    if result.modified_count > 0:
        logging.info(f"✅ Reset daily stats for {result.modified_count} sites")

# ================= SITE MANAGEMENT =================

def add_site(user_id: int, site_data: Dict) -> str:
    """Add new site for user - FIXED: No duplicate DEFAULT_BUTTONS"""
    site_id = str(int(time.time() * 1000))
    
    chat_ids = site_data.get("chat_ids", [])
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]
    
    # ✅ FIXED: Use DEFAULT_BUTTONS with proper cloning
    buttons = [btn.copy() for btn in DEFAULT_BUTTONS]
    
    # Update URLs based on site data
    for btn in buttons:
        if btn["text"] == "🆘 Support":
            btn["url"] = site_data.get("support_url", "t.me/botcasx")
        elif btn["text"] == "📲 Numbers":
            btn["url"] = site_data.get("owner_url", "") or "t.me/username"
    
    # Get owner username for grouping
    user_info = users_col.find_one({"user_id": user_id})
    owner_username = user_info.get("username", "unknown") if user_info else "unknown"
    
    site_data.update({
        "_id": site_id,
        "user_id": user_id,
        "owner_username": owner_username,
        "chat_ids": chat_ids,
        "enabled": True,
        "created_at": datetime.utcnow(),
        "last_check": None,
        "last_uid": None,
        "stats": {
            "today": 0,
            "total": 0,
            "errors": 0,
            "last_success": None,
            "last_day": datetime.utcnow().strftime("%Y-%m-%d")
        },
        "cookies": site_data.get("cookies", {}),
        "headers": site_data.get("headers", {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }),
        "owner_url": site_data.get("owner_url", ""),
        "support_url": site_data.get("support_url", "t.me/botcasx"),
        "ajax_type": site_data.get("ajax_type", "standard"),
        "buttons": buttons,  # ✅ Use cloned buttons
        "sms_format": {
            "template": DEFAULT_SMS_FORMAT,
            "created_at": datetime.utcnow()
        }
    })
    
    sites_col.insert_one(site_data)
    return site_id

def get_user_sites(user_id: int) -> List[Dict]:
    """Get all sites for a user"""
    if is_owner(user_id):
        return list(sites_col.find({}))
    else:
        return list(sites_col.find({"user_id": user_id}))

def get_site(site_id: str) -> Optional[Dict]:
    """Get site by ID"""
    return sites_col.find_one({"_id": site_id})

def update_site(site_id: str, update_data: Dict) -> bool:
    """Update site data"""
    try:
        result = sites_col.update_one(
            {"_id": site_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logging.error(f"Error updating site {site_id}: {str(e)}")
        return False

# ================= MENUS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add New Site", callback_data="add_site")],
        [InlineKeyboardButton("📋 My Sites", callback_data="list_sites")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("🆘 Help", callback_data="help")]
    ])

def site_menu(site_id: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔘 Toggle ON/OFF", callback_data=f"toggle_{site_id}"),
            InlineKeyboardButton("💬 Manage Chats", callback_data=f"chats_{site_id}")
        ],
        [
            InlineKeyboardButton("✏️ Edit SMS Format", callback_data=f"format_{site_id}"),
            InlineKeyboardButton("🔘 Edit Buttons", callback_data=f"buttons_{site_id}")
        ],
        [
            InlineKeyboardButton("🍪 Edit Cookies", callback_data=f"cookies_{site_id}"),
            InlineKeyboardButton("📝 Edit Headers", callback_data=f"headers_{site_id}")
        ],
        [
            InlineKeyboardButton("🔄 Test Site", callback_data=f"test_{site_id}"),
            InlineKeyboardButton("📊 Stats", callback_data=f"site_stats_{site_id}")
        ],
        [
            InlineKeyboardButton("✏️ Edit Bot Token", callback_data=f"token_{site_id}"),
            InlineKeyboardButton("🗑 Delete Site", callback_data=f"delete_{site_id}")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="list_sites")]
    ])

def back_to_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])

# ================= COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "You are not authorized to use this bot.\n"
            "Only owner and admins can access this system.",
            parse_mode="HTML"
        )
        return
    
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({
            "user_id": user_id,
            "username": update.effective_user.username,
            "first_name": update.effective_user.first_name,
            "joined_at": datetime.utcnow(),
            "role": "owner" if is_owner(user_id) else "admin"
        })
    
    welcome_text = f"""🤖 <b>AK KING 👑 - OTP Forwarder Bot</b>

<b>Access Level:</b> {'👑 Owner' if is_owner(user_id) else '🛡 Admin'}

<b>Features:</b>
• Use your own bot token
• Multiple chat IDs per site
• Live OTP forwarding
• Cookie & header management
• INTS SMS format support
• Custom SMS formatting
• Custom inline buttons

<b>Quick Start:</b>
1. Create your own bot via @BotFather
2. Get your bot token
3. Add site using this bot
4. Start receiving OTPs!

Use the buttons below to get started."""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "You are not authorized to use this bot.",
            parse_mode="HTML"
        )
        return
    
    help_text = """🆘 <b>How to Use This Bot</b>

<b>Step 1 - Create Your Bot:</b>
1. Go to @BotFather on Telegram
2. Send /newbot command
3. Follow instructions
4. Copy the bot token

<b>Step 2 - Add Your Site:</b>
1. Click "Add New Site"
2. Enter your bot token
3. Add chat IDs (where OTPs should go)
4. Enter AJAX URL to monitor
5. Set site name

<b>Step 3 - Get Chat IDs:</b>
• For personal chat: Send /id to your bot
• For group: Add your bot to group, then send /id in group

<b>Step 4 - For INTS SMS Sites:</b>
• Enter your PHPSESSID cookie
• Use INTS SMS format URL

<b>Step 5 - Customization:</b>
• Edit SMS format per site
• Edit inline buttons per site
• Manage admins (owner only)

<b>Admin Commands:</b>
/addadmin USER_ID - Add admin (owner only)
/removeadmin USER_ID - Remove admin (owner only)
/listadmins - List all admins
/access - Check your access level

<b>Support:</b> @botcasx"""
    
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        reply_markup=back_to_main_menu()
    )

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get chat ID"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "You are not authorized to use this bot.",
            parse_mode="HTML"
        )
        return
    
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    type_map = {
        "private": "Personal Chat",
        "group": "Group",
        "supergroup": "Supergroup",
        "channel": "Channel"
    }
    
    await update.message.reply_text(
        f"📋 <b>Chat Information</b>\n\n"
        f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
        f"<b>Type:</b> {type_map.get(chat_type, 'Unknown')}\n\n"
        f"Use this ID when adding sites.",
        parse_mode="HTML"
    )

# ================= ADMIN COMMANDS =================

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add new admin - OWNER ONLY"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text(
            "❌ <b>Owner Only</b>\n\n"
            "This command is reserved for the bot owner only.",
            parse_mode="HTML"
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /addadmin <user_id>\n\n"
            "Example: /addadmin 123456789"
        )
        return
    
    try:
        uid = int(context.args[0])
        
        if uid == OWNER_ID:
            await update.message.reply_text("❌ Owner is already admin!")
            return
        
        existing = admins_col.find_one({"user_id": uid})
        if existing:
            await update.message.reply_text(f"⚠️ User {uid} is already an admin")
            return
        
        admins_col.insert_one({
            "user_id": uid,
            "added_by": update.effective_user.id,
            "added_at": datetime.utcnow(),
            "level": "admin"
        })
        
        await update.message.reply_text(
            f"✅ <b>Admin Added Successfully</b>\n\n"
            f"User ID: <code>{uid}</code>\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format")
    except Exception as e:
        logging.error(f"Error adding admin: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove admin - OWNER ONLY"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text(
            "❌ <b>Owner Only</b>\n\n"
            "This command is reserved for the bot owner only.",
            parse_mode="HTML"
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /removeadmin <user_id>\n\n"
            "Example: /removeadmin 123456789"
        )
        return
    
    try:
        uid = int(context.args[0])
        
        if uid == OWNER_ID:
            await update.message.reply_text("❌ Cannot remove owner!")
            return
        
        result = admins_col.delete_one({"user_id": uid})
        
        if result.deleted_count > 0:
            await update.message.reply_text(
                f"✅ <b>Admin Removed</b>\n\n"
                f"User ID: <code>{uid}</code>\n"
                f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(f"❌ User {uid} is not an admin")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format")
    except Exception as e:
        logging.error(f"Error removing admin: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "You are not authorized to use this command.",
            parse_mode="HTML"
        )
        return
    
    admins = list(admins_col.find({}))
    
    text = "👑 <b>Admin List</b>\n\n"
    text += f"<b>Owner:</b> <code>{OWNER_ID}</code>\n\n"
    
    if admins:
        text += "<b>Admins:</b>\n"
        for i, admin in enumerate(admins, 1):
            text += f"{i}. <code>{admin['user_id']}</code>\n"
            if admin.get('added_at'):
                added_time = admin['added_at'].strftime('%Y-%m-%d')
                text += f"   Added: {added_time}\n"
    else:
        text += "No additional admins.\n"
    
    text += f"\nTotal Admins: {len(admins)}"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user's access level"""
    user_id = update.effective_user.id
    
    if is_owner(user_id):
        role = "👑 Owner"
    elif is_admin(user_id):
        role = "🛡 Admin"
    else:
        role = "👤 User"
    
    await update.message.reply_text(
        f"🔐 <b>Access Level</b>\n\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<b>Role:</b> {role}\n"
        f"<b>Status:</b> {'✅ Authorized' if is_admin(user_id) else '❌ Unauthorized'}",
        parse_mode="HTML"
    )

# ================= TEXT MESSAGE HANDLER =================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages - IMPROVED RATE LIMIT UX"""
    user_id = update.effective_user.id
    
    # ✅ IMPROVED: More user-friendly rate limiting
    if "last_action" in context.user_data:
        elapsed = time.time() - context.user_data["last_action"]
        if elapsed < 1.5:  # Increased from 2 to 1.5 for better UX
            remaining = 1.5 - elapsed
            await update.message.reply_text(
                f"⏳ Please wait {remaining:.1f} seconds before next action.",
                parse_mode="HTML"
            )
            return
    context.user_data["last_action"] = time.time()
    
    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ <b>Access Denied</b>\n\n"
            "You are not authorized to use this bot.",
            parse_mode="HTML"
        )
        return
    
    text = update.message.text.strip()
    
    # Handle delete confirmation
    if "confirm_delete" in context.user_data:
        site_id = context.user_data["confirm_delete"]
        site = get_site(site_id)
        
        if not site or (not is_owner(user_id) and site["user_id"] != user_id):
            await update.message.reply_text("❌ Access denied")
            context.user_data.pop("confirm_delete", None)
            return
        
        if text == "DELETE":
            sites_col.delete_one({"_id": site_id})
            SITE_SESSIONS.pop(site_id, None)
            
            await update.message.reply_text(
                "✅ <b>SITE DELETED SUCCESSFULLY</b>\n\n"
                "The site has been permanently removed.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        else:
            await update.message.reply_text(
                "❌ <b>Deletion cancelled</b>\n\n"
                "You didn't type DELETE. Site was not deleted.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Site", callback_data=f"view_site_{site_id}")]
                ])
            )
        
        context.user_data.pop("confirm_delete", None)
        return
    
    # Handle SMS format editing
    if "edit_format" in context.user_data and context.user_data.get("edit_format_step") == "get_format":
        site_id = context.user_data.pop("edit_format")
        context.user_data.pop("edit_format_step", None)
        
        update_site(site_id, {
            "sms_format": {
                "template": text,
                "updated_at": datetime.utcnow(),
                "updated_by": update.effective_user.id
            }
        })
        
        await update.message.reply_text(
            "✅ <b>SMS Format Updated Successfully!</b>\n\n"
            "The new format will be used for all future OTP messages.",
            parse_mode="HTML"
        )
        return
    
    # Handle button text editing
    if "edit_button_text" in context.user_data:
        site_id = context.user_data["edit_button_text"]["site_id"]
        btn_index = context.user_data["edit_button_text"]["btn_index"]
        
        site = get_site(site_id)
        if site and (is_owner(user_id) or site["user_id"] == user_id):
            buttons = site.get("buttons", DEFAULT_BUTTONS).copy()
            if btn_index < len(buttons):
                buttons[btn_index]["text"] = text
                update_site(site_id, {"buttons": buttons})
                
                await update.message.reply_text(
                    f"✅ <b>Button Text Updated</b>\n\n"
                    f"New text: {html.escape(text)}",
                    parse_mode="HTML"
                )
        
        context.user_data.pop("edit_button_text", None)
        return
    
    # Handle button URL editing
    if "edit_button_url" in context.user_data:
        site_id = context.user_data["edit_button_url"]["site_id"]
        btn_index = context.user_data["edit_button_url"]["btn_index"]
        
        if text.startswith("t.me/"):
            text = "https://" + text
        
        if not (text.startswith("http://") or text.startswith("https://") or text.startswith("tg://")):
            await update.message.reply_text(
                "❌ <b>Invalid URL format</b>\n\n"
                "URL must start with:\n"
                "• http:// or https://\n"
                "• tg:// (Telegram deep link)\n"
                "• t.me/ (Telegram username)\n\n"
                "Please enter a valid URL:",
                parse_mode="HTML"
            )
            return
        
        site = get_site(site_id)
        if site and (is_owner(user_id) or site["user_id"] == user_id):
            buttons = site.get("buttons", DEFAULT_BUTTONS).copy()
            if btn_index < len(buttons):
                buttons[btn_index]["url"] = text
                update_site(site_id, {"buttons": buttons})
                
                await update.message.reply_text(
                    f"✅ <b>Button URL Updated</b>\n\n"
                    f"New URL: {html.escape(text)}",
                    parse_mode="HTML"
                )
        
        context.user_data.pop("edit_button_url", None)
        return
    
    # Handle bot token editing
    if "edit_bot_token" in context.user_data:
        site_id = context.user_data.pop("edit_bot_token")
        new_token = text.strip()
        
        site = get_site(site_id)
        if not site or (not is_owner(user_id) and site["user_id"] != user_id):
            await update.message.reply_text("❌ Access denied")
            return
        
        if ":" not in new_token or len(new_token) < 30:
            await update.message.reply_text(
                "❌ <b>Invalid bot token format</b>\n\n"
                "Please send a valid bot token.",
                parse_mode="HTML"
            )
            return
        
        try:
            test = requests.get(
                f"https://api.telegram.org/bot{new_token}/getMe",
                timeout=10
            ).json()
            
            if not test.get("ok"):
                raise Exception("Telegram rejected token")
            
            bot_username = test["result"]["username"]
            
        except Exception:
            await update.message.reply_text(
                "❌ <b>Bot token is invalid or unreachable</b>",
                parse_mode="HTML"
            )
            return
        
        update_site(site_id, {
            "bot_token": new_token,
            "bot_username": bot_username
        })
        
        await update.message.reply_text(
            f"✅ <b>Bot Token Updated</b>\n\n"
            f"Bot: @{bot_username}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
            ])
        )
        return
    
    # Check if user is in add site flow
    if "adding_site" in context.user_data:
        step = context.user_data["adding_site"]["step"]
        site_data = context.user_data["adding_site"]["data"]
        
        if step == 1:  # Bot Token
            if ":" not in text or len(text) < 30:
                await update.message.reply_text(
                    "❌ <b>Invalid bot token format.</b>\n\n"
                    "Bot token should look like: <code>123456789:ABCdefGHIjklMnopQRstUvWXyz</code>\n\n"
                    "Please enter a valid bot token:",
                    parse_mode="HTML"
                )
                return
            
            try:
                test_url = f"https://api.telegram.org/bot{text}/getMe"
                response = requests.get(test_url, timeout=10)
                
                if response.status_code != 200:
                    await update.message.reply_text(
                        "❌ <b>Invalid bot token or bot not found.</b>\n"
                        "Please check and enter a valid bot token:",
                        parse_mode="HTML"
                    )
                    return
                
                bot_info = response.json()
                if not bot_info.get("ok"):
                    await update.message.reply_text(
                        "❌ <b>Bot token is invalid.</b>\n"
                        "Please enter a valid bot token:",
                        parse_mode="HTML"
                    )
                    return
                
                site_data["bot_token"] = text
                site_data["bot_username"] = bot_info["result"]["username"]
                context.user_data["adding_site"]["step"] = 2
                
                await update.message.reply_text(
                    f"✅ <b>Bot Connected Successfully!</b>\n"
                    f"Bot: @{bot_info['result']['username']}\n\n"
                    "<b>Step 2/5</b>\n\n"
                    "Now enter <b>Chat IDs</b> where OTPs should be sent:\n\n"
                    "<b>Format:</b> Separate multiple IDs with commas\n"
                    "<b>Example:</b> <code>-100123456789, -100987654321, 123456789</code>\n\n"
                    "To get Chat ID:\n"
                    "1. Add your bot to chat/group\n"
                    "2. Send /id command to your bot\n"
                    "3. Copy the Chat ID\n\n"
                    "Enter Chat ID(s):",
                    parse_mode="HTML"
                )
            
            except Exception as e:
                await update.message.reply_text(
                    f"❌ <b>Error testing bot token:</b>\n"
                    f"<code>{html.escape(str(e)[:100])}</code>\n\n"
                    "Please enter a valid bot token:",
                    parse_mode="HTML"
                )
            return
        
        elif step == 2:  # Chat IDs
            try:
                chat_ids = [cid.strip() for cid in text.split(",") if cid.strip()]
                
                for cid in chat_ids:
                    if not (cid.lstrip('-').isdigit() or (cid.startswith('@') and len(cid) > 1)):
                        await update.message.reply_text(
                            f"❌ <b>Invalid Chat ID:</b> <code>{html.escape(cid)}</code>\n"
                            "Chat IDs must be numbers (or start with @ for public channels)\n"
                            "Please enter valid Chat IDs:",
                            parse_mode="HTML"
                        )
                        return
                
                site_data["chat_ids"] = chat_ids
                context.user_data["adding_site"]["step"] = 3
                
                await update.message.reply_text(
                    "✅ <b>Chat IDs Saved!</b>\n\n"
                    "<b>Step 3/5</b>\n\n"
                    "Now enter the <b>AJAX URL</b> to monitor:\n\n"
                    "Example: <code>https://example.com/ajax.php</code>\n"
                    "For INTS SMS: Enter full URL with parameters\n\n"
                    "Enter AJAX URL:",
                    parse_mode="HTML"
                )
            
            except Exception as e:
                await update.message.reply_text(
                    f"❌ <b>Error parsing chat IDs:</b>\n"
                    f"<code>{html.escape(str(e))}</code>\n\n"
                    "Please enter valid Chat IDs:",
                    parse_mode="HTML"
                )
            return
        
        elif step == 3:  # AJAX URL
            if not (text.startswith("http://") or text.startswith("https://")):
                await update.message.reply_text(
                    "❌ <b>Invalid URL format.</b>\n"
                    "URL must start with http:// or https://\n"
                    "Please enter a valid URL:",
                    parse_mode="HTML"
                )
                return
            
            site_data["ajax"] = text
            context.user_data["adding_site"]["step"] = 4
            
            await update.message.reply_text(
                "✅ <b>URL Saved!</b>\n\n"
                "<b>Step 4/5</b>\n\n"
                "Now enter <b>Cookies</b> (if required):\n\n"
                "Format: <code>key1=value1; key2=value2</code>\n"
                "For INTS SMS: <code>PHPSESSID=your_session_id</code>\n\n"
                "Or type /skip if no cookies needed.",
                parse_mode="HTML"
            )
            return
        
        elif step == 4:  # Cookies
            if text.lower() == "/skip":
                site_data["cookies"] = {}
            else:
                cookies = {}
                for cookie in text.split(';'):
                    if '=' in cookie:
                        key, value = cookie.strip().split('=', 1)
                        cookies[key.strip()] = value.strip()
                site_data["cookies"] = cookies
            
            context.user_data["adding_site"]["step"] = 5
            
            await update.message.reply_text(
                "✅ <b>Cookies Saved!</b>\n\n"
                "<b>Step 5/5</b>\n\n"
                "Now enter a <b>name</b> for this site:\n\n"
                "Example: <code>INTS SMS</code> or <code>Amazon OTPs</code>\n\n"
                "Enter site name:",
                parse_mode="HTML"
            )
            return
        
        elif step == 5:  # Site Name
            site_data["name"] = text
            site_data["ajax_type"] = "ints_sms" if "ints/agent" in site_data.get("ajax", "") else "standard"
            
            site_id = add_site(user_id, site_data)
            
            success_text = f"""✅ <b>Site Added Successfully!</b>

<b>Site Details:</b>
• <b>ID:</b> <code>{site_id}</code>
• <b>Name:</b> {html.escape(site_data['name'])}
• <b>Bot:</b> @{html.escape(site_data.get('bot_username', 'N/A'))}
• <b>Chat IDs:</b> {len(site_data['chat_ids'])}
• <b>Type:</b> {site_data['ajax_type']}
• <b>Cookies:</b> {len(site_data.get('cookies', {}))} key(s)"""
            
            await update.message.reply_text(
                success_text,
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            
            del context.user_data["adding_site"]
        
        return
    
    await update.message.reply_text(
        "🤖 <b>AK KING 👑 Bot</b>\n\n"
        "Use the buttons or commands to manage your sites.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# ================= CALLBACK HANDLER =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries - WITH NOOP FIX"""
    query = update.callback_query
    
    try:
        await query.answer()
    except:
        pass
    
    try:
        user_id = query.from_user.id
        data = query.data
        
        # ✅ FIXED: Handle noop callback first
        if data == "noop":
            await query.answer("👤 Just a label", show_alert=False)
            return
        
        # ✅ IMPROVED: Better rate limiting for callbacks
        if "last_callback" in context.user_data:
            elapsed = time.time() - context.user_data["last_callback"]
            if elapsed < 0.8:  # Reduced from 1 to 0.8 for better UX
                return
        context.user_data["last_callback"] = time.time()
        
        logging.info(f"Callback received: {data} from user {user_id}")
        
        # Check admin access
        if data not in ["main_menu", "noop"] and not is_admin(user_id):
            await query.message.edit_text(
                "❌ <b>Access Denied</b>\n\n"
                "You are not authorized to use this bot.\n"
                "Contact the owner for access.",
                parse_mode="HTML"
            )
            return
        
        # Main menu
        if data == "main_menu":
            await query.message.edit_text(
                "🤖 <b>AK KING 👑 - Main Menu</b>",
                parse_mode="HTML",
                reply_markup=main_menu()
            )
        
        # Add site
        elif data == "add_site":
            context.user_data["adding_site"] = {
                "step": 1,
                "data": {
                    "user_id": user_id,
                    "support_url": "t.me/botcasx"
                }
            }
            
            await query.message.edit_text(
                "➕ <b>Add New Site - Step 1/5</b>\n\n"
                "Please enter your <b>Bot Token</b>:\n\n"
                "<b>How to get Bot Token:</b>\n"
                "1. Go to @BotFather\n"
                "2. Send /newbot\n"
                "3. Follow instructions\n"
                "4. Copy the token (format: <code>123456:ABCdef...</code>)\n\n"
                "Enter your bot token:",
                parse_mode="HTML"
            )
        
        # List sites
        elif data == "list_sites":
            if is_owner(user_id):
                sites = list(sites_col.find({}))
            else:
                sites = list(sites_col.find({"user_id": user_id}))
            
            if not sites:
                await query.message.edit_text(
                    "📭 <b>No Sites Found</b>",
                    parse_mode="HTML",
                    reply_markup=main_menu()
                )
                return
            
            keyboard = []
            
            if is_owner(user_id):
                grouped = {}
                
                for site in sites:
                    owner = site.get("owner_username", "unknown")
                    grouped.setdefault(owner, []).append(site)
                
                for owner, owner_sites in grouped.items():
                    keyboard.append([
                        InlineKeyboardButton(
                            f"👤 {owner} ({len(owner_sites)} sites)",
                            callback_data="noop"
                        )
                    ])
                    for site in owner_sites:
                        status = "🟢" if site.get("enabled", True) else "🔴"
                        keyboard.append([
                            InlineKeyboardButton(
                                f"   {status} {site.get('name','Unnamed')}",
                                callback_data=f"view_site_{site['_id']}"
                            )
                        ])
            else:
                for site in sites:
                    status = "🟢" if site.get("enabled", True) else "🔴"
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{status} {site.get('name','Unnamed')}",
                            callback_data=f"view_site_{site['_id']}"
                        )
                    ])
            
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
            
            await query.message.edit_text(
                "📋 <b>Sites Overview</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        # View site
        elif data.startswith("view_site_"):
            site_id = data.replace("view_site_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Site not found or access denied")
                return
            
            status = "🟢 Enabled" if site.get("enabled", True) else "🔴 Disabled"
            stats = site.get("stats", {})
            
            text = f"""📡 <b>Site Details</b>

<b>Name:</b> {html.escape(site.get('name', 'Unnamed'))}
<b>Status:</b> {status}
<b>Bot:</b> @{html.escape(site.get('bot_username', 'N/A'))}
<b>Chat IDs:</b> {len(site.get('chat_ids', []))}
<b>Type:</b> {site.get('ajax_type', 'standard')}
<b>Cookies:</b> {len(site.get('cookies', {}))} key(s)
<b>Buttons:</b> {len(site.get('buttons', []))} configured

<b>Statistics:</b>
• Today: {stats.get('today', 0)}
• Total: {stats.get('total', 0)}
• Errors: {stats.get('errors', 0)}

<b>URL:</b> <code>{html.escape(site.get('ajax', 'N/A')[:50])}...</code>"""
            
            if site.get("last_check"):
                last_check = site["last_check"].strftime("%Y-%m-%d %H:%M:%S")
                text += f"\n<b>Last Check:</b> {last_check}"
            
            await query.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=site_menu(site_id)
            )
        
        # Toggle site
        elif data.startswith("toggle_"):
            site_id = data.replace("toggle_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            new_state = not site.get("enabled", True)
            update_site(site_id, {"enabled": new_state})
            
            status = "✅ enabled" if new_state else "❌ disabled"
            await query.message.edit_text(f"Site {status}")
        
        # Test site
        elif data.startswith("test_"):
            site_id = data.replace("test_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            await query.message.edit_text("🔄 Sending test message...")
            
            logging.info(f"Test message attempt | Site: {site.get('name')} | Bot: {site.get('bot_username')} | Chats: {len(site.get('chat_ids', []))}")
            
            test_message = render_sms(site, {
                "otp": "123456",
                "number": "+4915511850412",
                "message": "This is a test message from AK KING Bot.\n\nYour verification code is 123456\n\nDo not share this code with anyone.",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "service": "WHATSAPP",
                "country": "Germany"
            })
            
            success = send_to_telegram(
                bot_token=site["bot_token"],
                chat_ids=site.get("chat_ids", []),
                text=test_message,
                site=site
            )
            
            if success:
                await query.message.edit_text(
                    "✅ <b>Test Message Sent Successfully!</b>\n\n"
                    "Check your specified chats for the test OTP.\n"
                    "Format used: Custom SMS format\n\n"
                    "<b>Test Details:</b>\n"
                    f"• Bot: @{site.get('bot_username', 'N/A')}\n"
                    f"• Chats: {len(site.get('chat_ids', []))}\n"
                    f"• Buttons: {len(site.get('buttons', []))}\n"
                    f"• Format: HTML",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
                    ])
                )
            else:
                await query.message.edit_text(
                    "❌ <b>Test Message Failed</b>\n\n"
                    "<b>Most Common Causes:</b>\n"
                    "1. Bot token invalid/expired\n"
                    "2. Bot not added to chat(s) as admin\n"
                    "3. Chat IDs incorrect\n"
                    "4. Bot privacy mode enabled\n"
                    "5. Channel: Bot not admin\n\n"
                    "<b>Check Logs for exact Telegram API error.</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🔄 Retry Test", callback_data=f"test_{site_id}"),
                            InlineKeyboardButton("🔧 Edit Token", callback_data=f"token_{site_id}")
                        ],
                        [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
                    ])
                )
        
        # SMS Format editor
        elif data.startswith("format_"):
            site_id = data.replace("format_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            context.user_data["edit_format"] = site_id
            context.user_data["edit_format_step"] = "get_format"
            
            current_format = site.get("sms_format", {}).get("template", DEFAULT_SMS_FORMAT)
            
            help_text = """✏️ <b>Edit SMS Format</b>

<b>Current Format:</b>
<pre>{}</pre>

<b>Available Variables:</b>
• <code>{{otp}}</code> - The OTP code
• <code>{{number}}</code> - Phone number
• <code>{{message}}</code> - Full SMS message
• <code>{{time}}</code> - Received time
• <code>{{service}}</code> - Service name
• <code>{{country}}</code> - Country

<b>HTML Formatting:</b>
• Use &lt;b&gt;bold&lt;/b&gt;
• Use &lt;code&gt;monospace&lt;/code&gt;
• Use &lt;i&gt;italic&lt;/i&gt;

Send your new format now:""".format(html.escape(current_format[:500] + ("..." if len(current_format) > 500 else "")))
            
            await query.message.edit_text(
                help_text,
                parse_mode="HTML"
            )
        
        # Button management
        elif data.startswith("buttons_"):
            site_id = data.replace("buttons_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            buttons = site.get("buttons", DEFAULT_BUTTONS)
            
            keyboard = []
            for i, btn in enumerate(buttons):
                status = "✅" if btn.get("enabled", True) else "❌"
                keyboard.append([
                    InlineKeyboardButton(
                        f"{status} {btn.get('text', f'Button {i+1}')}",
                        callback_data=f"editbtn_{site_id}_{i}"
                    )
                ])
            
            keyboard.append([
                InlineKeyboardButton("➕ Add New Button", callback_data=f"addbtn_{site_id}"),
                InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")
            ])
            
            await query.message.edit_text(
                f"🔘 <b>Button Management</b>\n\n"
                f"Site: {html.escape(site.get('name', 'Unknown'))}\n\n"
                f"<b>Current Buttons ({len(buttons)}):</b>\n"
                f"Click on a button to edit it.\n\n"
                f"<b>Note:</b> Max 4 buttons, 2 per row.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        # Edit specific button
        elif data.startswith("editbtn_"):
            parts = data.split("_")
            if len(parts) >= 3:
                site_id = parts[1]
                btn_index = int(parts[2])
                
                site = get_site(site_id)
                if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                    await query.message.edit_text("❌ Access denied")
                    return
                
                buttons = site.get("buttons", DEFAULT_BUTTONS)
                if btn_index >= len(buttons):
                    await query.message.edit_text("❌ Button not found")
                    return
                
                btn = buttons[btn_index]
                
                keyboard = [
                    [
                        InlineKeyboardButton("📝 Edit Text", callback_data=f"btntext_{site_id}_{btn_index}"),
                        InlineKeyboardButton("🔗 Edit URL", callback_data=f"btnurl_{site_id}_{btn_index}")
                    ],
                    [
                        InlineKeyboardButton(
                            "✅ Enabled" if btn.get("enabled", True) else "❌ Disabled",
                            callback_data=f"btntoggle_{site_id}_{btn_index}"
                        )
                    ],
                    [
                        InlineKeyboardButton("🗑 Delete Button", callback_data=f"btndelete_{site_id}_{btn_index}"),
                        InlineKeyboardButton("🔙 Back", callback_data=f"buttons_{site_id}")
                    ]
                ]
                
                await query.message.edit_text(
                    f"🔧 <b>Edit Button</b>\n\n"
                    f"<b>Text:</b> {btn.get('text', 'Not set')}\n"
                    f"<b>URL:</b> {btn.get('url', 'Not set')}\n"
                    f"<b>Status:</b> {'✅ Enabled' if btn.get('enabled', True) else '❌ Disabled'}\n\n"
                    f"Select an action:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        
        # Toggle button
        elif data.startswith("btntoggle_"):
            parts = data.split("_")
            if len(parts) >= 3:
                site_id = parts[1]
                btn_index = int(parts[2])
                
                site = get_site(site_id)
                if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                    await query.message.edit_text("❌ Access denied")
                    return
                
                buttons = site.get("buttons", DEFAULT_BUTTONS).copy()
                if btn_index < len(buttons):
                    buttons[btn_index]["enabled"] = not buttons[btn_index].get("enabled", True)
                    update_site(site_id, {"buttons": buttons})
                    
                    await query.message.edit_text(
                        "✅ Button status updated",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data=f"buttons_{site_id}")]
                        ])
                    )
        
        # Edit button text
        elif data.startswith("btntext_"):
            parts = data.split("_")
            if len(parts) >= 3:
                site_id = parts[1]
                btn_index = int(parts[2])
                
                site = get_site(site_id)
                if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                    await query.message.edit_text("❌ Access denied")
                    return
                
                context.user_data["edit_button_text"] = {
                    "site_id": site_id,
                    "btn_index": btn_index
                }
                
                await query.message.edit_text(
                    "📝 <b>Edit Button Text</b>\n\n"
                    "Enter the new text for this button:\n\n"
                    "Max length: 20 characters",
                    parse_mode="HTML"
                )
        
        # Edit button URL
        elif data.startswith("btnurl_"):
            parts = data.split("_")
            if len(parts) >= 3:
                site_id = parts[1]
                btn_index = int(parts[2])
                
                site = get_site(site_id)
                if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                    await query.message.edit_text("❌ Access denied")
                    return
                
                context.user_data["edit_button_url"] = {
                    "site_id": site_id,
                    "btn_index": btn_index
                }
                
                await query.message.edit_text(
                    "🔗 <b>Edit Button URL</b>\n\n"
                    "Enter the new URL for this button:\n\n"
                    "Supported formats:\n"
                    "• https://example.com\n"
                    "• tg://resolve?domain=username\n"
                    "• t.me/username",
                    parse_mode="HTML"
                )
        
        # Add new button
        elif data.startswith("addbtn_"):
            site_id = data.replace("addbtn_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            buttons = site.get("buttons", DEFAULT_BUTTONS).copy()
            
            if len(buttons) >= 4:
                await query.message.edit_text(
                    "❌ <b>Maximum buttons reached</b>\n\n"
                    "You can only have up to 4 buttons.\n"
                    "Delete a button first to add new one.",
                    parse_mode="HTML"
                )
                return
            
            buttons.append({
                "text": "New Button",
                "url": "https://example.com",
                "enabled": True
            })
            
            update_site(site_id, {"buttons": buttons})
            
            await query.message.edit_text(
                "✅ New button added",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"buttons_{site_id}")]
                ])
            )
        
        # Delete button
        elif data.startswith("btndelete_"):
            parts = data.split("_")
            if len(parts) >= 3:
                site_id = parts[1]
                btn_index = int(parts[2])
                
                site = get_site(site_id)
                if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                    await query.message.edit_text("❌ Access denied")
                    return
                
                buttons = site.get("buttons", DEFAULT_BUTTONS).copy()
                if btn_index < len(buttons):
                    del buttons[btn_index]
                    update_site(site_id, {"buttons": buttons})
                    
                    await query.message.edit_text(
                        "✅ <b>Button Deleted</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data=f"buttons_{site_id}")]
                        ])
                    )
        
        # Change bot token
        elif data.startswith("token_"):
            site_id = data.replace("token_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            context.user_data["edit_bot_token"] = site_id
            
            await query.message.edit_text(
                "🔑 <b>Change Bot Token</b>\n\n"
                "Please send the <b>new bot token</b> now.\n\n"
                "Format:\n"
                "<code>123456789:ABCdefGhIJKlmNOP</code>",
                parse_mode="HTML"
            )
        
        # Delete site with confirmation
        elif data.startswith("delete_"):
            site_id = data.replace("delete_", "")
            site = get_site(site_id)
            
            if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                await query.message.edit_text("❌ Access denied")
                return
            
            context.user_data["confirm_delete"] = site_id
            
            await query.message.edit_text(
                f"⚠️ <b>CONFIRM DELETE</b>\n\n"
                f"Are you sure you want to delete this site?\n\n"
                f"<b>Name:</b> {html.escape(site.get('name','Unknown'))}\n"
                f"<b>Bot:</b> @{html.escape(site.get('bot_username','N/A'))}\n\n"
                f"❗ <b>This action CANNOT be undone.</b>\n\n"
                f"Please type <code>DELETE</code> to confirm deletion.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ CANCEL", callback_data=f"view_site_{site_id}")]
                ])
            )
        
        # Help
        elif data == "help":
            help_text = """🆘 <b>How to Use This Bot</b>

<b>Step 1 - Create Your Bot:</b>
1. Go to @BotFather on Telegram
2. Send /newbot command
3. Follow instructions
4. Copy the bot token

<b>Step 2 - Add Your Site:</b>
1. Click "Add New Site"
2. Enter your bot token
3. Add chat IDs (where OTPs should go)
4. Enter AJAX URL to monitor
5. Set site name

<b>Step 3 - Get Chat IDs:</b>
• For personal chat: Send /id to your bot
• For group: Add your bot to group, then send /id in group

<b>Step 4 - For INTS SMS Sites:</b>
• Enter your PHPSESSID cookie
• Use INTS SMS format URL

<b>Step 5 - Customization:</b>
• Edit SMS format per site
• Edit inline buttons per site
• Manage admins (owner only)

<b>Support:</b> @botcasx"""
            
            await query.message.edit_text(
                help_text,
                parse_mode="HTML",
                reply_markup=back_to_main_menu()
            )
        
        # Statistics
        elif data == "stats":
            sites = get_user_sites(user_id)
            
            if not sites:
                await query.message.edit_text("📭 No sites found")
                return
            
            total_sites = len(sites)
            active_sites = len([s for s in sites if s.get("enabled", True)])
            total_today = sum(s.get("stats", {}).get("today", 0) for s in sites)
            total_all = sum(s.get("stats", {}).get("total", 0) for s in sites)
            
            text = f"""📊 <b>Your Statistics</b>

<b>Sites:</b>
• Total: {total_sites}
• Active: {active_sites}

<b>OTPs Today:</b> {total_today}
<b>OTPs Total:</b> {total_all}

<b>Top Sites:</b>"""
            
            sorted_sites = sorted(sites, key=lambda x: x.get("stats", {}).get("total", 0), reverse=True)[:5]
            
            for i, site in enumerate(sorted_sites, 1):
                name = site.get("name", f"Site-{site['_id'][-6:]}")
                today = site.get("stats", {}).get("today", 0)
                total = site.get("stats", {}).get("total", 0)
                text += f"\n{i}. {html.escape(name)}: {today} today, {total} total"
            
            await query.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=back_to_main_menu()
            )
        
        # Handle other callbacks
        elif data.startswith("chats_") or data.startswith("cookies_") or data.startswith("headers_") or data.startswith("site_stats_"):
            parts = data.split("_")
            if len(parts) >= 2:
                site_id = parts[1]
                site = get_site(site_id)
                
                if not site or (not is_owner(user_id) and site["user_id"] != user_id):
                    await query.message.edit_text("❌ Access denied")
                    return
                
                if data.startswith("chats_"):
                    await query.message.edit_text(
                        f"💬 <b>Manage Chats for {html.escape(site.get('name', 'Site'))}</b>\n\n"
                        "Current Chat IDs:\n"
                        f"{chr(10).join([f'• <code>{cid}</code>' for cid in site.get('chat_ids', [])])}\n\n"
                        "To modify chat IDs, edit the site settings.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
                        ])
                    )
                elif data.startswith("cookies_"):
                    cookies = site.get("cookies", {})
                    cookies_text = "\n".join([f"• <code>{k}={v}</code>" for k, v in cookies.items()]) if cookies else "No cookies set"
                    await query.message.edit_text(
                        f"🍪 <b>Cookies for {html.escape(site.get('name', 'Site'))}</b>\n\n"
                        f"{cookies_text}\n\n"
                        "To edit cookies, you need to recreate the site.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
                        ])
                    )
                else:
                    await query.message.edit_text(
                        "⚠️ <b>Feature Coming Soon</b>\n\n"
                        "This feature is not fully implemented yet.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
                        ])
                    )
    
    except Exception as e:
        logging.error(f"Error in callback handler: {str(e)}", exc_info=True)
        await query.message.edit_text(
            f"❌ <b>Error occurred</b>\n\n"
            f"<code>{html.escape(str(e)[:200])}</code>",
            parse_mode="HTML"
        )

# ================= ✅ ENHANCED: POLLER WITH SESSION CLEANUP =================

def poller_sync():
    """Main polling loop - WITH SESSION CLEANUP"""
    global LAST_RESET
    
    while True:
        try:
            # Optimized daily reset
            now = datetime.utcnow()
            if not LAST_RESET or now.date() != LAST_RESET.date():
                reset_daily_stats()
                LAST_RESET = now
                logging.info(f"✅ Daily stats reset at {now}")
            
            sites = list(sites_col.find({"enabled": True}))
            
            # ✅ ADDED: Clean up sessions for sites that are no longer enabled
            active_ids = set(s["_id"] for s in sites)
            for sid in list(SITE_SESSIONS.keys()):
                if sid not in active_ids:
                    SITE_SESSIONS.pop(sid, None)
                    logging.debug(f"Cleaned up session for inactive site: {sid}")
            
            for site in sites:
                try:
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$set": {"last_check": datetime.utcnow()}}
                    )
                    
                    if site["_id"] not in SITE_SESSIONS:
                        SITE_SESSIONS[site["_id"]] = get_site_session(site)
                    
                    session = SITE_SESSIONS[site["_id"]]
                    
                    if site.get("ajax_type") == "ints_sms":
                        url = site["ajax"]
                        
                        response = session.get(
                            url,
                            headers=session.headers,
                            cookies=session.cookies,
                            timeout=20
                        )
                        
                        content_type = response.headers.get("Content-Type", "").lower()
                        response_text = response.text.lower()
                        
                        if "text/html" in content_type and "<html" in response_text:
                            logging.warning(f"⚠️ Session expired for {site.get('name')} - Got HTML login page")
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            if site["_id"] in SITE_SESSIONS:
                                del SITE_SESSIONS[site["_id"]]
                            continue
                        
                        if response.status_code != 200:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        try:
                            data = response.json()
                        except json.JSONDecodeError as e:
                            logging.error(f"JSON decode error for {site.get('name')}: {str(e)}")
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        rows = data.get("aaData", [])
                        if not rows:
                            continue
                        
                        valid_rows = []
                        for row in rows:
                            if not row or not isinstance(row, list) or len(row) < 6:
                                continue
                            if not row[0] or not isinstance(row[0], str):
                                continue
                            if not re.match(r"\d{4}-\d{2}-\d{2}", row[0]):
                                continue
                            valid_rows.append(row)
                        
                        if not valid_rows:
                            continue
                        
                        valid_rows.sort(
                            key=lambda x: datetime.strptime(x[0], "%Y-%m-%d %H:%M:%S"),
                            reverse=True
                        )
                        
                        newest = valid_rows[0]
                        uid = newest[0] + (newest[2] or "") + (newest[5] or "")
                        
                        if site.get("last_uid") == uid:
                            continue
                        
                        date = newest[0]
                        route_raw = newest[1] or "Unknown"
                        number = newest[2] or ""
                        service = newest[3] or "Unknown"
                        message = newest[5] or ""
                        
                        otp = extract_otp(message)
                        if otp == "N/A":
                            continue
                        
                        formatted_message = render_sms(site, {
                            "otp": otp,
                            "number": number,
                            "message": message,
                            "date": date,
                            "service": service,
                            "country": route_raw.split("-")[0] if "-" in route_raw else route_raw
                        })
                        
                        success = send_to_telegram(
                            bot_token=site["bot_token"],
                            chat_ids=site.get("chat_ids", []),
                            text=formatted_message,
                            site=site
                        )
                        
                        if success:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {
                                    "$set": {
                                        "last_uid": uid,
                                        "last_success": datetime.utcnow()
                                    },
                                    "$inc": {
                                        "stats.today": 1,
                                        "stats.total": 1
                                    }
                                }
                            )
                            
                            logging.info(f"✅ OTP sent for site {site.get('name')}")
                        else:
                            logging.error(f"❌ Failed to send OTP for site {site.get('name')}")
                    
                    else:
                        url = site["ajax"]
                        response = session.get(
                            url,
                            headers=session.headers,
                            cookies=session.cookies,
                            timeout=15
                        )
                        
                        content_type = response.headers.get("Content-Type", "").lower()
                        response_text = response.text.lower()
                        
                        if "text/html" in content_type and "<html" in response_text:
                            logging.warning(f"⚠️ HTML login page for {site.get('name')}")
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            if site["_id"] in SITE_SESSIONS:
                                del SITE_SESSIONS[site["_id"]]
                            continue
                        
                        if response.status_code != 200:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        try:
                            data = response.json()
                        except json.JSONDecodeError as e:
                            logging.error(f"JSON decode error for {site.get('name')}: {str(e)}")
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        rows = data.get("aaData", [])
                        if not rows:
                            continue
                        
                        latest_row = rows[0]
                        row_id = str(latest_row)
                        
                        if site.get("last_uid") == row_id:
                            continue
                        
                        if isinstance(latest_row, list):
                            message = latest_row[-1] if len(latest_row) > 2 else str(latest_row)
                            phone_number = latest_row[2] if len(latest_row) > 2 else ""
                            timestamp = latest_row[0] if latest_row else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            message = str(latest_row)
                            phone_number = ""
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        otp = extract_otp(message)
                        if otp == "N/A":
                            continue
                        
                        formatted_message = render_sms(site, {
                            "otp": otp,
                            "number": phone_number,
                            "message": message,
                            "date": timestamp,
                            "service": site.get("name", "Unknown Service"),
                            "country": get_country_from_number(phone_number)
                        })
                        
                        success = send_to_telegram(
                            bot_token=site["bot_token"],
                            chat_ids=site.get("chat_ids", []),
                            text=formatted_message,
                            site=site
                        )
                        
                        if success:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {
                                    "$set": {
                                        "last_uid": row_id,
                                        "last_success": datetime.utcnow()
                                    },
                                    "$inc": {
                                        "stats.today": 1,
                                        "stats.total": 1
                                    }
                                }
                            )
                            
                            logging.info(f"✅ OTP sent for site {site.get('name')}")
                        else:
                            logging.error(f"❌ Failed to send OTP for site {site.get('name')}")
                
                except Exception as e:
                    logging.error(f"Error polling site {site.get('name', site['_id'])}: {str(e)}")
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$inc": {"stats.errors": 1}}
                    )
            
            time.sleep(max(7, CHECK_INTERVAL))
        
        except Exception as e:
            logging.error(f"Poller error: {str(e)}")
            time.sleep(30)

def start_poller_thread():
    """Start poller in a separate thread"""
    poller_thread = threading.Thread(target=poller_sync, daemon=True)
    poller_thread.start()
    logging.info("Poller thread started")

# ================= MAIN =================

def main():
    """Main function"""
    if not MASTER_BOT_TOKEN:
        print("❌ Error: MASTER_BOT_TOKEN not set!")
        print("Please set MASTER_BOT_TOKEN in environment variables")
        exit(1)
    
    if OWNER_ID == 0:
        print("❌ Error: OWNER_ID not set in environment!")
        print("Please set OWNER_ID in environment variables")
        exit(1)
    
    logging.info(f"Starting AK KING 👑 bot for owner {OWNER_ID}...")
    
    try:
        app = ApplicationBuilder()\
            .token(MASTER_BOT_TOKEN)\
            .connection_pool_size(10)\
            .pool_timeout(30)\
            .connect_timeout(10)\
            .read_timeout(10)\
            .write_timeout(10)\
            .build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("id", my_id))
        
        app.add_handler(CommandHandler("addadmin", add_admin))
        app.add_handler(CommandHandler("removeadmin", remove_admin))
        app.add_handler(CommandHandler("listadmins", list_admins))
        app.add_handler(CommandHandler("access", check_access))
        
        app.add_handler(CallbackQueryHandler(callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
        
        start_poller_thread()
        
        logging.info("Bot is starting polling...")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}", exc_info=True)
        exit(1)

if __name__ == "__main__":
    main()
