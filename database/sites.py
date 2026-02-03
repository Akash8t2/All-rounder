#!/usr/bin/env python3
# ============================================================
# SITES COLLECTION LOGIC (FULLY FIXED & PRODUCTION SAFE)
# ============================================================
# ✔ Async MongoDB (Motor)
# ✔ Backward compatible (poller safe)
# ✔ Auto-detect AJAX metadata
# ✔ Per-site error analytics
# ✔ Cookie expiry tracking
# ✔ Dedup protection
# ✔ Atomic updates
# ✔ ZERO missing imports / functions
# ============================================================

import logging
import time
from datetime import datetime
from typing import List, Dict, Optional

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

        document = {
            "_id": site_id,
            "site_id": site_id,
            "user_id": user_id,

            # Core
            "name": site_data["name"],
            "ajax": site_data["ajax_url"],
            "ajax_type": site_data.get("ajax_type", "unknown"),
            "ajax_columns": None,
            "ajax_auto_detected": False,

            "enabled": True,

            # Telegram
            "bot_token": site_data["bot_token"],
            "bot_username": site_data["bot_username"],
            "chat_ids": site_data.get("chat_ids", []),

            # HTTP
            "cookies": site_data.get("cookies", {}),
            "headers": site_data.get("headers", {}),

            # Buttons
            "buttons": site_data.get("buttons", []),

            # SMS format
            "sms_format": {
                "template": site_data.get("sms_template"),
                "updated_at": datetime.utcnow(),
            },

            # Stats & error buckets
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

            # Error tracking
            "last_error": None,

            # Cookie status
            "cookie_status": "unknown",
            "cookie_status_updated": None,

            # Dedup / poller
            "last_uid": None,
            "last_check": None,

            # Meta
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        await _col().insert_one(document)
        logger.info(f"✅ Site created | site_id={site_id}")
        return site_id

    except DuplicateKeyError:
        logger.warning("⚠️ Duplicate site_id")
        return None
    except PyMongoError:
        logger.error("❌ create_site failed", exc_info=True)
        return None


# ============================================================
# FETCH
# ============================================================

async def get_site(site_id: str) -> Optional[Dict]:
    try:
        return await _col().find_one({"_id": site_id})
    except PyMongoError:
        logger.error("get_site failed", exc_info=True)
        return None


async def list_sites(user_id: Optional[int] = None) -> List[Dict]:
    try:
        q = {} if user_id is None else {"user_id": user_id}
        cur = _col().find(q).sort("created_at", -1)
        return [s async for s in cur]
    except PyMongoError:
        logger.error("list_sites failed", exc_info=True)
        return []


async def list_active_sites() -> List[Dict]:
    try:
        cur = _col().find({"enabled": True})
        return [s async for s in cur]
    except PyMongoError:
        logger.error("list_active_sites failed", exc_info=True)
        return []


# ============================================================
# GENERIC UPDATE
# ============================================================

async def update_site(site_id: str, updates: Dict) -> bool:
    try:
        updates["updated_at"] = datetime.utcnow()
        res = await _col().update_one({"_id": site_id}, {"$set": updates})
        return res.modified_count > 0
    except PyMongoError:
        logger.error("update_site failed", exc_info=True)
        return False


async def toggle_site(site_id: str, enabled: bool) -> bool:
    return await update_site(site_id, {"enabled": enabled})


async def delete_site(site_id: str) -> bool:
    try:
        res = await _col().delete_one({"_id": site_id})
        return res.deleted_count > 0
    except PyMongoError:
        logger.error("delete_site failed", exc_info=True)
        return False


# ============================================================
# POLLER HELPERS
# ============================================================

async def update_last_check(site_id: str):
    try:
        await _col().update_one(
            {"_id": site_id},
            {"$set": {"last_check": datetime.utcnow()}},
        )
    except PyMongoError:
        logger.error("update_last_check failed", exc_info=True)


async def update_on_success(site_id: str, last_uid: str):
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
        logger.error("update_on_success failed", exc_info=True)


# ============================================================
# AJAX META
# ============================================================

async def update_ajax_meta(site_id: str, ajax_type: str, columns: int):
    try:
        await _col().update_one(
            {"_id": site_id},
            {
                "$set": {
                    "ajax_type": ajax_type,
                    "ajax_columns": columns,
                    "ajax_auto_detected": True,
                    "ajax_detected_at": datetime.utcnow(),
                }
            },
        )
    except PyMongoError:
        logger.error("update_ajax_meta failed", exc_info=True)


# ============================================================
# ERROR ANALYTICS
# ============================================================

async def increment_error(site_id: str, error_type: str):
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
                        "time": datetime.utcnow(),
                    }
                },
            },
        )
    except PyMongoError:
        logger.error("increment_error failed", exc_info=True)


async def get_error_report(site_id: str) -> Dict[str, int]:
    try:
        site = await _col().find_one(
            {"_id": site_id},
            {"stats.errors": 1, "_id": 0},
        )
        return site.get("stats", {}).get("errors", {}) if site else {}
    except PyMongoError:
        logger.error("get_error_report failed", exc_info=True)
        return {}


# ============================================================
# COOKIE STATUS
# ============================================================

async def update_cookie_status(site_id: str, status: str):
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
        logger.error("update_cookie_status failed", exc_info=True)


# ============================================================
# 🔥 BACKWARD-COMPATIBLE ALIASES (CRITICAL)
# ============================================================

# poller.py expects OLD names
get_enabled_sites = list_active_sites
get_site_by_id = get_site
update_site_last_check = update_last_check
update_site_on_success = update_on_success
increment_site_error = increment_error
update_site_ajax_meta = update_ajax_meta
update_site_cookie_status = update_cookie_status


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "create_site",
    "get_site",
    "list_sites",
    "list_active_sites",
    "update_site",
    "toggle_site",
    "delete_site",
    "update_last_check",
    "update_on_success",
    "update_ajax_meta",
    "increment_error",
    "get_error_report",
    "update_cookie_status",

    # aliases
    "get_enabled_sites",
    "get_site_by_id",
    "update_site_last_check",
    "update_site_on_success",
    "increment_site_error",
    "update_site_ajax_meta",
    "update_site_cookie_status",
]
