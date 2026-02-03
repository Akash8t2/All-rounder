#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM • HEROKU SAFE • FINAL)
# ============================================

import os
import asyncio
import logging
import signal
import sys
from typing import Optional

from pyrogram import Client

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
# IMPORT HANDLER MODULES
# (they expose register(app))
# ============================================

import handlers.start
import handlers.admin
import handlers.sites
import handlers.callbacks
import handlers.messages

# ============================================
# LOGGING SETUP
# ============================================

setup_logging()
logger = logging.getLogger("__main__")

# ============================================
# GLOBAL STATE
# ============================================

poller_task: Optional[asyncio.Task] = None
shutdown_event: Optional[asyncio.Event] = None
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
        in_memory=True,      # Heroku safe
        workers=2,
        sleep_threshold=30,
    )

# ============================================
# STARTUP
# ============================================

async def startup():
    global app_instance, poller_task

    logger.info("🚀 Starting AK KING 👑 Bot on Heroku")

    if os.environ.get("DYNO"):
        logger.info(f"🏗️ Dyno: {os.environ.get('DYNO')}")

    # MongoDB
    await init_mongo()
    logger.info("✅ MongoDB connected")

    # Create client
    app_instance = create_client()

    # 🔥 REGISTER HANDLERS ON THIS CLIENT
    handlers.start.register(app_instance)
    handlers.admin.register(app_instance)
    handlers.sites.register(app_instance)
    handlers.callbacks.register(app_instance)
    handlers.messages.register(app_instance)

    logger.info("✅ Handlers registered")

    # Start poller
    poller_task = asyncio.create_task(
        poller_loop(),
        name="poller_loop",
    )
    logger.info("🔄 Poller task started")

# ============================================
# SHUTDOWN
# ============================================

async def shutdown():
    global poller_task, app_instance, shutdown_event

    logger.warning("🛑 Shutdown initiated")

    if shutdown_event:
        shutdown_event.set()

    # Stop poller
    if poller_task and not poller_task.done():
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            logger.info("Poller cancelled")

    # Stop pyrogram client
    if app_instance:
        try:
            logger.info("🛑 Stopping Pyrogram client…")
            await app_instance.stop()
            logger.info("✅ Pyrogram stopped")
        except Exception as e:
            logger.error(f"Pyrogram stop error: {e}")

    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLER
# ============================================

def _signal_handler():
    logger.warning("📴 SIGTERM/SIGINT received")
    asyncio.create_task(shutdown())

# ============================================
# MAIN LOOP
# ============================================

async def main():
    global shutdown_event

    shutdown_event = asyncio.Event()

    try:
        await startup()

        await app_instance.start()
        logger.info("🤖 Pyrogram client started")

        me = await app_instance.get_me()
        logger.info(f"✅ Bot @{me.username} (ID: {me.id}) ready")

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
        loop.add_signal_handler(signal.SIGINT, _signal_handler)

        logger.info("⏳ Bot running…")
        await shutdown_event.wait()

    except Exception as e:
        logger.critical("Fatal error", exc_info=True)
        raise
    finally:
        await shutdown()

# ============================================
# ENTRYPOINT
# ============================================

if __name__ == "__main__":
    try:
        # Env check
        for key in ("API_ID", "API_HASH", "MASTER_BOT_TOKEN"):
            if not os.environ.get(key):
                raise RuntimeError(f"Missing env var: {key}")

        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Process interrupted")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
