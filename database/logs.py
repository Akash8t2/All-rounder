#!/usr/bin/env python3
# ============================================================
# LOGS COLLECTION (PRODUCTION READY – FULL FIX)
# ============================================================
# ✔ Async MongoDB (Motor)
# ✔ poller.py compatible
# ✔ telegram.py compatible
# ✔ Backward compatible helpers
# ✔ Strict error handling
# ✔ No missing imports
# ✔ No silent failures
# ✔ Restart safe (Heroku/VPS)
# ============================================================

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from pymongo.errors import PyMongoError
from database.mongo import get_db

logger = logging.getLogger("database.logs")


# ============================================================
# COLLECTION GETTER
# ============================================================

def _col():
    """
    MongoDB logs collection
    """
    return get_db().logs


# ============================================================
# ALLOWED LOG LEVELS
# ============================================================

LOG_LEVELS = {
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "DEBUG",
    "ADMIN",
    "USER",
    "SYSTEM",
}


# ============================================================
# CORE LOG INSERT (BASE FUNCTION)
# ============================================================

async def add_log(
    level: str,
    message: str,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
    meta: Optional[Dict] = None,
) -> bool:
    """
    Core async log writer (used by all helpers)
    """
    try:
        level = str(level).upper()
        if level not in LOG_LEVELS:
            level = "INFO"

        document = {
            "level": level,
            "message": str(message),
            "user_id": user_id,
            "site_id": site_id,
            "meta": meta or {},
            "timestamp": datetime.utcnow(),
        }

        await _col().insert_one(document)
        logger.debug(f"📝 Log stored | level={level} | site={site_id}")
        return True

    except PyMongoError:
        logger.error("❌ add_log Mongo error", exc_info=True)
        return False

    except Exception:
        logger.error("❌ add_log unexpected error", exc_info=True)
        return False


# ============================================================
# 🔥 BACKWARD-COMPATIBLE HELPERS (CRITICAL)
# ============================================================

async def log_error(
    error_type: str,
    message: str,
    site_id: Optional[str] = None,
):
    """
    REQUIRED by services.poller
    DO NOT REMOVE
    """
    try:
        logger.error(f"{error_type} | {message}")
        await add_log(
            level="ERROR",
            message=f"{error_type}: {message}",
            site_id=site_id,
        )
    except Exception:
        logger.error("❌ log_error wrapper failed", exc_info=True)


async def log_action(
    action: str,
    meta: Optional[Dict] = None,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
):
    """
    REQUIRED by poller / admin actions
    DO NOT REMOVE
    """
    try:
        logger.info(f"ACTION | {action}")
        await add_log(
            level="INFO",
            message=str(action),
            user_id=user_id,
            site_id=site_id,
            meta=meta,
        )
    except Exception:
        logger.error("❌ log_action wrapper failed", exc_info=True)


# ============================================================
# FETCH LOGS (ADMIN / DEBUG USE)
# ============================================================

async def fetch_logs(
    level: Optional[str] = None,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    try:
        query = {}

        if level:
            query["level"] = level.upper()
        if user_id is not None:
            query["user_id"] = user_id
        if site_id:
            query["site_id"] = site_id

        cursor = (
            _col()
            .find(query)
            .sort("timestamp", -1)
            .limit(int(limit))
        )

        return [doc async for doc in cursor]

    except PyMongoError:
        logger.error("❌ fetch_logs Mongo error", exc_info=True)
        return []

    except Exception:
        logger.error("❌ fetch_logs unexpected error", exc_info=True)
        return []


# ============================================================
# PURGE OLD LOGS (MAINTENANCE / CRON SAFE)
# ============================================================

async def purge_old_logs(days: int = 30) -> int:
    """
    Delete logs older than X days
    """
    try:
        cutoff_dt = datetime.utcnow() - timedelta(days=int(days))
        result = await _col().delete_many(
            {"timestamp": {"$lt": cutoff_dt}}
        )
        logger.info(f"🧹 Logs purged | count={result.deleted_count}")
        return result.deleted_count

    except PyMongoError:
        logger.error("❌ purge_old_logs Mongo error", exc_info=True)
        return 0

    except Exception:
        logger.error("❌ purge_old_logs unexpected error", exc_info=True)
        return 0


# ============================================================
# EXPORTS (IMPORT SAFETY)
# ============================================================

__all__ = [
    "add_log",
    "log_error",
    "log_action",
    "fetch_logs",
    "purge_old_logs",
]
