#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM • HEROKU SAFE • FIXED)
# ============================================

import os
import asyncio
import logging
import signal
import sys
from typing import Optional

from pyrogram import Client
try:
    from pyrogram import idle  # Pyrogram v2.0+
except ImportError:
    from pyrogram.idle import idle  # Old versions

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
shutting_down = False
app_instance: Optional[Client] = None

# ============================================
# PYROGRAM CLIENT
# ============================================

def create_client() -> Client:
    return Client(
        name=APP_NAME,
        api_id=int(API_ID),
        api_hash=API_HASH,
        bot_token=MASTER_BOT_TOKEN,
        in_memory=True,
        workers=2,
        sleep_threshold=30,
    )

# ============================================
# STARTUP LOGIC
# ============================================

async def startup():
    """
    Initialize database and background services.
    """
    global app_instance
    
    logger.info("🚀 Starting AK KING 👑 Bot on Heroku")
    
    if os.environ.get("DYNO"):
        logger.info(f"🏗️ Running on Heroku dyno: {os.environ.get('DYNO')}")
    
    # Initialize MongoDB
    await init_mongo()
    logger.info("✅ MongoDB connected")
    
    # Create and store app instance
    app_instance = create_client()
    
    # Start poller
    global poller_task
    poller_task = asyncio.create_task(
        poller_loop(),
        name="poller_loop"
    )
    logger.info("🔄 Poller task started")

# ============================================
# SHUTDOWN LOGIC (FIXED EVENT LOOP)
# ============================================

async def shutdown():
    """
    Graceful shutdown with proper event loop handling.
    """
    global shutting_down, poller_task, app_instance
    
    if shutting_down:
        return
    
    shutting_down = True
    logger.warning("🛑 Shutdown initiated")
    
    # Stop poller task first
    if poller_task and not poller_task.done():
        try:
            poller_task.cancel()
            await asyncio.wait_for(poller_task, timeout=5)
            logger.info("✅ Poller task stopped")
        except asyncio.CancelledError:
            logger.info("Poller task cancelled")
        except Exception as e:
            logger.error(f"Error stopping poller: {e}")
    
    # Stop Pyrogram client
    if app_instance:
        try:
            logger.info("🛑 Stopping Pyrogram client...")
            # Stop dispatchers first
            if hasattr(app_instance, 'dispatcher'):
                app_instance.dispatcher.stop()
            
            # Then stop the client
            await app_instance.stop()
            logger.info("✅ Pyrogram client stopped")
        except Exception as e:
            logger.error(f"Error stopping Pyrogram: {e}")
    
    # Cancel all pending tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"Cancelling {len(tasks)} pending tasks...")
        for task in tasks:
            task.cancel()
        
        # Wait for tasks to complete
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
    
    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLING
# ============================================

def handle_signal():
    """Signal handler wrapper"""
    logger.info("Signal received, initiating shutdown...")
    asyncio.create_task(shutdown())

# ============================================
# MAIN ASYNC FUNCTION
# ============================================

async def main():
    """Main application entry point"""
    try:
        # Startup sequence
        await startup()
        
        # Start the client
        await app_instance.start()
        logger.info("🤖 Pyrogram client started")
        
        # Get bot info
        me = await app_instance.get_me()
        logger.info(f"✅ Bot @{me.username} (ID: {me.id}) is ready!")
        
        # Install signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal)
        
        # Keep the bot running
        logger.info("⏳ Bot is now running...")
        
        # Create a future that never completes (until signal)
        await asyncio.Future()
        
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.critical(f"Fatal error in main loop: {e}", exc_info=True)
        raise
    finally:
        if not shutting_down:
            await shutdown()

# ============================================
# ENTRYPOINT (HEROKU COMPATIBLE)
# ============================================

if __name__ == "__main__":
    # Heroku-friendly entry point
    try:
        # Check required environment variables
        required_vars = ["API_ID", "API_HASH", "MASTER_BOT_TOKEN"]
        missing = [var for var in required_vars if not os.environ.get(var)]
        
        if missing:
            logger.error(f"Missing env vars: {missing}")
            logger.error("Set in Heroku: heroku config:set KEY=VALUE")
            sys.exit(1)
        
        # Run the application
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(0)
    except SystemExit as e:
        logger.info(f"System exit with code {e.code}")
        raise
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
