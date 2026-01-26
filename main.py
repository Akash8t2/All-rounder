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
    InputFile,
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

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN")  # Yeh wala bot admin panel ke liye
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
CHECK_INTERVAL = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ================= DB =================

mongo = MongoClient(MONGO_URI)
db = mongo["master_bot"]
sites_col = db["sites"]
users_col = db["users"]

# ================= HELPER FUNCTIONS =================

def extract_otp(text: str) -> str:
    """Extract OTP from text"""
    if not text:
        return "N/A"
    
    patterns = [
        r'\b(\d{3,8})\b',
        r'OTP[:\s]*(\d{3,8})',
        r'code[:\s]*(\d{3,8})',
        r'(\d{3,8})[\s]*is your',
        r'(\d{3,8})[\s]*code'
    ]
    
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    
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
    
    # Simple country detection based on prefix
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
    }
    
    for prefix, country in prefixes.items():
        if number.startswith(prefix):
            return country
    
    return "🌍 International"

def format_otp_message(otp: str, number: str, message: str, date: str, site_name: str) -> str:
    """Format OTP message as per requirement - Use HTML to avoid Markdown issues"""
    masked_number = mask_phone_number(number)
    country = get_country_from_number(number)
    
    # Escape HTML special characters
    safe_message = html.escape(message)
    safe_site_name = html.escape(site_name)
    
    return (
        "📩 <b>LIVE OTP RECEIVED</b>\n\n"
        f"📞 <b>Number:</b> <code>{masked_number}</code>\n"
        f"🔢 <b>OTP:</b> 🔥 <code>{otp}</code> 🔥\n"
        f"🏷 <b>Service:</b> {safe_site_name}\n"
        f"🌍 <b>Country:</b> {country}\n"
        f"🕒 <b>Time:</b> {date}\n\n"
        f"💬 <b>SMS:</b>\n{safe_message}\n\n"
        "⚡ <b>—͟͟͞͞𝗔𝗞𝗔𝗦𝗛 🥀</b>"
    )

def send_to_telegram(bot_token: str, chat_ids: List[str], text: str, owner_url: str = "", support_url: str = "t.me/botcasx"):
    """Send message to Telegram using bot token - Use HTML parse mode"""
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            # Prepare inline keyboard
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Owner", "url": owner_url} if owner_url else {"text": "Owner", "url": "t.me/username"},
                        {"text": "🆘 Support", "url": support_url}
                    ]
                ]
            }
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": json.dumps(reply_markup)
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to send to chat {chat_id}: {response.text}")
        
        except Exception as e:
            logging.error(f"Error sending to Telegram: {str(e)}")

def safe_json_parse(text: str):
    """Safely parse JSON"""
    try:
        return json.loads(text)
    except:
        return None

# ================= SITE MANAGEMENT =================

def add_site(user_id: int, site_data: Dict) -> str:
    """Add new site for user"""
    site_id = str(int(time.time() * 1000))
    
    # Ensure chat_ids is a list
    chat_ids = site_data.get("chat_ids", [])
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]
    
    site_data.update({
        "_id": site_id,
        "user_id": user_id,
        "chat_ids": chat_ids,
        "enabled": True,
        "created_at": datetime.utcnow(),
        "last_check": None,
        "last_uid": None,
        "stats": {
            "today": 0,
            "total": 0,
            "errors": 0,
            "last_success": None
        },
        "default_format": True,  # Use our default format
        "owner_url": site_data.get("owner_url", ""),
        "support_url": site_data.get("support_url", "t.me/botcasx")
    })
    
    sites_col.insert_one(site_data)
    return site_id

def get_user_sites(user_id: int) -> List[Dict]:
    """Get all sites for a user"""
    return list(sites_col.find({"user_id": user_id}))

def get_site(site_id: str) -> Optional[Dict]:
    """Get site by ID"""
    return sites_col.find_one({"_id": site_id})

def update_site(site_id: str, update_data: Dict) -> bool:
    """Update site data properly with MongoDB operators"""
    # Check if this is an operator update (starts with $) or a simple set
    if any(key.startswith('$') for key in update_data.keys()):
        # It's already an operator update
        update_doc = update_data
    else:
        # Convert to $set operator
        update_doc = {"$set": update_data}
    
    result = sites_col.update_one(
        {"_id": site_id},
        update_doc
    )
    return result.modified_count > 0

