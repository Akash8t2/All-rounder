#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM • FINAL • HEROKU SAFE)
# ============================================

import os
import asyncio
import logging
import signal
import sys
from typing import Optional

from pyrogram import Client
# Pyrogram v2.0+ compatible idle import
try:
    from pyrogram import idle  # For Pyrogram v2.0+
except ImportError:
    from pyrogram.idle import idle  # For older Pyrogram

from config.settings import (
    API_ID,
    API_HASH,
    MASTER_BOT_TOKEN,
    APP_NAME,
)

from utils.logger import setup_logging
from database.mongo import init_mongo
from services.poller import poller_loop

# ============================================
# IMPORT HANDLERS (REGISTER ON LOAD)
# ============================================

import handlers.start        # noqa: F401
import handlers.admin        # noqa: F401
import handlers.sites        # noqa: F401
import handlers.callbacks    # noqa: F401
import handlers.messages     # noqa: F401

# ============================================
# LOGGING SETUP
# ============================================

setup_logging()
logger = logging.getLogger("__main__")

# ============================================
# GLOBAL STATE
# ============================================

poller_task: Optional[asyncio.Task] = None
stopping: bool = False

# ============================================
# PYROGRAM CLIENT
# ============================================

app = Client(
    name=APP_NAME,
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=MASTER_BOT_TOKEN,
    in_memory=True,   # Heroku safe
    workers=2,        # Reduced for Heroku free tier
)

# ============================================
# SIMPLE HEROKU PING SERVER
# ============================================

async def keep_alive_ping():
    """Simple ping to keep Heroku dyno alive"""
    import aiohttp
    
    # Ping every 5 minutes
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                # Ping your own app or external service
                heroku_app_name = os.environ.get("HEROKU_APP_NAME")
                if heroku_app_name:
                    url = f"https://{heroku_app_name}.herokuapp.com"
                    async with session.get(url, timeout=10):
                        logger.debug("Ping sent to keep dyno alive")
        except Exception as e:
            logger.debug(f"Ping failed: {e}")
        
        await asyncio.sleep(300)  # 5 minutes

# ============================================
# STARTUP LOGIC
# ============================================

async def startup():
    """
    Initialize database and background services.
    """
    logger.info("🚀 Starting AK KING 👑 Bot on Heroku")
    
    # Check Heroku environment
    if os.environ.get("DYNO"):
        logger.info(f"🏗️ Running on Heroku dyno: {os.environ.get('DYNO')}")
    
    # MongoDB
    await init_mongo()
    logger.info("✅ MongoDB connected")
    
    # Start poller
    global poller_task
    poller_task = asyncio.create_task(
        poller_loop(),
        name="poller_loop"
    )
    logger.info("🔄 Poller task started")
    
    # Start keep-alive ping for worker dyno
    if os.environ.get("DYNO"):
        asyncio.create_task(keep_alive_ping(), name="keep_alive")

# ============================================
# SHUTDOWN LOGIC (SAFE & SINGLE LOOP)
# ============================================

async def shutdown():
    """
    Graceful shutdown – runs ONLY once.
    """
    global stopping
    
    if stopping:
        return
    
    stopping = True
    logger.warning("🛑 Shutdown initiated")
    
    # Stop poller
    if poller_task and not poller_task.done():
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            logger.warning("Poller loop cancelled gracefully")
        except Exception as e:
            logger.error(f"Error stopping poller: {e}")
    
    # Stop Pyrogram
    logger.info("🛑 Stopping Pyrogram client...")
    try:
        await app.stop()
    except Exception as e:
        logger.error(f"Error stopping app: {e}")
    
    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLING (SAME EVENT LOOP)
# ============================================

def install_signal_handlers():
    """
    Install SIGTERM / SIGINT handlers safely.
    """
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

# ============================================
# MAIN ASYNC FUNCTION - HEROKU ADAPTED
# ============================================

async def main():
    try:
        # Install signal handlers
        install_signal_handlers()
        
        # Startup services
        await startup()
        
        # Start Pyrogram
        await app.start()
        logger.info("🤖 Pyrogram client started")
        
        # Log bot info
        me = await app.get_me()
        logger.info(f"✅ Bot @{me.username} is ready!")
        
        # Heroku-compatible - use idle or wait
        logger.info("⏳ Bot is now running on Heroku...")
        
        # For Heroku worker dyno, we need to keep running
        # idle() will keep the bot running until stopped
        await idle()
        
    except asyncio.CancelledError:
        logger.info("Main task cancelled (normal shutdown)")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.critical(f"Fatal error in main loop: {e}", exc_info=True)
        raise
    finally:
        await shutdown()

# ============================================
# ENTRYPOINT
# ============================================

if __name__ == "__main__":
    # Heroku-friendly entry point
    try:
        # Check for required environment variables
        required_vars = ["API_ID", "API_HASH", "MASTER_BOT_TOKEN"]
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            logger.error(f"Missing environment variables: {missing_vars}")
            logger.error("Please set these in Heroku config vars")
            sys.exit(1)
        
        # Run the bot
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.warning("Process interrupted by user")
    except SystemExit:
        logger.info("System exit")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
