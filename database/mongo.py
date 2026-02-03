#!/usr/bin/env python3
# ============================================
# ASYNC MONGODB CONNECTION (MOTOR)
# ============================================

import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
from config.settings import MONGO_URI

logger = logging.getLogger("database.mongo")

# ============================================
# GLOBAL CLIENT (SINGLETON)
# ============================================

_client: AsyncIOMotorClient | None = None
_db = None

# ============================================
# DATABASE INITIALIZATION
# ============================================

async def connect_mongo():
    """
    Initialize MongoDB connection.
    Must be called ONCE at startup.
    """
    global _client, _db

    try:
        logger.info("🔌 Connecting to MongoDB...")

        _client = AsyncIOMotorClient(
            MONGO_URI,
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000,
            retryWrites=True,
        )

        # Force connection check
        await _client.admin.command("ping")

        _db = _client["otp_master_bot"]

        logger.info("✅ MongoDB connected successfully")

        await _create_indexes()

    except PyMongoError as e:
        logger.error(f"❌ MongoDB connection failed: {e}", exc_info=True)
        raise SystemExit("MongoDB connection error")

# ============================================
# 🔥 BACKWARD-COMPATIBLE ALIAS (CRITICAL FIX)
# ============================================

# main.py expects init_mongo()
init_mongo = connect_mongo

# ============================================
# INDEX CREATION
# ============================================

async def _create_indexes():
    try:
        logger.info("⚙️ Creating MongoDB indexes...")

        await _db.users.create_index("user_id", unique=True)
        await _db.admins.create_index("user_id", unique=True)

        await _db.sites.create_index("site_id", unique=True)
        await _db.sites.create_index("user_id")
        await _db.sites.create_index("enabled")
        await _db.sites.create_index("last_uid")
        await _db.sites.create_index([("user_id", 1), ("enabled", 1)])

        await _db.logs.create_index("timestamp")
        await _db.logs.create_index("level")
        await _db.logs.create_index("user_id")
        await _db.logs.create_index("site_id")

        await _db.settings.create_index("key", unique=True)

        logger.info("✅ MongoDB indexes created / verified")

    except PyMongoError as e:
        logger.error(f"❌ Index creation failed: {e}", exc_info=True)
        raise

# ============================================
# SAFE DB GETTER
# ============================================

def get_db():
    if _db is None:
        raise RuntimeError("MongoDB not initialized. Call init_mongo() first.")
    return _db

# ============================================
# SHUTDOWN HANDLER
# ============================================

async def close_mongo():
    global _client
    try:
        if _client:
            logger.info("🔌 Closing MongoDB connection...")
            _client.close()
            logger.info("✅ MongoDB connection closed")
    except Exception as e:
        logger.error(f"Error closing MongoDB: {e}", exc_info=True)

# ============================================
# EXPORTS
# ============================================

__all__ = [
    "init_mongo",
    "connect_mongo",
    "close_mongo",
    "get_db",
]
