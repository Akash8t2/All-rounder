#!/usr/bin/env python3
# ============================================
# CENTRALIZED LOGGER + DB LOG BRIDGE (FIXED)
# ============================================
# FIX APPLIED:
# - setup_logging() function ADDED
# - Compatible with main.py import
# - Python logging + Loguru bridge preserved
# - Heroku stdout safe
# ============================================

import sys
import logging
from typing import Optional, Dict, Any

from loguru import logger as _loguru_logger
from database.logs import add_log

# ============================================
# SETUP FUNCTION (🔥 MISSING FIX)
# ============================================

def setup_logging() -> None:
    """
    Initialize global logging configuration.
    Must be called ONCE at startup.
    """
    try:
        # Remove default loguru handlers
        _loguru_logger.remove()

        # Console handler (Heroku compatible)
        _loguru_logger.add(
            sys.stdout,
            level="INFO",
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level}</level> | "
                "<cyan>{name}</cyan> | "
                "<level>{message}</level>"
            ),
            enqueue=True,
            backtrace=True,
            diagnose=True,
        )

        # Bridge std logging → loguru
        class InterceptHandler(logging.Handler):
            def emit(self, record: logging.LogRecord):
                try:
                    level = _loguru_logger.level(record.levelname).name
                except Exception:
                    level = record.levelno

                frame, depth = logging.currentframe(), 2
                while frame and frame.f_code.co_filename == logging.__file__:
                    frame = frame.f_back
                    depth += 1

                _loguru_logger.opt(
                    depth=depth,
                    exception=record.exc_info,
                ).log(level, record.getMessage())

        logging.basicConfig(
            handlers=[InterceptHandler()],
            level=logging.INFO,
            force=True,
        )

        _loguru_logger.info("✅ Logging system initialized")

    except Exception as e:
        print("❌ Failed to initialize logging:", e)
        raise


# ============================================
# HIGH-LEVEL ASYNC LOG HELPERS
# ============================================

async def log_info(
    message: str,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
):
    _loguru_logger.info(message)
    await add_log(
        level="INFO",
        message=message,
        user_id=user_id,
        site_id=site_id,
        meta=meta,
    )


async def log_warning(
    message: str,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
):
    _loguru_logger.warning(message)
    await add_log(
        level="WARNING",
        message=message,
        user_id=user_id,
        site_id=site_id,
        meta=meta,
    )


async def log_error(
    message: str,
    user_id: Optional[int] = None,
    site_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
):
    _loguru_logger.error(message)
    await add_log(
        level="ERROR",
        message=message,
        user_id=user_id,
        site_id=site_id,
        meta=meta,
    )


async def log_admin(
    message: str,
    admin_id: int,
    meta: Optional[Dict[str, Any]] = None,
):
    _loguru_logger.info(f"[ADMIN] {message}")
    await add_log(
        level="ADMIN",
        message=message,
        user_id=admin_id,
        meta=meta,
    )


async def log_user(
    message: str,
    user_id: int,
    meta: Optional[Dict[str, Any]] = None,
):
    _loguru_logger.info(f"[USER] {message}")
    await add_log(
        level="USER",
        message=message,
        user_id=user_id,
        meta=meta,
    )


async def log_system(
    message: str,
    meta: Optional[Dict[str, Any]] = None,
):
    _loguru_logger.info(f"[SYSTEM] {message}")
    await add_log(
        level="SYSTEM",
        message=message,
        meta=meta,
    )

# ============================================
# FINAL VERIFICATION CHECKLIST
# ============================================
# - [x] setup_logging() implemented
# - [x] main.py import fixed
# - [x] Loguru + logging bridge intact
# - [x] MongoDB logging preserved
# - [x] Heroku stdout compatible
# - [x] No missing logic
# - [x] No placeholders
