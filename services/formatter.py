#!/usr/bin/env python3
# ============================================================
# SMS FORMATTER SERVICE (FINAL – FULL FIX)
# ============================================================
# ✔ HTML safe
# ✔ Per-site custom template
# ✔ poller.py compatible
# ✔ Backward compatible aliases
# ✔ Zero KeyError guarantee
# ✔ Always returns valid string
# ✔ Production safe
# ============================================================

import logging
from datetime import datetime
from typing import Dict, Any

from utils.helpers import html_safe
from utils.country import get_country, get_country_from_number

logger = logging.getLogger("services.formatter")

# ============================================================
# DEFAULT SMS TEMPLATE
# ============================================================

DEFAULT_SMS_TEMPLATE = """📩 <b>LIVE OTP RECEIVED</b>

📞 <b>Number:</b> <code>{number}</code>
🔢 <b>OTP:</b> 🔥 <code>{otp}</code> 🔥
🏷 <b>Service:</b> {service}
🌍 <b>Country:</b> {country}
🕒 <b>Time:</b> {time}

💬 <b>SMS:</b>
{message}

⚡ <b>— AK KING 👑</b>
"""


# ============================================================
# INTERNAL COUNTRY RESOLVER (SAFE)
# ============================================================

def _resolve_country(number: str) -> str:
    """
    Safe country resolver with backward compatibility
    """
    try:
        if number:
            try:
                return get_country_from_number(number)
            except Exception:
                return get_country(number)
        return "🌍 International"
    except Exception:
        return "🌍 International"


# ============================================================
# CORE FORMATTER
# ============================================================

def format_sms(site: Dict[str, Any], data: Dict[str, Any]) -> str:
    """
    Render SMS message using site-specific template.

    HARD GUARANTEES:
    - No KeyError
    - HTML safe
    - Always returns string
    - poller-safe
    """
    try:
        template = (
            site.get("sms_format", {}).get("template")
            or DEFAULT_SMS_TEMPLATE
        )

        safe_data = {
            "otp": html_safe(str(data.get("otp", "N/A"))),
            "number": html_safe(str(data.get("number", "N/A"))),
            "message": html_safe(str(data.get("message", ""))),
            "time": html_safe(
                str(
                    data.get(
                        "time",
                        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    )
                )
            ),
            "service": html_safe(str(data.get("service", "Unknown"))),
            "country": html_safe(
                str(
                    data.get(
                        "country",
                        _resolve_country(data.get("number")),
                    )
                )
            ),
        }

        try:
            return template.format(**safe_data)

        except KeyError as ke:
            logger.error(
                f"Template variable missing | {ke} | site={site.get('_id')}"
            )
            note = (
                "⚠️ <b>Template Error</b>\n"
                f"Missing variable: <code>{html_safe(str(ke))}</code>\n\n"
            )
            return note + DEFAULT_SMS_TEMPLATE.format(**safe_data)

        except Exception:
            logger.error(
                f"Template render failed | site={site.get('_id')}",
                exc_info=True,
            )
            return DEFAULT_SMS_TEMPLATE.format(**safe_data)

    except Exception:
        logger.critical(
            f"Formatter fatal error | site={site.get('_id')}",
            exc_info=True,
        )
        return DEFAULT_SMS_TEMPLATE.format(
            otp="N/A",
            number="N/A",
            message="",
            time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            service="Unknown",
            country="🌍 International",
        )


# ============================================================
# 🔥 BACKWARD COMPATIBILITY (CRITICAL)
# ============================================================

def render_sms(site: Dict[str, Any], data: Dict[str, Any]) -> str:
    """
    REQUIRED by services.poller
    DO NOT REMOVE
    """
    return format_sms(site, data)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "format_sms",
    "render_sms",
]
