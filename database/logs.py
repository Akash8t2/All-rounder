#!/usr/bin/env python3
# ============================================
# LOGS COLLECTION (FIXED + BACKWARD COMPATIBLE)
# ============================================

import logging
from datetime import datetime
from typing import Optional, Dict, List

from pymongo.errors import PyMongoError
from database.mongo import get_db

logger = logging.getLogger("database.logs")


# ============================================
# COLLECTION
# ============================================

def _col():
    return get_db().logs


# ============================================
# LOG LEVELS
# ============================================

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


# ============================================
# CORE LOG INSERT
# ============================================

async def add_log(
    level: str,
    message: str,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
    meta: Optional[Dict] = None,
) -> bool:
    try:
        level = level.upper()
        if level not in LOG_LEVELS:
            level = "INFO"

        doc = {
            "level": level,
            "message": message,
            "user_id": user_id,
            "site_id": site_id,
            "meta": meta or {},
            "timestamp": datetime.utcnow(),
        }

        await _col().insert_one(doc)
        logger.debug(f"Log stored | {level} | site={site_id}")
        return True

    except PyMongoError:
        logger.error("add_log failed", exc_info=True)
        return False


# ============================================
# 🔥 BACKWARD-COMPATIBLE HELPERS (CRITICAL)
# ============================================

async def log_error(
    error_type: str,
    message: str,
    site_id: Optional[str] = None,
):
    """
    Used by poller / services
    """
    logger.error(f"{error_type}: {message}")
    await add_log(
        level="ERROR",
        message=f"{error_type}: {message}",
        site_id=site_id,
    )


async def log_action(
    action: str,
    meta: Optional[Dict] = None,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
):
    """
    Used by poller / admin actions
    """
    logger.info(f"Action: {action}")
    await add_log(
        level="INFO",
        message=action,
        user_id=user_id,
        site_id=site_id,
        meta=meta,
    )


# ============================================
# FETCH LOGS
# ============================================

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
        if user_id:
            query["user_id"] = user_id
        if site_id:
            query["site_id"] = site_id

        cursor = (
            _col()
            .find(query)
            .sort("timestamp", -1)
            .limit(limit)
        )

        return [log async for log in cursor]

    except PyMongoError:
        logger.error("fetch_logs failed", exc_info=True)
        return []


# ============================================
# PURGE OLD LOGS
# ============================================

async def purge_old_logs(days: int = 30) -> int:
    try:
        cutoff = datetime.utcnow().timestamp() - (days * 86400)
        cutoff_dt = datetime.utcfromtimestamp(cutoff)

        result = await _col().delete_many(
            {"timestamp": {"$lt": cutoff_dt}}
        )

        return result.deleted_count

    except PyMongoError:
        logger.error("purge_old_logs failed", exc_info=True)
        return 0


# ============================================
# EXPORTS
# ============================================

__all__ = [
    "add_log",
    "log_error",
    "log_action",
    "fetch_logs",
    "purge_old_logs",
]
