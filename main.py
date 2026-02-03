#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (HEROKU + PYROGRAM SAFE)
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

_shutdown_event = asyncio.Event()
_shutdown_started = False
_poller_task: Optional[asyncio.Task] = None

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
    if _shutdown_event.is_set():
        logger.warning("Startup skipped due to shutdown")
        return

    logger.info("🚀 Starting AK KING 👑 Bot")

    await init_mongo()
    logger.info("✅ MongoDB connected")

    global _poller_task
    if not _shutdown_event.is_set():
        _poller_task = asyncio.create_task(poller_loop(), name="poller")
        logger.info("🔄 Poller task started")

# ============================================
# SHUTDOWN (CRITICAL FIX)
# ============================================

async def shutdown():
    global _shutdown_started

    if _shutdown_started:
        return

    _shutdown_started = True
    logger.warning("🛑 Shutdown initiated")

    # Stop Pyrogram FIRST
    if app.is_connected:
        logger.info("🛑 Stopping Pyrogram client...")
        await app.stop()

    # Stop poller
    global _poller_task
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            logger.info("Poller loop cancelled gracefully")

    _shutdown_event.set()
    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLING (HEROKU SAFE)
# ============================================

def _handle_signal(sig, frame):
    logger.warning(f"Received signal {sig}, shutting down...")
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

        if _shutdown_event.is_set():
            return

        async with app:
            logger.info("🤖 Pyrogram client started")
            await _shutdown_event.wait()

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
