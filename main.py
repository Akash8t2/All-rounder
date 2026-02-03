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
from pyrogram.idle import idle

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
    workers=4,        # Optimal for Heroku
    sleep_threshold=60,  # For Heroku's 30-second timeout
)

# ============================================
# HEROKU HEALTH CHECK SERVER
# ============================================

async def start_health_server():
    """
    Start a simple HTTP server for Heroku health checks
    Required for web dyno to stay alive
    """
    try:
        from aiohttp import web
        
        async def health_check(request):
            return web.Response(text="Bot is running")
        
        app_web = web.Application()
        app_web.router.add_get('/', health_check)
        app_web.router.add_get('/health', health_check)
        
        # Heroku provides PORT environment variable
        port = int(os.environ.get("PORT", 8080))
        
        runner = web.AppRunner(app_web)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        
        logger.info(f"🌐 Health check server running on port {port}")
        return runner
    except ImportError:
        logger.warning("aiohttp not installed, skipping health server")
        return None
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")
        return None

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
        logger.info("🏗️ Running on Heroku dyno")
    
    # MongoDB
    await init_mongo()
    logger.info("✅ MongoDB connected")
    
    # Poller
    global poller_task
    poller_task = asyncio.create_task(
        poller_loop(),
        name="poller_loop"
    )
    logger.info("🔄 Poller task started")
    
    # Start health server for web dyno
    if os.environ.get("PORT"):
        return await start_health_server()
    return None

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
    await app.stop()
    
    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLING (SAME EVENT LOOP)
# ============================================

def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    """
    Install SIGTERM / SIGINT handlers safely.
    """
    def handle_signal():
        asyncio.create_task(shutdown())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, RuntimeError):
            # Some platforms don't support add_signal_handler
            signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(handle_signal))

# ============================================
# MAIN ASYNC FUNCTION - HEROKU ADAPTED
# ============================================

async def main():
    health_runner = None
    try:
        # Startup services including health server
        health_runner = await startup()
        
        # Install signal handlers on current loop
        loop = asyncio.get_running_loop()
        install_signal_handlers(loop)
        
        # Start Pyrogram
        await app.start()
        logger.info("🤖 Pyrogram client started")
        
        # Log bot info
        me = await app.get_me()
        logger.info(f"✅ Bot @{me.username} is ready!")
        
        # Heroku-compatible idle - use asyncio.sleep instead of idle()
        # This prevents Heroku from thinking the app crashed
        logger.info("⏳ Bot is now running...")
        
        # Keep the bot alive
        while True:
            await asyncio.sleep(86400)  # Sleep for 1 day
        
    except asyncio.CancelledError:
        logger.info("Main task cancelled (normal shutdown)")
    except Exception as e:
        logger.critical(f"Fatal error in main loop: {e}", exc_info=True)
    finally:
        # Cleanup health server if running
        if health_runner:
            try:
                await health_runner.cleanup()
                logger.info("✅ Health server stopped")
            except Exception as e:
                logger.error(f"Error stopping health server: {e}")
        
        await shutdown()

# ============================================
# ENTRYPOINT
# ============================================

if __name__ == "__main__":
    # Heroku-friendly entry point
    try:
        # Set event loop policy for Heroku
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        else:
            asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Process interrupted by user")
    except SystemExit:
        logger.info("System exit")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
