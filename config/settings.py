#!/usr/bin/env python3
# ============================================
# GLOBAL SETTINGS & ENV VALIDATION
# ============================================

import os
import sys
import logging
from dotenv import load_dotenv

# Load .env if exists (Heroku ignores, VPS uses)
load_dotenv()

# ============================================
# REQUIRED ENV VARIABLES
# ============================================

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = os.getenv("OWNER_ID")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# Optional / Tunables
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "10"))  # seconds
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TIMEZONE = os.getenv("TIMEZONE", "UTC")

# ============================================
# VALIDATION (STRICT – FAIL FAST)
# ============================================

def _fatal(msg: str):
    print(f"❌ CONFIG ERROR: {msg}")
    sys.exit(1)

if not MASTER_BOT_TOKEN:
    _fatal("MASTER_BOT_TOKEN is not set")

if ":" not in MASTER_BOT_TOKEN or len(MASTER_BOT_TOKEN) < 30:
    _fatal("MASTER_BOT_TOKEN format looks invalid")

if not MONGO_URI:
    _fatal("MONGO_URI is not set")

try:
    OWNER_ID = int(OWNER_ID)
except Exception:
    _fatal("OWNER_ID must be a valid integer Telegram user ID")

if CHECK_INTERVAL < 5:
    _fatal("CHECK_INTERVAL too low (minimum 5 seconds)")

# ============================================
# LOGGING CONFIG (GLOBAL)
# ============================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("config")

logger.info("✅ Configuration loaded successfully")
logger.info(f"Owner ID: {OWNER_ID}")
logger.info(f"Check interval: {CHECK_INTERVAL}s")
logger.info(f"Timezone: {TIMEZONE}")

# ============================================
# EXPORTED SETTINGS
# ============================================

__all__ = [
    "MASTER_BOT_TOKEN",
    "MONGO_URI",
    "OWNER_ID",
    "CHECK_INTERVAL",
    "LOG_LEVEL",
    "TIMEZONE",
]
