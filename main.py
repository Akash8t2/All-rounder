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
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
CHECK_INTERVAL = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ================= GLOBAL CACHE =================

# ✅ FIX 1: Session cache for reuse
SITE_SESSIONS = {}
# ✅ FIX 4: Daily reset optimization
LAST_RESET = None

# ================= DB SETUP WITH INDEXES =================

mongo = MongoClient(MONGO_URI)
db = mongo["master_bot"]
sites_col = db["sites"]
users_col = db["users"]

# Create indexes for performance
try:
    sites_col.create_index("user_id")
    sites_col.create_index("enabled")
    sites_col.create_index("last_uid")
    sites_col.create_index([("user_id", 1), ("enabled", 1)])
    users_col.create_index("user_id", unique=True)
    logging.info("✅ MongoDB indexes created/verified")
except Exception as e:
    logging.warning(f"⚠️ Could not create indexes: {e}")

# ================= HELPER FUNCTIONS =================

def extract_otp(text: str) -> str:
    """Extract OTP from text - HARDENED VERSION"""
    if not text:
        return "N/A"
    
    # More specific patterns to avoid phone numbers/prices
    patterns = [
        r'(?:OTP|code|verification|password|पासकोड|कोड)[^\d]{0,10}(\d{4,8})',
        r'\b(?!\d{9,})(\d{4,8})\b',  # Avoid 9+ digit numbers
        r'(?:is|का|की)[^\d]{0,5}(\d{4,8})',
        r'[:\-\s]\s*(\d{4,8})\b'
    ]
    
    # First try specific patterns
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            otp = m.group(1)
            # Validate OTP length
            if 4 <= len(otp) <= 8:
                return otp
    
    # Fallback: look for isolated 4-8 digit numbers
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
            # Filter out phone numbers (usually in sequence)
            for match in matches:
                # Check if this looks like part of a phone number
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
    '1': '🇺🇸 USA / 🇨🇦 Canada',
    '7': '🇷🇺 Russia / 🇰🇿 Kazakhstan',
    '20': '🇪🇬 Egypt',
    '27': '🇿🇦 South Africa',
    '30': '🇬🇷 Greece',
    '31': '🇳🇱 Netherlands',
    '32': '🇧🇪 Belgium',
    '33': '🇫🇷 France',
    '34': '🇪🇸 Spain',
    '36': '🇭🇺 Hungary',
    '39': '🇮🇹 Italy',
    '40': '🇷🇴 Romania',
    '41': '🇨🇭 Switzerland',
    '43': '🇦🇹 Austria',
    '44': '🇬🇧 United Kingdom',
    '45': '🇩🇰 Denmark',
    '46': '🇸🇪 Sweden',
    '47': '🇳🇴 Norway',
    '48': '🇵🇱 Poland',
    '49': '🇩🇪 Germany',
    '51': '🇵🇪 Peru',
    '52': '🇲🇽 Mexico',
    '53': '🇨🇺 Cuba',
    '54': '🇦🇷 Argentina',
    '55': '🇧🇷 Brazil',
    '56': '🇨🇱 Chile',
    '57': '🇨🇴 Colombia',
    '58': '🇻🇪 Venezuela',
    '60': '🇲🇾 Malaysia',
    '61': '🇦🇺 Australia',
    '62': '🇮🇩 Indonesia',
    '63': '🇵🇭 Philippines',
    '64': '🇳🇿 New Zealand',
    '65': '🇸🇬 Singapore',
    '66': '🇹🇭 Thailand',
    '81': '🇯🇵 Japan',
    '82': '🇰🇷 South Korea',
    '84': '🇻🇳 Vietnam',
    '86': '🇨🇳 China',
    '90': '🇹🇷 Turkey',
    '91': '🇮🇳 India',
    '92': '🇵🇰 Pakistan',
    '93': '🇦🇫 Afghanistan',
    '94': '🇱🇰 Sri Lanka',
    '95': '🇲🇲 Myanmar',
    '98': '🇮🇷 Iran',

    '211': '🇸🇸 South Sudan',
    '212': '🇲🇦 Morocco',
    '213': '🇩🇿 Algeria',
    '216': '🇹🇳 Tunisia',
    '218': '🇱🇾 Libya',
    '220': '🇬🇲 Gambia',
    '221': '🇸🇳 Senegal',
    '222': '🇲🇷 Mauritania',
    '223': '🇲🇱 Mali',
    '224': '🇬🇳 Guinea',
    '225': '🇨🇮 Ivory Coast',
    '226': '🇧🇫 Burkina Faso',
    '227': '🇳🇪 Niger',
    '228': '🇹🇬 Togo',
    '229': '🇧🇯 Benin',
    '230': '🇲🇺 Mauritius',
    '231': '🇱🇷 Liberia',
    '232': '🇸🇱 Sierra Leone',
    '233': '🇬🇭 Ghana',
    '234': '🇳🇬 Nigeria',
    '235': '🇹🇩 Chad',
    '236': '🇨🇫 Central African Republic',
    '237': '🇨🇲 Cameroon',
    '238': '🇨🇻 Cape Verde',
    '239': '🇸🇹 Sao Tome & Principe',
    '240': '🇬🇶 Equatorial Guinea',
    '241': '🇬🇦 Gabon',
    '242': '🇨🇬 Congo',
    '243': '🇨🇩 DR Congo',
    '244': '🇦🇴 Angola',
    '245': '🇬🇼 Guinea-Bissau',
    '246': '🇮🇴 British Indian Ocean Territory',
    '248': '🇸🇨 Seychelles',
    '249': '🇸🇩 Sudan',
    '250': '🇷🇼 Rwanda',
    '251': '🇪🇹 Ethiopia',
    '252': '🇸🇴 Somalia',
    '253': '🇩🇯 Djibouti',
    '254': '🇰🇪 Kenya',
    '255': '🇹🇿 Tanzania',
    '256': '🇺🇬 Uganda',
    '257': '🇧🇮 Burundi',
    '258': '🇲🇿 Mozambique',
    '260': '🇿🇲 Zambia',
    '261': '🇲🇬 Madagascar',
    '262': '🇷🇪 Reunion',
    '263': '🇿🇼 Zimbabwe',
    '264': '🇳🇦 Namibia',
    '265': '🇲🇼 Malawi',
    '266': '🇱🇸 Lesotho',
    '267': '🇧🇼 Botswana',
    '268': '🇸🇿 Eswatini',
    '269': '🇰🇲 Comoros',

    '351': '🇵🇹 Portugal',
    '352': '🇱🇺 Luxembourg',
    '353': '🇮🇪 Ireland',
    '354': '🇮🇸 Iceland',
    '355': '🇦🇱 Albania',
    '356': '🇲🇹 Malta',
    '357': '🇨🇾 Cyprus',
    '358': '🇫🇮 Finland',
    '359': '🇧🇬 Bulgaria',
    '370': '🇱🇹 Lithuania',
    '371': '🇱🇻 Latvia',
    '372': '🇪🇪 Estonia',
    '373': '🇲🇩 Moldova',
    '374': '🇦🇲 Armenia',
    '375': '🇧🇾 Belarus',
    '376': '🇦🇩 Andorra',
    '377': '🇲🇨 Monaco',
    '378': '🇸🇲 San Marino',
    '380': '🇺🇦 Ukraine',
    '381': '🇷🇸 Serbia',
    '382': '🇲🇪 Montenegro',
    '383': '🇽🇰 Kosovo',
    '385': '🇭🇷 Croatia',
    '386': '🇸🇮 Slovenia',
    '387': '🇧🇦 Bosnia & Herzegovina',
    '389': '🇲🇰 North Macedonia',

    '420': '🇨🇿 Czech Republic',
    '421': '🇸🇰 Slovakia',
    '423': '🇱🇮 Liechtenstein',

    '852': '🇭🇰 Hong Kong',
    '853': '🇲🇴 Macau',
    '855': '🇰🇭 Cambodia',
    '856': '🇱🇦 Laos',
    '880': '🇧🇩 Bangladesh',
    '886': '🇹🇼 Taiwan',

    '960': '🇲🇻 Maldives',
    '961': '🇱🇧 Lebanon',
    '962': '🇯🇴 Jordan',
    '963': '🇸🇾 Syria',
    '964': '🇮🇶 Iraq',
    '965': '🇰🇼 Kuwait',
    '966': '🇸🇦 Saudi Arabia',
    '967': '🇾🇪 Yemen',
    '968': '🇴🇲 Oman',
    '970': '🇵🇸 Palestine',
    '971': '🇦🇪 UAE',
    '972': '🇮🇱 Israel',
    '973': '🇧🇭 Bahrain',
    '974': '🇶🇦 Qatar',
    '975': '🇧🇹 Bhutan',
    '976': '🇲🇳 Mongolia',
    '977': '🇳🇵 Nepal',
    '992': '🇹🇯 Tajikistan',
    '993': '🇹🇲 Turkmenistan',
    '994': '🇦🇿 Azerbaijan',
    '995': '🇬🇪 Georgia',
    '996': '🇰🇬 Kyrgyzstan',
    '998': '🇺🇿 Uzbekistan',
    }
    
    for prefix, country in prefixes.items():
        if number.startswith(prefix):
            return country
    
    return "🌍 International"

