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

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN")
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

# ================= HELPERS =================

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
        '49': '🇩🇪 Germany',
        '55': '🇧🇷 Brazil',
        '34': '🇪🇸 Spain',
        '39': '🇮🇹 Italy',
        '61': '🇦🇺 Australia',
        '27': '🇿🇦 South Africa',
        '20': '🇪🇬 Egypt',
        '90': '🇹🇷 Turkey',
        '98': '🇮🇷 Iran',
        '41': '🇨🇭 Switzerland',
        '46': '🇸🇪 Sweden',
        '47': '🇳🇴 Norway',
        '45': '🇩🇰 Denmark',
        '358': '🇫🇮 Finland',
        '31': '🇳🇱 Netherlands',
        '32': '🇧🇪 Belgium',
        '43': '🇦🇹 Austria',
        '48': '🇵🇱 Poland',
        '36': '🇭🇺 Hungary',
        '40': '🇷🇴 Romania',
        '421': '🇸🇰 Slovakia',
        '420': '🇨🇿 Czech',
    }
    
    for prefix, country in prefixes.items():
        if number.startswith(prefix):
            return country
    
    return "🌍 International"

def format_otp_message(otp: str, number: str, message: str, date: str, site_name: str, route: str = "", service: str = "") -> str:
    """Format OTP message"""
    masked_number = mask_phone_number(number)
    country = get_country_from_number(number)
    
    # Use HTML for better formatting
    result = "📩 <b>LIVE OTP RECEIVED</b>\n\n"
    result += f"📞 <b>Number:</b> <code>{number if number else 'N/A'}</code>\n"
    result += f"🔢 <b>OTP:</b> 🔥 <code>{otp}</code> 🔥\n"
    
    if service:
        result += f"🏷 <b>Service:</b> {html.escape(service)}\n"
    else:
        result += f"🏷 <b>Service:</b> {html.escape(site_name)}\n"
    
    if route and route != "Unknown":
        country_from_route = route.split("-")[0] if "-" in route else route
        result += f"🌍 <b>Country:</b> {country_from_route}\n"
    else:
        result += f"🌍 <b>Country:</b> {country}\n"
    
    result += f"🕒 <b>Time:</b> {date}\n\n"
    result += f"💬 <b>SMS:</b>\n{html.escape(message)}\n\n"
    result += "⚡ <b>—͟͟͞͞𝗔𝗞𝗔𝗦𝗛 🥀</b>"
    
    return result

def send_to_telegram(bot_token: str, chat_ids: List[str], text: str, owner_url: str = "", support_url: str = "t.me/botcasx"):
    """Send message to Telegram"""
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
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

# ================= SITE MANAGEMENT =================

def add_site(user_id: int, site_data: Dict) -> str:
    """Add new site for user"""
    site_id = str(int(time.time() * 1000))
    
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
        "cookies": site_data.get("cookies", {}),
        "headers": site_data.get("headers", {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }),
        "owner_url": site_data.get("owner_url", ""),
        "support_url": site_data.get("support_url", "t.me/botcasx"),
        "ajax_type": site_data.get("ajax_type", "standard")  # standard or ints_sms
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])