def delete_site(site_id: str) -> bool:
    """Delete site"""
    result = sites_col.delete_one({"_id": site_id})
    return result.deleted_count > 0

def add_chat_to_site(site_id: str, chat_id: str) -> bool:
    """Add chat ID to site"""
    site = get_site(site_id)
    if not site:
        return False
    
    chat_ids = site.get("chat_ids", [])
    if chat_id not in chat_ids:
        chat_ids.append(chat_id)
        return update_site(site_id, {"chat_ids": chat_ids})
    
    return True

def remove_chat_from_site(site_id: str, chat_id: str) -> bool:
    """Remove chat ID from site"""
    site = get_site(site_id)
    if not site:
        return False
    
    chat_ids = site.get("chat_ids", [])
    if chat_id in chat_ids:
        chat_ids.remove(chat_id)
        return update_site(site_id, {"chat_ids": chat_ids})
    
    return True

# ================= MENUS =================

def main_menu():
    """Main menu"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add New Site", callback_data="add_site")],
        [InlineKeyboardButton("📋 My Sites", callback_data="list_sites")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("🆘 Help", callback_data="help")]
    ])

def site_menu(site_id: str):
    """Site management menu"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔘 Toggle ON/OFF", callback_data=f"toggle:{site_id}"),
            InlineKeyboardButton("💬 Manage Chats", callback_data=f"chats:{site_id}")
        ],
        [
            InlineKeyboardButton("🍪 Edit Cookies", callback_data=f"cookies:{site_id}"),
            InlineKeyboardButton("📝 Edit Headers", callback_data=f"headers:{site_id}")
        ],
        [
            InlineKeyboardButton("🔄 Test Site", callback_data=f"test:{site_id}"),
            InlineKeyboardButton("📊 Stats", callback_data=f"site_stats:{site_id}")
        ],
        [
            InlineKeyboardButton("✏️ Edit Bot Token", callback_data=f"token:{site_id}"),
            InlineKeyboardButton("🗑 Delete Site", callback_data=f"delete:{site_id}")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="list_sites")]
    ])