def format_otp_message(otp: str, number: str, message: str, date: str, site_name: str, route: str = "", service: str = "") -> str:
    """Format OTP message with proper HTML escaping"""
    safe_otp = html.escape(otp)
    safe_number = html.escape(number) if number else "N/A"
    safe_message = html.escape(message)
    safe_site_name = html.escape(site_name)
    safe_service = html.escape(service) if service else safe_site_name
    
    result = "📩 <b>LIVE OTP RECEIVED</b>\n\n"
    result += f"📞 <b>Number:</b> <code>{safe_number}</code>\n"
    result += f"🔢 <b>OTP:</b> 🔥 <code>{safe_otp}</code> 🔥\n"
    result += f"🏷 <b>Service:</b> {safe_service}\n"
    
    if route and route != "Unknown":
        country_from_route = route.split("-")[0] if "-" in route else route
        result += f"🌍 <b>Country:</b> {country_from_route}\n"
    else:
        country = get_country_from_number(number)
        result += f"🌍 <b>Country:</b> {country}\n"
    
    result += f"🕒 <b>Time:</b> {date}\n\n"
    result += f"💬 <b>SMS:</b>\n{safe_message}\n\n"
    result += "⚡ <b>—͟͟͞͞𝗔𝗞𝗔𝗦𝗛 🥀</b>"
    
    return result

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

