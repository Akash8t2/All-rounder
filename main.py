#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM • HEROKU • SAFE)
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

# Register handlers
import handlers.start        # noqa: F401
import handlers.admin        # noqa: F401
import handlers.sites        # noqa: F401
import handlers.callbacks    # noqa: F401
import handlers.messages     # noqa: F401

# ============================================
# LOGGING
# ============================================

setup_logging()
logger = logging.getLogger("__main__")

# ============================================
# GLOBAL STATE
# ============================================

shutdown_event = asyncio.Event()
poller_task: Optional[asyncio.Task] = None

# ============================================
# PYROGRAM CLIENT
# ============================================

app = Client(
    name=APP_NAME,
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=MASTER_BOT_TOKEN,
    in_memory=True,
    workdir=".",
)

# ============================================
# STARTUP
# ============================================

async def startup():
    logger.info("🚀 Starting AK KING 👑 Bot")

    await init_mongo()
    logger.info("✅ MongoDB connected")

    global poller_task
    poller_task = asyncio.create_task(poller_loop(), name="poller")
    logger.info("🔄 Poller task started")

# ============================================
# SHUTDOWN (FIXED)
# ============================================

async def shutdown():
    logger.warning("🛑 Shutdown initiated")

    if poller_task and not poller_task.done():
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            logger.warning("Poller loop cancelled gracefully")

    shutdown_event.set()
    logger.info("✅ Shutdown signal set")

# ============================================
# SIGNAL HANDLING (SAFE)
# ============================================

def _handle_signal(sig, frame):
    logger.warning(f"📴 Received signal {sig}, initiating shutdown")
    if not shutdown_event.is_set():
        shutdown_event.set()

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
            await shutdown_event.wait()

    except Exception:
        logger.critical("Fatal error in main loop", exc_info=True)
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
