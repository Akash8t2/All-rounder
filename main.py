#!/usr/bin/env python3
import os
import re
import time
import json
import asyncio
import logging
import requests
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
    """Format OTP message as per requirement"""
    masked_number = mask_phone_number(number)
    country = get_country_from_number(number)
    
    return (
        "📩 *LIVE OTP RECEIVED*\n\n"
        f"📞 *Number:* `{masked_number}`\n"
        f"🔢 *OTP:* 🔥 `{otp}` 🔥\n"
        f"🏷 *Service:* {site_name}\n"
        f"🌍 *Country:* {country}\n"
        f"🕒 *Time:* {date}\n\n"
        f"💬 *SMS:*\n{message}\n\n"
        "⚡ *—͟͟͞͞𝗔𝗞𝗔𝗦𝗛 🥀*"
    )

def send_to_telegram(bot_token: str, chat_ids: List[str], text: str, owner_url: str = "", support_url: str = "t.me/botcasx"):
    """Send message to Telegram using bot token"""
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
                "parse_mode": "Markdown",
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
    """Update site data"""
    result = sites_col.update_one(
        {"_id": site_id},
        {"$set": update_data}
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
    """Start command handler"""
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
🤖 *AK KING 👑 - OTP Forwarder Bot*

*Features:*
• Use your own bot token
• Multiple chat IDs per site
• Live OTP forwarding
• Default professional format
• Cookie & header management

*Quick Start:*
1. Create your own bot via @BotFather
2. Get your bot token
3. Add site using this bot
4. Start receiving OTPs!

Use the buttons below to get started.
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
🆘 *How to Use This Bot*

*Step 1 - Create Your Bot:*
1. Go to @BotFather on Telegram
2. Send /newbot command
3. Follow instructions
4. Copy the bot token (like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)

*Step 2 - Add Your Site:*
1. Click "Add New Site"
2. Enter your bot token
3. Add chat IDs (where OTPs should go)
4. Enter AJAX URL to monitor
5. Set site name

*Step 3 - Get Chat IDs:*
• For personal chat: Send /id to your bot
• For group: Add your bot to group, then send /id in group

*Step 4 - Multiple Chats:*
You can add multiple chat IDs separated by commas:
Example: -100123456789, -100987654321, 123456789

*Features:*
• Each site uses its own bot token
• OTPs go to specified chat IDs
• Professional message format
• Real-time forwarding

*Support:* @botcasx
"""
    
    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=back_to_main_menu()
    )

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get chat ID"""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    type_map = {
        "private": "Personal Chat",
        "group": "Group",
        "supergroup": "Supergroup",
        "channel": "Channel"
    }
    
    await update.message.reply_text(
        f"📋 *Chat Information*\n\n"
        f"*Chat ID:* `{chat_id}`\n"
        f"*Type:* {type_map.get(chat_type, 'Unknown')}\n\n"
        f"Use this ID when adding sites.",
        parse_mode="Markdown"
    )

# ================= TEXT MESSAGE HANDLER =================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
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
                    "❌ Invalid bot token format.\n"
                    "Bot token should look like: 123456789:ABCdefGHIjklMnopQRstUvWXyz\n\n"
                    "Please enter a valid bot token:"
                )
                return
            
            # Test the bot token
            try:
                test_url = f"https://api.telegram.org/bot{text}/getMe"
                response = requests.get(test_url, timeout=10)
                
                if response.status_code != 200:
                    await update.message.reply_text(
                        "❌ Invalid bot token or bot not found.\n"
                        "Please check and enter a valid bot token:"
                    )
                    return
                
                bot_info = response.json()
                if not bot_info.get("ok"):
                    await update.message.reply_text(
                        "❌ Bot token is invalid.\n"
                        "Please enter a valid bot token:"
                    )
                    return
                
                site_data["bot_token"] = text
                site_data["bot_username"] = bot_info["result"]["username"]
                context.user_data["adding_site"]["step"] = 2
                
                await update.message.reply_text(
                    f"✅ *Bot Connected Successfully!*\n"
                    f"Bot: @{bot_info['result']['username']}\n\n"
                    "*Step 2/4*\n\n"
                    "Now enter *Chat IDs* where OTPs should be sent:\n\n"
                    "*Format:* Separate multiple IDs with commas\n"
                    "*Example:* -100123456789, -100987654321, 123456789\n\n"
                    "To get Chat ID:\n"
                    "1. Add your bot to chat/group\n"
                    "2. Send /id command to your bot\n"
                    "3. Copy the Chat ID\n\n"
                    "Enter Chat ID(s):",
                    parse_mode="Markdown"
                )
            
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Error testing bot token: {str(e)}\n"
                    "Please enter a valid bot token:"
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
                            f"❌ Invalid Chat ID: {cid}\n"
                            "Chat IDs must be numbers (or start with @ for public channels)\n"
                            "Please enter valid Chat IDs:"
                        )
                        return
                
                site_data["chat_ids"] = chat_ids
                context.user_data["adding_site"]["step"] = 3
                
                await update.message.reply_text(
                    "✅ *Chat IDs Saved!*\n\n"
                    "*Step 3/4*\n\n"
                    "Now enter the *AJAX URL* to monitor:\n\n"
                    "Example: `https://example.com/ajax.php`\n\n"
                    "This URL should return JSON data with OTP information.",
                    parse_mode="Markdown"
                )
            
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Error parsing chat IDs: {str(e)}\n"
                    "Please enter valid Chat IDs:"
                )
            return
        
        elif step == 3:  # AJAX URL
            # Basic URL validation
            if not (text.startswith("http://") or text.startswith("https://")):
                await update.message.reply_text(
                    "❌ Invalid URL format.\n"
                    "URL must start with http:// or https://\n"
                    "Please enter a valid URL:"
                )
                return
            
            site_data["ajax"] = text
            context.user_data["adding_site"]["step"] = 4
            
            await update.message.reply_text(
                "✅ *URL Saved!*\n\n"
                "*Step 4/4*\n\n"
                "Now enter a *name* for this site:\n\n"
                "Example: `Amazon OTPs` or `Gmail Verification`\n\n"
                "This name will appear in OTP messages.",
                parse_mode="Markdown"
            )
            return
        
        elif step == 4:  # Site Name
            site_data["name"] = text
            
            # Ask for Owner URL (optional)
            context.user_data["adding_site"]["step"] = 5
            
            await update.message.reply_text(
                "✅ *Site Name Saved!*\n\n"
                "*Optional Step*\n\n"
                "Enter Owner URL (optional):\n\n"
                "Example: `t.me/yourusername`\n"
                "This will appear in the OTP message buttons.\n\n"
                "Or type /skip to use default.",
                parse_mode="Markdown"
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
✅ *Site Added Successfully!*

*Site Details:*
• *ID:* `{site_id}`
• *Name:* {site_data['name']}
• *Bot:* @{site_data.get('bot_username', 'N/A')}
• *Chat IDs:* {len(site_data['chat_ids'])}
• *URL:* `{site_data['ajax']}`

*Next Steps:*
1. Make sure your bot is added to all chats
2. Test the site using "Test Site" button
3. Enable site to start receiving OTPs

OTPs will be sent using your bot with this format:
"""
            success_text += format_otp_message("123456", "9876543210", "Your verification code is 123456", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), site_data['name'])
            
            await update.message.reply_text(
                success_text[:4000],  # Telegram limit
                parse_mode="Markdown",
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
            "🤖 *AK KING 👑 - Main Menu*",
            parse_mode="Markdown",
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
            "➕ *Add New Site - Step 1/4*\n\n"
            "Please enter your *Bot Token*:\n\n"
            "*How to get Bot Token:*\n"
            "1. Go to @BotFather\n"
            "2. Send /newbot\n"
            "3. Follow instructions\n"
            "4. Copy the token (format: 123456:ABCdef...)\n\n"
            "Enter your bot token:",
            parse_mode="Markdown"
        )
    
    # List sites
    elif data == "list_sites":
        sites = get_user_sites(user_id)
        
        if not sites:
            await query.message.edit_text(
                "📭 *No Sites Found*\n\n"
                "You haven't added any sites yet.\n"
                "Click 'Add New Site' to get started.",
                parse_mode="Markdown",
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
            f"📋 *Your Sites ({len(sites)})*",
            parse_mode="Markdown",
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
📡 *Site Details*

*Name:* {site.get('name', 'Unnamed')}
*Status:* {status}
*Bot:* @{site.get('bot_username', 'N/A')}
*Chat IDs:* {len(site.get('chat_ids', []))}

*Statistics:*
• Today: {stats.get('today', 0)}
• Total: {stats.get('total', 0)}
• Errors: {stats.get('errors', 0)}

*URL:* `{site.get('ajax', 'N/A')}`
"""
        
        if site.get("last_check"):
            last_check = site["last_check"].strftime("%Y-%m-%d %H:%M:%S")
            text += f"*Last Check:* {last_check}\n"
        
        await query.message.edit_text(
            text,
            parse_mode="Markdown",
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
            text = "💬 *Current Chat IDs:*\n\n"
            for i, cid in enumerate(chat_ids, 1):
                text += f"{i}. `{cid}`\n"
        else:
            text = "📭 *No Chat IDs*\n\nAdd chat IDs to receive OTPs."
        
        text += "\n\n*Current Bot:* @" + site.get("bot_username", "N/A")
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"view_site:{site_id}")])
        
        await query.message.edit_text(
            text,
            parse_mode="Markdown",
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
                "✅ *Test Message Sent!*\n\n"
                "Check your specified chats for the test OTP.\n\n"
                "If you didn't receive:\n"
                "1. Check if bot is added to chats\n"
                "2. Verify chat IDs are correct\n"
                "3. Ensure bot has permission to send messages",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"view_site:{site_id}")]
                ])
            )
        
        except Exception as e:
            await query.message.edit_text(
                f"❌ *Test Failed*\n\nError: {str(e)}",
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
📊 *Your Statistics*

*Sites:*
• Total: {total_sites}
• Active: {active_sites}

*OTPs Today:* {total_today}
*OTPs Total:* {total_all}

*Top Sites:*
"""
        
        # Sort by total OTPs
        sorted_sites = sorted(sites, key=lambda x: x.get("stats", {}).get("total", 0), reverse=True)[:5]
        
        for i, site in enumerate(sorted_sites, 1):
            name = site.get("name", f"Site-{site['_id'][-6:]}")
            today = site.get("stats", {}).get("today", 0)
            total = site.get("stats", {}).get("total", 0)
            text += f"{i}. {name}: {today} today, {total} total\n"
        
        await query.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_to_main_menu()
        )

# ================= POLLER =================

async def poller():
    """Main polling loop"""
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
                            "Accept": "application/json"
                        }
                    
                    # Make request
                    response = session.get(
                        site["ajax"],
                        headers=headers,
                        timeout=15
                    )
                    
                    if response.status_code != 200:
                        update_site(site["_id"], {"$inc": {"stats.errors": 1}})
                        continue
                    
                    # Parse JSON response
                    data = response.json()
                    rows = data.get("aaData", [])
                    
                    if not rows:
                        continue
                    
                    # Get latest row
                    latest_row = rows[0]
                    row_id = str(latest_row)
                    
                    # Check if already processed
                    if site.get("last_uid") == row_id:
                        continue
                    
                    # Extract data
                    message = latest_row[-1] if len(latest_row) > 2 else str(latest_row)
                    phone_number = latest_row[2] if len(latest_row) > 2 else ""
                    timestamp = latest_row[0] if latest_row else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
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
                    
                    # Update statistics
                    update_site(site["_id"], {
                        "last_uid": row_id,
                        "last_success": datetime.utcnow(),
                        "$inc": {"stats.today": 1, "stats.total": 1}
                    })
                    
                    logging.info(f"OTP sent for site {site.get('name')}")
                
                except Exception as e:
                    logging.error(f"Error polling site {site.get('name', site['_id'])}: {str(e)}")
                    update_site(site["_id"], {"$inc": {"stats.errors": 1}})
            
            await asyncio.sleep(CHECK_INTERVAL)
        
        except Exception as e:
            logging.error(f"Poller error: {str(e)}")
            await asyncio.sleep(30)

# ================= MAIN =================

def setup_handlers(application):
    """Setup all handlers"""
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("id", my_id))
    
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

async def main_async():
    """Main application (async)"""
    # Create application
    app = ApplicationBuilder().token(MASTER_BOT_TOKEN).build()
    
    # Setup handlers
    setup_handlers(app)
    
    # Start poller
    asyncio.create_task(poller())
    
    # Start bot
    logging.info("Starting AK KING 👑 bot...")
    await app.initialize()
    await app.start()
    await app.run_polling()

def main():
    """Main entry point"""
    # Check environment variables
    if not MASTER_BOT_TOKEN:
        print("❌ Error: MASTER_BOT_TOKEN not set!")
        print("Please set MASTER_BOT_TOKEN in environment variables")
        exit(1)
    
    try:
        # For Heroku, we need to handle the event loop properly
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Error: {e}")

if __name__ == "__main__":
    main()
