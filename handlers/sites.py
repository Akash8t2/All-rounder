#!/usr/bin/env python3
# ============================================================
# SITES COLLECTION LOGIC (IMPORT-SAFE FINAL FIX)
# ============================================================

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from pymongo.errors import DuplicateKeyError, PyMongoError
from database.mongo import get_db

logger = logging.getLogger("database.sites")


# ============================================================
# COLLECTION
# ============================================================

def _col():
    return get_db().sites


# ============================================================
# CREATE SITE
# ============================================================

async def create_site(user_id: int, site_data: Dict) -> Optional[str]:
    try:
        site_id = str(int(time.time() * 1000))

        doc = {
            "_id": site_id,
            "site_id": site_id,
            "user_id": user_id,
            "name": site_data["name"],
            "ajax": site_data["ajax_url"],
            "ajax_type": "unknown",
            "ajax_columns": None,
            "ajax_auto_detected": False,
            "enabled": True,
            "bot_token": site_data["bot_token"],
            "bot_username": site_data["bot_username"],
            "chat_ids": site_data["chat_ids"],
            "cookies": site_data.get("cookies", {}),
            "headers": site_data.get("headers", {}),
            "buttons": site_data.get("buttons", []),
            "sms_format": {
                "template": site_data.get("sms_template"),
                "updated_at": datetime.utcnow(),
            },
            "stats": {
                "today": 0,
                "total": 0,
                "errors": {
                    "total": 0,
                    "http_error": 0,
                    "json_decode": 0,
                    "html_login": 0,
                    "telegram_send": 0,
                    "poll_exception": 0,
                },
                "last_success": None,
            },
            "last_error": None,
            "cookie_status": "unknown",
            "cookie_status_updated": None,
            "last_uid": None,
            "last_check": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        await _col().insert_one(doc)
        logger.info(f"✅ Site created | {site_id}")
        return site_id

    except DuplicateKeyError:
        logger.warning("Duplicate site_id")
        return None
    except PyMongoError:
        logger.error("create_site failed", exc_info=True)
        return None


# ============================================================
# FETCH
# ============================================================

async def get_site_by_id(site_id: str) -> Optional[Dict]:
    try:
        return await _col().find_one({"_id": site_id})
    except PyMongoError:
        logger.error("get_site_by_id failed", exc_info=True)
        return None


async def get_enabled_sites() -> List[Dict]:
    try:
        cursor = _col().find({"enabled": True})
        return [s async for s in cursor]
    except PyMongoError:
        logger.error("get_enabled_sites failed", exc_info=True)
        return []


# ============================================================
# POLLER HELPERS
# ============================================================

async def update_site_last_check(site_id: str):
    try:
        await _col().update_one(
            {"_id": site_id},
            {"$set": {"last_check": datetime.utcnow()}},
        )
    except PyMongoError:
        logger.error("update_site_last_check failed", exc_info=True)


async def update_site_on_success(site_id: str, last_uid: str):
    try:
        await _col().update_one(
            {"_id": site_id},
            {
                "$set": {
                    "last_uid": last_uid,
                    "stats.last_success": datetime.utcnow(),
                    "cookie_status": "valid",
                    "cookie_status_updated": datetime.utcnow(),
                },
                "$inc": {
                    "stats.today": 1,
                    "stats.total": 1,
                },
            },
        )
    except PyMongoError:
        logger.error("update_site_on_success failed", exc_info=True)


async def update_site_ajax_meta(site_id: str, ajax_type: str, ajax_columns: int):
    try:
        await _col().update_one(
            {"_id": site_id},
            {
                "$set": {
                    "ajax_type": ajax_type,
                    "ajax_columns": ajax_columns,
                    "ajax_auto_detected": True,
                    "ajax_detected_at": datetime.utcnow(),
                }
            },
        )
    except PyMongoError:
        logger.error("update_site_ajax_meta failed", exc_info=True)


async def increment_site_error(site_id: str, error_type: str):
    try:
        await _col().update_one(
            {"_id": site_id},
            {
                "$inc": {
                    "stats.errors.total": 1,
                    f"stats.errors.{error_type}": 1,
                },
                "$set": {
                    "last_error": {
                        "type": error_type,
                        "time": datetime.utcnow().isoformat(),
                        "message": error_type,
                    }
                },
            },
        )
    except PyMongoError:
        logger.error("increment_site_error failed", exc_info=True)


# ============================================================
# 🔥 IMPORT-SAFE ERROR REPORT (THIS FIXES HEROKU CRASH)
# ============================================================

async def _async_get_site_error_report(site_id: str) -> Dict[str, int]:
    try:
        site = await _col().find_one(
            {"_id": site_id},
            {"stats.errors": 1, "_id": 0},
        )
        return site.get("stats", {}).get("errors", {}) if site else {}
    except PyMongoError:
        logger.error("get_site_error_report failed", exc_info=True)
        return {}


def get_site_error_report(site_id: str) -> Dict[str, int]:
    """
    🔒 SYNC SAFE EXPORT
    Required by handlers.callbacks at import time
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(_async_get_site_error_report(site_id))


# ============================================================
# COOKIE STATUS
# ============================================================

async def update_site_cookie_status(site_id: str, status: str):
    try:
        await _col().update_one(
            {"_id": site_id},
            {
                "$set": {
                    "cookie_status": status,
                    "cookie_status_updated": datetime.utcnow(),
                }
            },
        )
    except PyMongoError:
        logger.error("update_site_cookie_status failed", exc_info=True)


# ============================================================
# EXPLICIT EXPORTS (CRITICAL)
# ============================================================

__all__ = [
    "create_site",
    "get_site_by_id",
    "get_enabled_sites",
    "update_site_last_check",
    "update_site_on_success",
    "update_site_ajax_meta",
    "increment_site_error",
    "get_site_error_report",
    "update_site_cookie_status",
]