def back_to_main_menu():
    """Back to main menu button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])

# ================= COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler - Use HTML instead of Markdown"""
    user_id = update.effective_user.id
    
    # Check if user exists
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({
            "user_id": user_id,
            "username": update.effective_user.username,
            "first_name": update.effective_user.first_name,
            "joined_at": datetime.utcnow()
        })
    
    welcome_text = """
🤖 <b>AK KING 👑 - OTP Forwarder Bot</b>

<b>Features:</b>
• Use your own bot token
• Multiple chat IDs per site
• Live OTP forwarding
• Default professional format
• Cookie & header management

<b>Quick Start:</b>
1. Create your own bot via @BotFather
2. Get your bot token
3. Add site using this bot
4. Start receiving OTPs!

Use the buttons below to get started.
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command - Use HTML instead of Markdown"""
    help_text = """
🆘 <b>How to Use This Bot</b>

<b>Step 1 - Create Your Bot:</b>
1. Go to @BotFather on Telegram
2. Send /newbot command
3. Follow instructions
4. Copy the bot token (like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)

<b>Step 2 - Add Your Site:</b>
1. Click "Add New Site"
2. Enter your bot token
3. Add chat IDs (where OTPs should go)
4. Enter AJAX URL to monitor
5. Set site name

<b>Step 3 - Get Chat IDs:</b>
• For personal chat: Send /id to your bot
• For group: Add your bot to group, then send /id in group

<b>Step 4 - Multiple Chats:</b>
You can add multiple chat IDs separated by commas:
Example: -100123456789, -100987654321, 123456789

<b>Features:</b>
• Each site uses its own bot token
• OTPs go to specified chat IDs
• Professional message format
• Real-time forwarding

<b>Support:</b> @botcasx
"""
    
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        reply_markup=back_to_main_menu()
    )

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get chat ID - Use HTML instead of Markdown"""
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

# ================= TEXT MESSAGE HANDLER =================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages - Use HTML to avoid Markdown issues"""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Check if user is in add site flow
    if "adding_site" in context.user_data:
        step = context.user_data["adding_site"]["step"]
        site_data = context.user_data["adding_site"]["data"]
        
        if step == 1:  # Bot Token
            # Validate bot token format
            if ":" not in text or len(text) < 30:
                await update.message.reply_text(
                    "❌ <b>Invalid bot token format.</b>\n\n"
                    "Bot token should look like: <code>123456789:ABCdefGHIjklMnopQRstUvWXyz</code>\n\n"
                    "Please enter a valid bot token:",
                    parse_mode="HTML"
                )
                return
            
            # Test the bot token
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
                    "<b>Step 2/4</b>\n\n"
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
                error_msg = html.escape(str(e))
                await update.message.reply_text(
                    f"❌ <b>Error testing bot token:</b>\n"
                    f"<code>{error_msg[:100]}</code>\n\n"
                    "Please enter a valid bot token:",
                    parse_mode="HTML"
                )
            return
        
        elif step == 2:  # Chat IDs
            try:
                # Parse comma-separated chat IDs
                chat_ids = [cid.strip() for cid in text.split(",") if cid.strip()]
                
                # Validate each chat ID is numeric
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
                    "<b>Step 3/4</b>\n\n"
                    "Now enter the <b>AJAX URL</b> to monitor:\n\n"
                    "Example: <code>https://example.com/ajax.php</code>\n\n"
                    "This URL should return JSON data with OTP information.",
                    parse_mode="HTML"
                )
            
            except Exception as e:
                error_msg = html.escape(str(e))
                await update.message.reply_text(
                    f"❌ <b>Error parsing chat IDs:</b>\n"
                    f"<code>{error_msg}</code>\n\n"
                    "Please enter valid Chat IDs:",
                    parse_mode="HTML"
                )
            return
        
        elif step == 3:  # AJAX URL
            # Basic URL validation
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
                "<b>Step 4/4</b>\n\n"
                "Now enter a <b>name</b> for this site:\n\n"
                "Example: <code>Amazon OTPs</code> or <code>Gmail Verification</code>\n\n"
                "This name will appear in OTP messages.",
                parse_mode="HTML"
            )
            return
        
        elif step == 4:  # Site Name
            site_data["name"] = text
            
            # Ask for Owner URL (optional)
            context.user_data["adding_site"]["step"] = 5
            
            await update.message.reply_text(
                "✅ <b>Site Name Saved!</b>\n\n"
                "<b>Optional Step</b>\n\n"
                "Enter Owner URL (optional):\n\n"
                "Example: <code>t.me/yourusername</code>\n"
                "This will appear in the OTP message buttons.\n\n"
                "Or type /skip to use default.",
                parse_mode="HTML"
            )
            return
        
        elif step == 5:  # Owner URL
            if text.lower() == "/skip":
                site_data["owner_url"] = ""
            else:
                site_data["owner_url"] = text
            
            # Add the site to database
            site_id = add_site(user_id, site_data)
            
            # Get site info
            site = get_site(site_id)
            
            # Send success message
            success_text = f"""
✅ <b>Site Added Successfully!</b>

<b>Site Details:</b>
• <b>ID:</b> <code>{site_id}</code>
• <b>Name:</b> {html.escape(site_data['name'])}
• <b>Bot:</b> @{html.escape(site_data.get('bot_username', 'N/A'))}
• <b>Chat IDs:</b> {len(site_data['chat_ids'])}
• <b>URL:</b> <code>{html.escape(site_data['ajax'])}</code>

<b>Next Steps:</b>
1. Make sure your bot is added to all chats
2. Test the site using "Test Site" button
3. Enable site to start receiving OTPs

OTPs will be sent using your bot with this format:
"""
            success_text += format_otp_message("123456", "9876543210", "Your verification code is 123456", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), site_data['name'])
            
            await update.message.reply_text(
                success_text[:4000],  # Telegram limit
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            
            # Clear adding state
            del context.user_data["adding_site"]
        
        return
    
    # Handle other text inputs based on context
    await update.message.reply_text(
        "🤖 AK KING 👑 Bot\n\n"
        "Use the buttons or commands to manage your sites.",
        reply_markup=main_menu()
    )

# ================= CALLBACK HANDLER =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
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
            "➕ <b>Add New Site - Step 1/4</b>\n\n"
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
        sites = get_user_sites(user_id)
        
        if not sites:
            await query.message.edit_text(
                "📭 <b>No Sites Found</b>\n\n"
                "You haven't added any sites yet.\n"
                "Click 'Add New Site' to get started.",
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            return
        
        keyboard = []
        for site in sites:
            status = "🟢" if site.get("enabled", True) else "🔴"
            name = site.get("name", f"Site-{site['_id'][-6:]}")
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {name}",
                    callback_data=f"view_site:{site['_id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        
        await query.message.edit_text(
            f"📋 <b>Your Sites ({len(sites)})</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # View site
    elif data.startswith("view_site:"):
        site_id = data.split(":", 1)[1]
        site = get_site(site_id)
        
        if not site or site["user_id"] != user_id:
            await query.message.edit_text("❌ Site not found or access denied")
            return
        
        status = "🟢 Enabled" if site.get("enabled", True) else "🔴 Disabled"
        stats = site.get("stats", {})
        
        text = f"""
📡 <b>Site Details</b>

<b>Name:</b> {html.escape(site.get('name', 'Unnamed'))}
<b>Status:</b> {status}
<b>Bot:</b> @{html.escape(site.get('bot_username', 'N/A'))}
<b>Chat IDs:</b> {len(site.get('chat_ids', []))}

<b>Statistics:</b>
• Today: {stats.get('today', 0)}
• Total: {stats.get('total', 0)}
• Errors: {stats.get('errors', 0)}

<b>URL:</b> <code>{html.escape(site.get('ajax', 'N/A'))}</code>
"""
        
        if site.get("last_check"):
            last_check = site["last_check"].strftime("%Y-%m-%d %H:%M:%S")
            text += f"<b>Last Check:</b> {last_check}\n"
        
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=site_menu(site_id)
        )
    
    # Toggle site
    elif data.startswith("toggle:"):
        site_id = data.split(":", 1)[1]
        site = get_site(site_id)
        
        if not site or site["user_id"] != user_id:
            await query.message.edit_text("❌ Access denied")
            return
        
        new_state = not site.get("enabled", True)
        update_site(site_id, {"enabled": new_state})
        
        status = "enabled ✅" if new_state else "disabled 🔴"
        await query.message.edit_text(f"✅ Site {status}")
    
    # Manage chats
    elif data.startswith("chats:"):
        site_id = data.split(":", 1)[1]
        site = get_site(site_id)
        
        if not site or site["user_id"] != user_id:
            await query.message.edit_text("❌ Access denied")
            return
        
        chat_ids = site.get("chat_ids", [])
        
        keyboard = [
            [InlineKeyboardButton("➕ Add Chat ID", callback_data=f"add_chat:{site_id}")],
            [InlineKeyboardButton("🗑 Remove Chat ID", callback_data=f"remove_chat:{site_id}")]
        ]
        
        if chat_ids:
            text = "💬 <b>Current Chat IDs:</b>\n\n"
            for i, cid in enumerate(chat_ids, 1):
                text += f"{i}. <code>{html.escape(cid)}</code>\n"
        else:
            text = "📭 <b>No Chat IDs</b>\n\nAdd chat IDs to receive OTPs."
        
        text += f"\n\n<b>Current Bot:</b> @{html.escape(site.get('bot_username', 'N/A'))}"
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"view_site:{site_id}")])
        
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # Test site
    elif data.startswith("test:"):
        site_id = data.split(":", 1)[1]
        site = get_site(site_id)
        
        if not site or site["user_id"] != user_id:
            await query.message.edit_text("❌ Access denied")
            return
        
        # Send test message
        test_message = format_otp_message(
            otp="123456",
            number="9876543210",
            message="This is a test message. Your verification code is 123456",
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            site_name=site.get("name", "Test Site")
        )
        
        try:
            send_to_telegram(
                bot_token=site["bot_token"],
                chat_ids=site.get("chat_ids", []),
                text=test_message,
                owner_url=site.get("owner_url", ""),
                support_url=site.get("support_url", "t.me/botcasx")
            )
            
            await query.message.edit_text(
                "✅ <b>Test Message Sent!</b>\n\n"
                "Check your specified chats for the test OTP.\n\n"
                "If you didn't receive:\n"
                "1. Check if bot is added to chats\n"
                "2. Verify chat IDs are correct\n"
                "3. Ensure bot has permission to send messages",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"view_site:{site_id}")]
                ])
            )
        
        except Exception as e:
            await query.message.edit_text(
                f"❌ <b>Test Failed</b>\n\nError: {html.escape(str(e))}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"view_site:{site_id}")]
                ])
            )
    
    # Help
    elif data == "help":
        await help_command(update, context)
    
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
        
        text = f"""
📊 <b>Your Statistics</b>

<b>Sites:</b>
• Total: {total_sites}
• Active: {active_sites}

<b>OTPs Today:</b> {total_today}
<b>OTPs Total:</b> {total_all}

<b>Top Sites:</b>
"""
        
        # Sort by total OTPs
        sorted_sites = sorted(sites, key=lambda x: x.get("stats", {}).get("total", 0), reverse=True)[:5]
        
        for i, site in enumerate(sorted_sites, 1):
            name = site.get("name", f"Site-{site['_id'][-6:]}")
            today = site.get("stats", {}).get("today", 0)
            total = site.get("stats", {}).get("total", 0)
            text += f"{i}. {html.escape(name)}: {today} today, {total} total\n"
        
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=back_to_main_menu()
        )