# ✅ FIX 3: send_to_telegram() returns correctly for all chats
def send_to_telegram(bot_token: str, chat_ids: List[str], text: str, owner_url: str = "", support_url: str = "t.me/botcasx"):
    """Send message to Telegram - IMPROVED"""
    success = True
    
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Owner", "url": owner_url} if owner_url else {"text": "Owner", "url": "https://t.me/+W2ipO5KOmtIzOTU1"},
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
                success = False
                # Don't return here - try sending to other chats
        
        except Exception as e:
            logging.error(f"Error sending to Telegram for chat {chat_id}: {str(e)}")
            success = False
            # Continue trying other chats
    
    return success

def reset_daily_stats():
    """Reset daily statistics at midnight UTC"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Update all sites where last_day is not today
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
        "ajax_type": site_data.get("ajax_type", "standard")
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
    
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({
            "user_id": user_id,
            "username": update.effective_user.username,
            "first_name": update.effective_user.first_name,
            "joined_at": datetime.utcnow()
        })
    
    welcome_text = """🤖 <b>AK KING 👑 - OTP Forwarder Bot</b>

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

Use the buttons below to get started."""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
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

<b>Support:</b> @botcasx"""
    
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
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
        f"📋 <b>Chat Information</b>\n\n"
        f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
        f"<b>Type:</b> {type_map.get(chat_type, 'Unknown')}\n\n"
        f"Use this ID when adding sites.",
        parse_mode="HTML"
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
            
            # Clear adding state
            del context.user_data["adding_site"]
        
        return
    
    # Handle other text inputs
    await update.message.reply_text(
        "🤖 <b>AK KING 👑 Bot</b>\n\n"
        "Use the buttons or commands to manage your sites.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# ================= CALLBACK HANDLER =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries - FIXED"""
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = query.from_user.id
        data = query.data
        
        logging.info(f"Callback received: {data} from user {user_id}")
        
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
                        callback_data=f"view_site_{site['_id']}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
            
            await query.message.edit_text(
                f"📋 <b>Your Sites ({len(sites)})</b>\n\n"
                "Click on a site to manage it:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        # View site
        elif data.startswith("view_site_"):
            site_id = data.replace("view_site_", "")
            site = get_site(site_id)
            
            if not site or site["user_id"] != user_id:
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
            
            if not site or site["user_id"] != user_id:
                await query.message.edit_text("❌ Access denied")
                return
            
            new_state = not site.get("enabled", True)
            update_site(site_id, {"enabled": new_state})
            
            status = "✅ enabled" if new_state else "❌ disabled"
            await query.message.edit_text(f"Site {status}")
        
        # Test site - FIXED
        elif data.startswith("test_"):
            site_id = data.replace("test_", "")
            site = get_site(site_id)
            
            if not site or site["user_id"] != user_id:
                await query.message.edit_text("❌ Access denied")
                return
            
            # Send a test message with actual sending
            await query.message.edit_text("🔄 Sending test message...")
            
            test_message = format_otp_message(
                otp="123456",
                number="+4915511850412",
                message="This is a test message from AK KING Bot.\n\nYour verification code is 123456\n\nDo not share this code with anyone.",
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                site_name=site.get("name", "Test Site"),
                service="WHATSAPP",
                route="Germany"
            )
            
            success = send_to_telegram(
                bot_token=site["bot_token"],
                chat_ids=site.get("chat_ids", []),
                text=test_message,
                owner_url=site.get("owner_url", ""),
                support_url=site.get("support_url", "t.me/botcasx")
            )
            
            if success:
                await query.message.edit_text(
                    "✅ <b>Test Message Sent Successfully!</b>\n\n"
                    "Check your specified chats for the test OTP.\n"
                    "Format used: INTS SMS format\n\n"
                    "<b>Test Details:</b>\n"
                    f"• Bot: @{site.get('bot_username', 'N/A')}\n"
                    f"• Chats: {len(site.get('chat_ids', []))}\n"
                    f"• Format: HTML",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
                    ])
                )
            else:
                await query.message.edit_text(
                    "❌ <b>Test Message Failed</b>\n\n"
                    "Possible issues:\n"
                    "1. Bot token is invalid\n"
                    "2. Bot is not added to chat(s)\n"
                    "3. Chat IDs are incorrect\n"
                    "4. Bot doesn't have permission to send messages",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data=f"view_site_{site_id}")]
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
        elif data.startswith("chats_") or data.startswith("cookies_") or data.startswith("headers_") or data.startswith("delete_") or data.startswith("token_") or data.startswith("site_stats_"):
            parts = data.split("_")
            if len(parts) >= 2:
                site_id = parts[1]
                site = get_site(site_id)
                
                if not site or site["user_id"] != user_id:
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
                elif data.startswith("delete_"):
                    # Delete site
                    sites_col.delete_one({"_id": site_id})
                    await query.message.edit_text(
                        f"🗑 <b>Site Deleted</b>\n\n"
                        "The site has been removed from your list.",
                        parse_mode="HTML",
                        reply_markup=main_menu()
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

# ================= POLLER =================

def poller_sync():
    """Main polling loop - FIXED with all critical patches"""
    global LAST_RESET
    
    while True:
        try:
            # ✅ FIX 4: Optimized daily reset - run only once per day
            now = datetime.utcnow()
            if not LAST_RESET or now.date() != LAST_RESET.date():
                reset_daily_stats()
                LAST_RESET = now
                logging.info(f"✅ Daily stats reset at {now}")
            
            sites = list(sites_col.find({"enabled": True}))
            
            for site in sites:
                try:
                    # Update last check time
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$set": {"last_check": datetime.utcnow()}}
                    )
                    
                    # ✅ FIX 1: Reuse session instead of creating new one every loop
                    if site["_id"] not in SITE_SESSIONS:
                        SITE_SESSIONS[site["_id"]] = get_site_session(site)
                    
                    session = SITE_SESSIONS[site["_id"]]
                    
                    # Check if it's INTS SMS type
                    if site.get("ajax_type") == "ints_sms":
                        url = site["ajax"]
                        
                        # Make request
                        response = session.get(
                            url,
                            headers=session.headers,
                            cookies=session.cookies,
                            timeout=20
                        )
                        
                        # ✅ FIX 2: Improved HTML detection
                        content_type = response.headers.get("Content-Type", "").lower()
                        response_text = response.text.lower()
                        
                        if "text/html" in content_type and "<html" in response_text:
                            logging.warning(f"⚠️ Session expired for {site.get('name')} - Got HTML login page")
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            # Clear session on HTML response (likely expired)
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
                        
                        # CRITICAL: Update last_uid BEFORE sending
                        sites_col.update_one(
                            {"_id": site["_id"]},
                            {"$set": {"last_uid": uid}}
                        )
                        
                        # Format message
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
                        success = send_to_telegram(
                            bot_token=site["bot_token"],
                            chat_ids=site.get("chat_ids", []),
                            text=formatted_message,
                            owner_url=site.get("owner_url", ""),
                            support_url=site.get("support_url", "t.me/botcasx")
                        )
                        
                        if success:
                            # Update stats only if send successful
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {
                                    "$set": {"last_success": datetime.utcnow()},
                                    "$inc": {
                                        "stats.today": 1,
                                        "stats.total": 1
                                    }
                                }
                            )
                            
                            logging.info(f"✅ OTP sent for site {site.get('name')}")
                        else:
                            logging.error(f"❌ Failed to send OTP for site {site.get('name')}")
                            # Rollback last_uid if send failed
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$set": {"last_uid": site.get("last_uid")}}
                            )
                    
                    else:
                        # Standard AJAX polling
                        url = site["ajax"]
                        response = session.get(
                            url,
                            headers=session.headers,
                            cookies=session.cookies,
                            timeout=15
                        )
                        
                        # ✅ FIX 2: Improved HTML detection
                        content_type = response.headers.get("Content-Type", "").lower()
                        response_text = response.text.lower()
                        
                        if "text/html" in content_type and "<html" in response_text:
                            logging.warning(f"⚠️ HTML login page for {site.get('name')}")
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$inc": {"stats.errors": 1}}
                            )
                            # Clear session on HTML response
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
                        
                        # Extract data
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
                            continue
                        
                        # CRITICAL: Update last_uid BEFORE sending
                        sites_col.update_one(
                            {"_id": site["_id"]},
                            {"$set": {"last_uid": row_id}}
                        )
                        
                        # Format message
                        formatted_message = format_otp_message(
                            otp=otp,
                            number=phone_number,
                            message=message,
                            date=timestamp,
                            site_name=site.get("name", "Unknown Service")
                        )
                        
                        # Send to Telegram
                        success = send_to_telegram(
                            bot_token=site["bot_token"],
                            chat_ids=site.get("chat_ids", []),
                            text=formatted_message,
                            owner_url=site.get("owner_url", ""),
                            support_url=site.get("support_url", "t.me/botcasx")
                        )
                        
                        if success:
                            # Update stats
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {
                                    "$set": {"last_success": datetime.utcnow()},
                                    "$inc": {
                                        "stats.today": 1,
                                        "stats.total": 1
                                    }
                                }
                            )
                            
                            logging.info(f"✅ OTP sent for site {site.get('name')}")
                        else:
                            logging.error(f"❌ Failed to send OTP for site {site.get('name')}")
                            # Rollback last_uid
                            sites_col.update_one(
                                {"_id": site["_id"]},
                                {"$set": {"last_uid": site.get("last_uid")}}
                            )
                
                except Exception as e:
                    logging.error(f"Error polling site {site.get('name', site['_id'])}: {str(e)}")
                    sites_col.update_one(
                        {"_id": site["_id"]},
                        {"$inc": {"stats.errors": 1}}
                    )
            
            # Safe polling speed
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
    """Main function - FIXED for Heroku"""
    if not MASTER_BOT_TOKEN:
        print("❌ Error: MASTER_BOT_TOKEN not set!")
        print("Please set MASTER_BOT_TOKEN in environment variables")
        exit(1)
    
    logging.info("Starting AK KING 👑 bot...")
    
    try:
        # Create application with proper settings
        app = ApplicationBuilder()\
            .token(MASTER_BOT_TOKEN)\
            .connection_pool_size(10)\
            .pool_timeout(30)\
            .connect_timeout(10)\
            .read_timeout(10)\
            .write_timeout(10)\
            .build()
        
        # Add handlers in correct order
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("id", my_id))
        app.add_handler(CommandHandler("cancel", lambda u, c: None))
        
        # Add callback handler
        app.add_handler(CallbackQueryHandler(callback_handler))
        
        # Add text handler last
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
        
        # Start poller thread
        start_poller_thread()
        
        # Run the bot
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
