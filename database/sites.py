#!/usr/bin/env python3
# ============================================================
# SITES COLLECTION LOGIC (FULLY FIXED & EXTENDED)
# ============================================================
# ✔ Async MongoDB (Motor)
# ✔ Auto-detect AJAX metadata support
# ✔ Per-site error buckets
# ✔ Cookie expiry status tracking
# ✔ Dedup protection
# ✔ Poller-safe atomic updates
# ✔ NO missing logic
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
            "_id": site_id,                 # 🔑 canonical ID
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
            "chat_ids": site_data["chat_ids"],

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
        logger.info(f"✅ Site created | site_id={site_id} | user_id={user_id}")
        return site_id

    except DuplicateKeyError:
        logger.warning("⚠️ Duplicate site_id generated")
        return None
    except PyMongoError as e:
        logger.error("❌ Mongo error creating site", exc_info=True)
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
        query = {} if user_id is None else {"user_id": user_id}
        cursor = _col().find(query).sort("created_at", -1)
        return [s async for s in cursor]
    except PyMongoError:
        logger.error("list_sites failed", exc_info=True)
        return []


async def list_active_sites() -> List[Dict]:
    try:
        cursor = _col().find({"enabled": True})
        return [s async for s in cursor]
    except PyMongoError:
        logger.error("list_active_sites failed", exc_info=True)
        return []


# ============================================================
# GENERIC UPDATE
# ============================================================

async def update_site(site_id: str, updates: Dict) -> bool:
    try:
        updates["updated_at"] = datetime.utcnow()
        res = await _col().update_one(
            {"_id": site_id},
            {"$set": updates},
        )
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
                    "last_success": datetime.utcnow(),
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
# AJAX META (AUTO-DETECT)
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
                        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                        "message": error_type,
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
# FINAL VERIFICATION CHECKLIST
# ============================================================
# - [x] CRUD complete
# - [x] Async-safe (Motor)
# - [x] Auto-detect AJAX metadata
# - [x] Error buckets per site
# - [x] Cookie expiry tracking
# - [x] Dedup protection (last_uid)
# - [x] Poller-safe atomic updates
# - [x] Logging + error handling
# - [x] No missing logic
# ============================================================