# ================= COMMAND HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
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
• Cookie & header management
• INTS SMS format support

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
    help_text = """
🆘 <b>How to Use This Bot</b>

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

<b>Support:</b> @botcasx
"""
    
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        reply_markup=back_to_main_menu()
    )

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
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
            
            # Add the site
            site_id = add_site(user_id, site_data)
            site = get_site(site_id)
            
            success_text = f"""
✅ <b>Site Added Successfully!</b>

<b>Site Details:</b>
• <b>ID:</b> <code>{site_id}</code>
• <b>Name:</b> {html.escape(site_data['name'])}
• <b>Bot:</b> @{html.escape(site_data.get('bot_username', 'N/A'))}
• <b>Chat IDs:</b> {len(site_data['chat_ids'])}
• <b>URL:</b> <code>{html.escape(site_data['ajax'][:50])}...</code>
• <b>Type:</b> {site_data['ajax_type']}
"""
            
            await update.message.reply_text(
                success_text,
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            
            del context.user_data["adding_site"]
        
        return
    
    await update.message.reply_text(
        "🤖 AK KING 👑 Bot\n\n"
        "Use the buttons or commands to manage your sites.",
        reply_markup=main_menu()
    )

# ================= CALLBACK HANDLER =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "main_menu":
        await query.message.edit_text(
            "🤖 <b>AK KING 👑 - Main Menu</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
    
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
<b>Type:</b> {site.get('ajax_type', 'standard')}

<b>Statistics:</b>
• Today: {stats.get('today', 0)}
• Total: {stats.get('total', 0)}
• Errors: {stats.get('errors', 0)}

<b>URL:</b> <code>{html.escape(site.get('ajax', 'N/A')[:50])}...</code>
"""
        
        if site.get("last_check"):
            last_check = site["last_check"].strftime("%Y-%m-%d %H:%M:%S")
            text += f"<b>Last Check:</b> {last_check}\n"
        
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=site_menu(site_id)
        )
    
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
    
    elif data.startswith("test:"):
        site_id = data.split(":", 1)[1]
        site = get_site(site_id)
        
        if not site or site["user_id"] != user_id:
            await query.message.edit_text("❌ Access denied")
            return
        
        test_message = format_otp_message(
            otp="123456",
            number="+4915511850412",
            message="Contul dvs WhatsApp Business se inregistreaza pe un nou dispozitiv\n\nNu comunicati nimanui acest cod\nCodul dvs WhatsApp Business 397-838",
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            site_name=site.get("name", "Test Site"),
            service="WHATSAPP",
            route="Germany"
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
                "Check your specified chats for the test OTP.\n"
                "Format used: INTS SMS format",
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
    
    elif data == "help":
        await help_command(update, context)
    
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
    """Main polling loop - Based on working script"""
    while True:
        try:
            sites = list(sites_col.find({"enabled": True}))
            
            for site in sites:
                try:
                    # Update last check time
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$set": {"last_check": datetime.utcnow()}}
                    )
                    
                    # Prepare session
                    session = requests.Session()
                    
                    # Set headers
                    headers = site.get("headers", {
                        "User-Agent": "Mozilla/5.0",
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01"
                    })
                    
                    # Set cookies
                    cookies = site.get("cookies", {})
                    
                    # Check if it's INTS SMS type
                    if site.get("ajax_type") == "ints_sms":
                        # Use working script logic for INTS SMS
                        url = site["ajax"]
                        
                        # Make request
                        response = session.get(
                            url,
                            headers=headers,
                            cookies=cookies,
                            timeout=20
                        )
                        
                        if response.status_code != 200:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        try:
                            data = response.json()
                        except:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        rows = data.get("aaData", [])
                        if not rows:
                            continue
                        
                        # Filter valid rows
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
                        
                        # Sort by date
                        valid_rows.sort(
                            key=lambda x: datetime.strptime(x[0], "%Y-%m-%d %H:%M:%S"),
                            reverse=True
                        )
                        
                        newest = valid_rows[0]
                        uid = newest[0] + (newest[2] or "") + (newest[5] or "")
                        
                        # Check if already processed
                        if site.get("last_uid") == uid:
                            continue
                        
                        # Extract data
                        date = newest[0]
                        route_raw = newest[1] or "Unknown"
                        number = newest[2] or ""
                        service = newest[3] or "Unknown"
                        message = newest[5] or ""
                        
                        # Extract OTP
                        otp = extract_otp(message)
                        if otp == "N/A":
                            continue
                        
                        # Format message (same as WhatsApp example)
                        formatted_message = format_otp_message(
                            otp=otp,
                            number=number,
                            message=message,
                            date=date,
                            site_name=site.get("name", "Unknown"),
                            route=route_raw,
                            service=service
                        )
                        
                        # Send to Telegram
                        send_to_telegram(
                            bot_token=site["bot_token"],
                            chat_ids=site.get("chat_ids", []),
                            text=formatted_message,
                            owner_url=site.get("owner_url", ""),
                            support_url=site.get("support_url", "t.me/botcasx")
                        )
                        
                        # Update stats
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
                        
                        logging.info(f"OTP sent for site {site.get('name')}")
                    
                    else:
                        # Standard AJAX polling (original logic)
                        url = site["ajax"]
                        response = session.get(
                            url,
                            headers=headers,
                            cookies=cookies,
                            timeout=15
                        )
                        
                        if response.status_code != 200:
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            continue
                        
                        try:
                            data = response.json()
                        except:
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
                        
                        # Extract data
                        message = latest_row[-1] if len(latest_row) > 2 else str(latest_row)
                        phone_number = latest_row[2] if len(latest_row) > 2 else ""
                        timestamp = latest_row[0] if latest_row else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Extract OTP
                        otp = extract_otp(message)
                        if otp == "N/A":
                            continue
                        
                        # Format message
                        formatted_message = format_otp_message(
                            otp=otp,
                            number=phone_number,
                            message=message,
                            date=timestamp,
                            site_name=site.get("name", "Unknown Service")
                        )
                        
                        # Send to Telegram
                        send_to_telegram(
                            bot_token=site["bot_token"],
                            chat_ids=site.get("chat_ids", []),
                            text=formatted_message,
                            owner_url=site.get("owner_url", ""),
                            support_url=site.get("support_url", "t.me/botcasx")
                        )
                        
                        # Update stats
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
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$inc": {"stats.errors": 1}}
                    )
            
            time.sleep(CHECK_INTERVAL)
        
        except Exception as e:
            logging.error(f"Poller error: {str(e)}")
            time.sleep(30)

def start_poller_thread():
    poller_thread = threading.Thread(target=poller_sync, daemon=True)
    poller_thread.start()
    logging.info("Poller thread started")

# ================= MAIN =================

def main():
    if not MASTER_BOT_TOKEN:
        print("❌ Error: MASTER_BOT_TOKEN not set!")
        print("Please set MASTER_BOT_TOKEN in environment variables")
        exit(1)
    
    logging.info("Starting AK KING 👑 bot...")
    
    try:
        app = ApplicationBuilder().token(MASTER_BOT_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("id", my_id))
        
        app.add_handler(CallbackQueryHandler(callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
        
        start_poller_thread()
        
        logging.info("Bot is starting polling...")
        app.run_polling()
        
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()
