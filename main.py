#!/usr/bin/env python3
# ============================================
# MAIN ENTRY POINT (PYROGRAM • FINAL • SAFE)
# ============================================

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

poller_task: Optional[asyncio.Task] = None
stopping = False

# ============================================
# PYROGRAM CLIENT
# ============================================

app = Client(
    name=APP_NAME,
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=MASTER_BOT_TOKEN,
    in_memory=True,
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
# SHUTDOWN (FINAL & SAFE)
# ============================================

async def shutdown():
    global stopping
    if stopping:
        return
    stopping = True

    logger.warning("🛑 Shutdown initiated")

    if poller_task and not poller_task.done():
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            logger.warning("Poller loop cancelled gracefully")

    logger.info("🛑 Stopping Pyrogram client...")
    await app.stop()

    logger.info("✅ Shutdown complete")

# ============================================
# SIGNAL HANDLING (SAME LOOP)
# ============================================

def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown())
        )

# ============================================
# MAIN
# ============================================

async def main():
    try:
        await startup()

        loop = asyncio.get_running_loop()
        install_signal_handlers(loop)

        await app.start()
        logger.info("🤖 Pyrogram client started")

        await idle()   # <-- Pyrogram-safe blocking

    except Exception:
        logger.critical("Fatal error in main loop", exc_info=True)
    finally:
        await shutdown()

# ============================================
# ENTRYPOINT
# ============================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Process interrupted")
