#!/usr/bin/env python3
# ============================================================
# POLLER SERVICE (FINAL • ASYNC • HEROKU SAFE)
# ============================================================

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List

import requests
from requests import Session

from config.settings import CHECK_INTERVAL
from database.sites import (
    list_active_sites,
    update_last_check,
    update_on_success,
    increment_error,
    update_ajax_meta,
    update_cookie_status,
)
from database.logs import log_error, log_action
from services.telegram import send_message, send_admin_alert
from services.formatter import format_sms
from utils.otp import extract_and_validate
from utils.country import get_country_from_number

logger = logging.getLogger("services.poller")

# ============================================================
# IN-MEMORY STATE
# ============================================================

_SITE_SESSIONS: Dict[str, Session] = {}
_COOKIE_ALERT_CACHE: Dict[str, bool] = {}

# ============================================================
# SESSION MANAGEMENT
# ============================================================

def _build_session(site: Dict[str, Any]) -> Session:
    s = requests.Session()
    s.headers.update(site.get("headers", {}))
    s.cookies.update(site.get("cookies", {}))
    return s


def _get_session(site: Dict[str, Any]) -> Session:
    site_id = site["_id"]
    if site_id not in _SITE_SESSIONS:
        _SITE_SESSIONS[site_id] = _build_session(site)
    return _SITE_SESSIONS[site_id]


def _cleanup_sessions(active_ids: List[str]):
    for sid in list(_SITE_SESSIONS.keys()):
        if sid not in active_ids:
            _SITE_SESSIONS.pop(sid, None)
            _COOKIE_ALERT_CACHE.pop(sid, None)

# ============================================================
# HELPERS
# ============================================================

def _is_html_login(response: requests.Response) -> bool:
    try:
        ct = response.headers.get("Content-Type", "").lower()
        body = response.text.lower()
        return "text/html" in ct and ("login" in body or "<html" in body)
    except Exception:
        return True


def _safe_json(response: requests.Response):
    try:
        return response.json()
    except Exception:
        return None


async def _auto_detect_ajax(site_id: str, rows: List[list]):
    if not rows:
        return

    cols = len(rows[0])
    if cols == 7:
        ajax_type = "ints_client"
    elif cols == 9:
        ajax_type = "ints_agent"
    elif cols > 9:
        ajax_type = "extended"
    else:
        ajax_type = "unknown"

    await update_ajax_meta(site_id, ajax_type, cols)

# ============================================================
# SINGLE SITE POLL
# ============================================================

async def poll_single_site(site: Dict[str, Any]):
    site_id = site["_id"]

    try:
        await update_last_check(site_id)
        session = _get_session(site)

        response = session.get(site["ajax"], timeout=20)

        if response.status_code != 200:
            await increment_error(site_id, "http_error")
            return

        if _is_html_login(response):
            await increment_error(site_id, "html_login")
            await update_cookie_status(site_id, "expired")

            if not _COOKIE_ALERT_CACHE.get(site_id):
                await send_admin_alert(
                    site,
                    "🚨 <b>COOKIE EXPIRED</b>\nPlease update cookies."
                )
                _COOKIE_ALERT_CACHE[site_id] = True

            _SITE_SESSIONS.pop(site_id, None)
            return

        payload = _safe_json(response)
        if not payload:
            await increment_error(site_id, "json_decode")
            return

        rows = payload.get("aaData", [])
        if not rows:
            return

        if site.get("ajax_type") in (None, "unknown"):
            await _auto_detect_ajax(site_id, rows)

        latest = rows[0]
        row_uid = str(latest)

        if site.get("last_uid") == row_uid:
            return

        number = latest[2] if len(latest) > 2 else ""
        service = latest[3] if len(latest) > 3 else site.get("name", "Unknown")
        message = latest[5] if len(latest) > 5 else ""
        timestamp = latest[0]

        otp = extract_and_validate(message)
        if not otp:
            return

        text = format_sms(
            site,
            {
                "otp": otp,
                "number": number,
                "message": message,
                "time": timestamp,
                "service": service,
                "country": get_country_from_number(number),
            },
        )

        sent = await send_message(
            site["bot_token"],
            site.get("chat_ids", []),
            text,
            site,
        )

        if sent:
            await update_on_success(site_id, row_uid)
            await update_cookie_status(site_id, "valid")
            _COOKIE_ALERT_CACHE.pop(site_id, None)

            await log_action(
                "otp_sent",
                meta={"site_id": site_id, "otp": otp},
                site_id=site_id,
            )
        else:
            await increment_error(site_id, "telegram_send")

    except Exception as e:
        await increment_error(site_id, "poll_exception")
        await log_error("poll_single_site", str(e), site_id)

# ============================================================
# MAIN LOOP (FIXED)
# ============================================================

async def poller_loop():
    logger.info("Poller loop started")

    while True:
        try:
            sites = await list_active_sites()   # ✅ FIX
            active_ids = [s["_id"] for s in sites]

            _cleanup_sessions(active_ids)

            for site in sites:
                await poll_single_site(site)

            await asyncio.sleep(max(7, CHECK_INTERVAL))

        except asyncio.CancelledError:
            logger.warning("Poller loop cancelled")
            break

        except Exception as e:
            logger.critical("Poller fatal crash", exc_info=True)
            await log_error("poller_loop", str(e))
            await asyncio.sleep(15)
