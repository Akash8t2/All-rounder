#!/usr/bin/env python3
# ============================================================
# GLOBAL SETTINGS COLLECTION (FINAL – FULL FIX)
# ============================================================
# ✔ Async MongoDB (Motor)
# ✔ DB-based global config
# ✔ telegram.py compatible
# ✔ Backward-compatible helpers
# ✔ Strict error handling
# ✔ Logging everywhere
# ✔ Restart safe (Heroku/VPS)
# ✔ No missing logic
# ============================================================

import logging
from datetime import datetime
from typing import Optional, Any, Dict

from pymongo.errors import DuplicateKeyError, PyMongoError
from database.mongo import get_db

logger = logging.getLogger("database.settings")


# ============================================================
# COLLECTION GETTER
# ============================================================

def _col():
    """
    MongoDB settings collection
    """
    return get_db().settings


# ============================================================
# SET / UPDATE SETTING
# ============================================================

async def set_setting(
    key: str,
    value: Any,
    updated_by: Optional[int] = None,
) -> bool:
    """
    Create or update a global setting.
    """
    try:
        now = datetime.utcnow()

        await _col().update_one(
            {"key": key},
            {
                "$set": {
                    "value": value,
                    "updated_at": now,
                    "updated_by": updated_by,
                },
                "$setOnInsert": {
                    "key": key,
                    "created_at": now,
                },
            },
            upsert=True,
        )

        logger.info(f"⚙️ Setting saved | key={key}")
        return True

    except DuplicateKeyError:
        logger.warning(f"⚠️ Duplicate setting key | key={key}")
        return False

    except PyMongoError:
        logger.error("❌ set_setting Mongo error", exc_info=True)
        return False

    except Exception:
        logger.error("❌ set_setting unexpected error", exc_info=True)
        return False


# ============================================================
# GET SETTING (BASE)
# ============================================================

async def get_setting(key: str, default: Any = None) -> Any:
    """
    Get setting value by key.
    """
    try:
        doc = await _col().find_one({"key": key})
        if not doc:
            return default
        return doc.get("value", default)

    except PyMongoError:
        logger.error("❌ get_setting Mongo error", exc_info=True)
        return default

    except Exception:
        logger.error("❌ get_setting unexpected error", exc_info=True)
        return default


# ============================================================
# 🔥 BACKWARD-COMPATIBLE HELPER (CRITICAL)
# ============================================================

async def get_global_setting(key: str, default: Any = None) -> Any:
    """
    REQUIRED by services.telegram
    DO NOT REMOVE
    """
    return await get_setting(key, default)


# ============================================================
# DELETE SETTING
# ============================================================

async def delete_setting(key: str) -> bool:
    """
    Delete a setting.
    """
    try:
        result = await _col().delete_one({"key": key})
        if result.deleted_count:
            logger.info(f"🗑 Setting deleted | key={key}")
            return True

        logger.warning(f"⚠️ Setting not found | key={key}")
        return False

    except PyMongoError:
        logger.error("❌ delete_setting Mongo error", exc_info=True)
        return False

    except Exception:
        logger.error("❌ delete_setting unexpected error", exc_info=True)
        return False


# ============================================================
# LIST SETTINGS (ADMIN / OWNER)
# ============================================================

async def list_settings(limit: int = 100) -> Dict[str, Any]:
    """
    List settings as key-value dict.
    """
    try:
        cursor = _col().find({}).limit(int(limit))
        data: Dict[str, Any] = {}

        async for s in cursor:
            data[s["key"]] = s.get("value")

        logger.info(f"📋 Settings listed | count={len(data)}")
        return data

    except PyMongoError:
        logger.error("❌ list_settings Mongo error", exc_info=True)
        return {}

    except Exception:
        logger.error("❌ list_settings unexpected error", exc_info=True)
        return {}


# ============================================================
# EXPORTS (IMPORT SAFETY)
# ============================================================

__all__ = [
    "set_setting",
    "get_setting",
    "get_global_setting",
    "delete_setting",
    "list_settings",
]