# ================= POLLER =================

def poller_sync():
    """Synchronous poller for Heroku"""
    while True:
        try:
            # Get all enabled sites
            sites = list(sites_col.find({"enabled": True}))
            
            for site in sites:
                try:
                    # Update last check time
                    update_site(site["_id"], {"last_check": datetime.utcnow()})
                    
                    # Prepare request
                    session = requests.Session()
                    
                    # Add cookies if present
                    if site.get("cookies"):
                        session.cookies.update(site["cookies"])
                    
                    # Add headers
                    headers = site.get("headers", {})
                    if not headers:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "application/json, text/javascript, */*"
                        }
                    
                    # Make request
                    response = session.get(
                        site["ajax"],
                        headers=headers,
                        timeout=15
                    )
                    
                    if response.status_code != 200:
                        # Use proper MongoDB operator
                        sites_col.update_one(
                            {"_id": site["_id"]},
                            {"$inc": {"stats.errors": 1}}
                        )
                        logging.error(f"HTTP error {response.status_code} for site {site.get('name')}")
                        continue
                    
                    # Try to parse as JSON
                    try:
                        data = response.json()
                    except json.JSONDecodeError as e:
                        logging.error(f"JSON decode error for site {site.get('name')}: {str(e)}")
                        sites_col.update_one(
                            {"_id": site["_id"]},
                            {"$inc": {"stats.errors": 1}}
                        )
                        continue
                    
                    rows = data.get("aaData", [])
                    
                    if not rows:
                        continue
                    
                    # Get latest row
                    latest_row = rows[0]
                    row_id = str(latest_row)
                    
                    # Check if already processed
                    if site.get("last_uid") == row_id:
                        continue
                    
                    # Extract data - handle different row formats
                    if isinstance(latest_row, list):
                        message = latest_row[-1] if len(latest_row) > 2 else str(latest_row)
                        phone_number = latest_row[2] if len(latest_row) > 2 else ""
                        timestamp = latest_row[0] if latest_row else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        message = str(latest_row)
                        phone_number = ""
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Extract OTP
                    otp = extract_otp(message)
                    
                    if otp == "N/A":
                        continue  # Skip if no OTP found
                    
                    # Format message
                    formatted_message = format_otp_message(
                        otp=otp,
                        number=phone_number,
                        message=message,
                        date=timestamp,
                        site_name=site.get("name", "Unknown Service")
                    )
                    
                    # Send to Telegram using site's bot token
                    send_to_telegram(
                        bot_token=site["bot_token"],
                        chat_ids=site.get("chat_ids", []),
                        text=formatted_message,
                        owner_url=site.get("owner_url", ""),
                        support_url=site.get("support_url", "t.me/botcasx")
                    )
                    
                    # Update statistics - use proper MongoDB operators
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
                    
                    logging.info(f"OTP sent for site {site.get('name')}")
                
                except Exception as e:
                    logging.error(f"Error polling site {site.get('name', site['_id'])}: {str(e)}")
                    # Use proper MongoDB operator
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$inc": {"stats.errors": 1}}
                    )
            
            time.sleep(CHECK_INTERVAL)
        
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
    """Main function for Heroku"""
    # Check environment variables
    if not MASTER_BOT_TOKEN:
        print("❌ Error: MASTER_BOT_TOKEN not set!")
        print("Please set MASTER_BOT_TOKEN in environment variables")
        exit(1)
    
    logging.info("Starting AK KING 👑 bot...")
    
    try:
        # Create application
        app = ApplicationBuilder().token(MASTER_BOT_TOKEN).build()
        
        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("id", my_id))
        
        app.add_handler(CallbackQueryHandler(callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
        
        # Start poller in separate thread
        start_poller_thread()
        
        # Start bot (this will block until stopped)
        logging.info("Bot is starting polling...")
        app.run_polling()
        
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()
