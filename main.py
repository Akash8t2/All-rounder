#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM + HEROKU SAFE)
# - Pyrogram Client bootstrap
# - MongoDB initialization
# - Async poller startup
# - Graceful shutdown handling
# ============================================

import asyncio
import logging
import signal
import sys

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

# Import handlers to register them
import handlers.start        # noqa: F401
import handlers.admin        # noqa: F401
import handlers.sites        # noqa: F401
import handlers.callbacks    # noqa: F401
import handlers.messages     # noqa: F401

# ============================================
# LOGGING SETUP
# ============================================

setup_logging()
logger = logging.getLogger("main")

# ============================================
# PYROGRAM CLIENT
# ============================================

app = Client(
    name=APP_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=MASTER_BOT_TOKEN,
    in_memory=True,          # Heroku safe
    workdir=".",             # no FS dependency
)

# ============================================
# GLOBAL TASK REFERENCES
# ============================================

_poller_task: asyncio.Task | None = None

# ============================================
# STARTUP ROUTINE
# ============================================

async def startup():
    """
    Initialize DB and background services.
    """
    logger.info("🚀 Starting AK KING 👑 Bot")

    # Init MongoDB
    await init_mongo()
    logger.info("✅ MongoDB connected")

    # Start poller
    global _poller_task
    _poller_task = asyncio.create_task(poller_loop())
    logger.info("🔄 Poller task started")


# ============================================
# SHUTDOWN ROUTINE
# ============================================

async def shutdown():
    """
    Gracefully shutdown background tasks.
    """
    logger.warning("🛑 Shutdown initiated")

    global _poller_task
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            logger.info("Poller task cancelled")

    logger.info("✅ Shutdown complete")


# ============================================
# SIGNAL HANDLING (HEROKU SAFE)
# ============================================

def _handle_signal(sig, frame):
    logger.warning(f"Received signal {sig}, shutting down...")
    asyncio.get_event_loop().create_task(shutdown())


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ============================================
# MAIN ASYNC RUNNER
# ============================================

async def main():
    try:
        await startup()

        async with app:
            logger.info("🤖 Pyrogram client started")
            await asyncio.Event().wait()  # Run forever

    except Exception as e:
        logger.critical(f"Fatal error in main loop: {e}", exc_info=True)
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