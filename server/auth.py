"""
Authentication utilities for enterprise JWT-based auth.

The enterprise gateway provides JWT tokens via the 'x-kiosk-gateway-jwt' header
on every request. Per gateway documentation, signature verification is performed
at the gateway (the only ingress path), so the application decodes the token
without signature verification and uses the claims directly. Token expiry is
still enforced.
"""
import os
import logging
from typing import Optional, Dict, Any

import jwt

logger = logging.getLogger(__name__)

# The HTTP header the enterprise gateway uses to pass the JWT
ENTERPRISE_JWT_HEADER = "x-kiosk-gateway-jwt"

# ---------------------------------------------------------------------------
# LOCAL DEV BYPASS
# ---------------------------------------------------------------------------
# Set DEV_AUTH_BYPASS=true in your .env to skip enterprise JWT validation
# and auto-authenticate as a local dev admin user.
#
# >>> THIS MUST BE UNSET (or "false") IN PRODUCTION / ENTERPRISE ENV <<<
#
# When enabled, all requests are treated as coming from the dev user below.
# Customize DEV_AUTH_USERNAME / DEV_AUTH_ROLE if you need a different identity.
# ---------------------------------------------------------------------------
DEV_AUTH_BYPASS = os.getenv("DEV_AUTH_BYPASS", "false").lower() == "true"
DEV_AUTH_USERNAME = os.getenv("DEV_AUTH_USERNAME", "dev-admin")
DEV_AUTH_ROLE = os.getenv("DEV_AUTH_ROLE", "admin")  # admin | analyst | viewer

if DEV_AUTH_BYPASS:
    logger.warning(
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  DEV_AUTH_BYPASS is ON  –  all requests auto-authenticate   ║\n"
        "║  as '%s' (%s).  DO NOT use in production.        ║\n"
        "╚══════════════════════════════════════════════════════════════╝",
        DEV_AUTH_USERNAME, DEV_AUTH_ROLE,
    )


def verify_enterprise_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode an enterprise gateway JWT token.

    Signature verification is intentionally skipped: the gateway is the only
    ingress path to this service, so any JWT in the x-kiosk-gateway-jwt header
    has already been validated upstream. Token expiry is still enforced.

    Args:
        token: JWT token string from x-kiosk-gateway-jwt header

    Returns:
        Decoded payload dict if parseable and unexpired, None otherwise.
        Expected claims: sub (user ID), preferred_username or email, name, groups/roles
    """
    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": True},
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Enterprise JWT token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid enterprise JWT token: {e}")
        return None


def extract_user_info(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract normalized user info from enterprise JWT claims.

    Maps common enterprise JWT claim names to our internal user fields.
    Adjust the claim keys below to match your enterprise gateway's JWT format.

    Args:
        payload: Decoded JWT payload

    Returns:
        Dict with keys: enterprise_id, username, display_name
    """
    return {
        "enterprise_id": payload.get("sub", ""),
        "username": (
            payload.get("preferred_username")
            or payload.get("email")
            or payload.get("sub", "unknown")
        ),
        "display_name": (
            payload.get("name")
            or payload.get("display_name")
            or payload.get("preferred_username")
            or ""
        ),
    }


def get_dev_user_info() -> Dict[str, Any]:
    """
    Return synthetic user info for local dev bypass mode.
    Only called when DEV_AUTH_BYPASS=true.
    """
    return {
        "enterprise_id": "dev-local",
        "username": DEV_AUTH_USERNAME,
        "display_name": DEV_AUTH_USERNAME,
    }
