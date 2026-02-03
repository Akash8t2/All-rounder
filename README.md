"""
OTP MASTER BOT – ALL-ROUNDER
==================================================

Author        : @botcasx
Language      : Python 3.10+
Framework     : Pyrogram (Async)
Database      : MongoDB (Motor – Async)
Status        : Production Ready
Uptime        : 24x7 VPS / Heroku Safe
Restart Safe  : YES (MongoDB driven)

--------------------------------------------------
WHAT THIS PROJECT IS
--------------------------------------------------

OTP Master Bot is a fully automated Telegram OTP
forwarding system written purely in Python.

The bot continuously monitors AJAX based SMS panels
(INTS and non-INTS websites).

Whenever a new SMS / OTP is detected:
- OTP is extracted safely
- Duplicate OTPs are ignored
- Message is formatted per-site
- Forwarded instantly to Telegram chats

This project is designed for:
• Stability
• Scalability
• Multiple websites
• Zero manual intervention


--------------------------------------------------
MAIN HIGHLIGHTS
--------------------------------------------------

✔ Auto-detect AJAX structure
✔ Works with different SMS panels
✔ Per-site bot token support
✔ Per-site chat ID support
✔ Cookie expiry detection
✔ Error analytics
✔ Admin + Owner security
✔ Restart safe (state in DB)
✔ Production hardened


--------------------------------------------------
AJAX AUTO-DETECTION SYSTEM
--------------------------------------------------

The bot automatically detects the AJAX type
by analyzing column structure.

Column Mapping:
- 7 columns  → ints_client
- 9 columns  → ints_agent
- >9 columns → extended / custom
- Unknown    → safely ignored

No hard-coded dependency exists.
Each site is handled independently.


--------------------------------------------------
OTP HANDLING LOGIC
--------------------------------------------------

• OTP length: 4–8 digits
• Multi-language SMS supported
• Regex hardened extraction
• Duplicate protection using last_uid
• Masked phone numbers (optional)
• Per-site SMS template support


--------------------------------------------------
TELEGRAM FEATURES
--------------------------------------------------

• Separate bot token for each site
• Multiple chat IDs per site
• Groups, private chats, channels supported
• Inline buttons (max 4)
• Button enable / disable
• Button text & URL editable
• Safe Telegram API handling


--------------------------------------------------
ERROR HANDLING & ALERTS
--------------------------------------------------

• HTTP error tracking
• JSON decode error tracking
• Telegram send error tracking
• Per-site error counters
• Cookie expiry auto-detection
• One-time admin alert (no spam)
• AJAX test button (safe test mode)


--------------------------------------------------
SECURITY MODEL
--------------------------------------------------

• Owner system (full control)
• Admin system (limited control)
• Unauthorized users blocked
• Flood / spam protection
• Token & cookie validation
• Admin actions logged


--------------------------------------------------
TECH STACK (PURE PYTHON)
--------------------------------------------------

• Python 3.10+
• Pyrogram (Async Telegram client)
• MongoDB (Motor async driver)
• aiohttp (non-blocking HTTP)
• Logging module
• Modular architecture


--------------------------------------------------
PROJECT STRUCTURE
--------------------------------------------------

.
├── app.json              # Heroku deployment config
├── Procfile              # Worker definition
├── runtime.txt           # Python version
├── version.txt
├── requirements.txt
├── main.py
│
├── config/
│   └── settings.py
│
├── database/
│   ├── mongo.py
│   ├── users.py
│   ├── admins.py
│   ├── sites.py
│   ├── logs.py
│   └── settings.py
│
├── handlers/
│   ├── start.py
│   ├── admin.py
│   ├── sites.py
│   ├── callbacks.py
│   └── messages.py
│
├── services/
│   ├── poller.py
│   ├── telegram.py
│   ├── formatter.py
│   └── security.py
│
└── utils/
    ├── otp.py
    ├── country.py
    ├── helpers.py
    └── logger.py


--------------------------------------------------
HEROKU DEPLOYMENT (OFFICIAL)
--------------------------------------------------

This project supports ONE-CLICK Heroku deployment.

Heroku Deploy Button:
https://heroku.com/deploy?template=https://github.com/Akash8t2/All-rounder

Required Environment Variables:

API_ID          = Telegram API ID
API_HASH        = Telegram API HASH
BOT_TOKEN       = Main bot token
OWNER_ID        = Telegram numeric user ID
MONGO_URI       = MongoDB connection string
CHECK_INTERVAL  = Poll interval (default: 10 seconds)
TZ              = Timezone (UTC recommended)


--------------------------------------------------
LOCAL / VPS DEPLOYMENT
--------------------------------------------------

Steps:
1. Clone repository
2. Create virtual environment
3. Install requirements
4. Run main.py

Example:

git clone https://github.com/Akash8t2/All-rounder
cd All-rounder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py


--------------------------------------------------
SUPPORTED AJAX RESPONSE FORMAT
--------------------------------------------------

Example:

{
  "aaData": [
    [
      "2026-01-30 07:59:08",
      "Egypt Fly TW05",
      "201113456917",
      "WhatsApp",
      "Your WhatsApp code is 785072",
      "$",
      0
    ]
  ]
}

The system will:
• Auto-detect structure
• Extract OTP
• Forward to Telegram


--------------------------------------------------
ADMIN COMMANDS
--------------------------------------------------

/start
/addadmin <id>
/removeadmin <id>
/listadmins
/access


--------------------------------------------------
SUPPORT & CONTACT
--------------------------------------------------

Telegram : @botcasx
GitHub   : https://github.com/Akash8t2/All-rounder


--------------------------------------------------
DISCLAIMER
--------------------------------------------------

This project is intended for legitimate OTP monitoring
and forwarding purposes only.

The developer is not responsible for misuse.


--------------------------------------------------
FINAL VERIFICATION
--------------------------------------------------

✔ Python-style documentation
✔ Deployment button included
✔ No markdown dependency
✔ Production ready
✔ Rule compliant
✔ Clean & professional
"""
