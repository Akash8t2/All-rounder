#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM + HEROKU SAFE)
# ============================================
# FEATURES:
# - Async-safe startup & shutdown
# - Pyrogram graceful stop (FIXES R12)
# - MongoDB initialization
# - Async poller lifecycle handling
# - Heroku SIGTERM compatible
# ============================================

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

# Register handlers (side-effect imports)
import handlers.start        # noqa: F401
import handlers.admin        # noqa: F401
import handlers.sites        # noqa: F401
import handlers.callbacks    # noqa: F401
import handlers.messages     # noqa: F401

# ============================================
# LOGGING
# ============================================

setup_logging()
logger = logging.getLogger("main")

# ============================================
# PYROGRAM CLIENT
# ============================================

app = Client(
    name=APP_NAME,
    api_id=int(API_ID),          # MUST be int
    api_hash=API_HASH,
    bot_token=MASTER_BOT_TOKEN,
    in_memory=True,              # Heroku safe
    workdir=".",                 # No FS dependency
)

# ============================================
# GLOBAL STATE
# ============================================

_poller_task: Optional[asyncio.Task] = None
_shutdown_event = asyncio.Event()

# ============================================
# STARTUP
# ============================================

async def startup():
    logger.info("🚀 Starting AK KING 👑 Bot")

    # MongoDB
    await init_mongo()
    logger.info("✅ MongoDB connected")

    # Poller
    global _poller_task
    _poller_task = asyncio.create_task(poller_loop(), name="poller")
    logger.info("🔄 Poller task started")

# ============================================
# SHUTDOWN (CRITICAL FIX)
# ============================================

async def shutdown():
    logger.warning("🛑 Shutdown initiated")

    global _poller_task

    # Stop poller
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            logger.info("Poller task cancelled")

    # Stop Pyrogram
    if app.is_connected:
        logger.info("🛑 Stopping Pyrogram client...")
        await app.stop()

    _shutdown_event.set()
    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLING (HEROKU SAFE)
# ============================================

def _handle_signal(sig, frame):
    logger.warning(f"📴 Received signal {sig}, initiating shutdown")

    loop = asyncio.get_event_loop()

    if not _shutdown_event.is_set():
        loop.create_task(shutdown())

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ============================================
# MAIN
# ============================================

async def main():
    try:
        await startup()

        async with app:
            logger.info("🤖 Pyrogram client started")
            await _shutdown_event.wait()

    except Exception as e:
        logger.critical("🔥 Fatal error in main loop", exc_info=True)
        await shutdown()
        sys.exit(1)

# ============================================
# ENTRYPOINT
# ============================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Process interrupted")
