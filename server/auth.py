"""
Authentication utilities for enterprise JWT-based auth.

The enterprise gateway provides JWT tokens via the 'x-kiosk-gateway-jwt' header
on every request. This module validates those tokens and extracts user identity.

Configuration:
    ENTERPRISE_JWT_SECRET: Secret or public key for validating enterprise JWTs.
                           Set via ENTERPRISE_JWT_SECRET env var.
    ENTERPRISE_JWT_ALGORITHM: Algorithm used by the enterprise gateway (default: HS256).
                              Set via ENTERPRISE_JWT_ALGORITHM env var.
                              For RS256/ES256, set ENTERPRISE_JWT_PUBLIC_KEY to a PEM file path.
"""
import os
import logging
from typing import Optional, Dict, Any

import jwt

logger = logging.getLogger(__name__)

# Enterprise JWT Configuration
# For symmetric algorithms (HS256), this is the shared secret.
# For asymmetric algorithms (RS256/ES256), use ENTERPRISE_JWT_PUBLIC_KEY instead.
ENTERPRISE_JWT_SECRET = os.getenv("ENTERPRISE_JWT_SECRET", "")
ENTERPRISE_JWT_ALGORITHM = os.getenv("ENTERPRISE_JWT_ALGORITHM", "HS256")
ENTERPRISE_JWT_PUBLIC_KEY_PATH = os.getenv("ENTERPRISE_JWT_PUBLIC_KEY", "")

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


def _get_verification_key() -> str:
    """
    Get the key used to verify enterprise JWTs.

    For asymmetric algorithms (RS256, ES256, etc.), reads from PEM file.
    For symmetric algorithms (HS256), uses the shared secret.
    """
    if ENTERPRISE_JWT_PUBLIC_KEY_PATH and os.path.isfile(ENTERPRISE_JWT_PUBLIC_KEY_PATH):
        with open(ENTERPRISE_JWT_PUBLIC_KEY_PATH, "r") as f:
            return f.read()
    return ENTERPRISE_JWT_SECRET


def verify_enterprise_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode an enterprise gateway JWT token.

    Args:
        token: JWT token string from x-kiosk-gateway-jwt header

    Returns:
        Decoded payload dict if valid, None if invalid/expired.
        Expected claims: sub (user ID), preferred_username or email, name, groups/roles
    """
    key = _get_verification_key()
    if not key:
        logger.error("No enterprise JWT secret or public key configured. "
                      "Set ENTERPRISE_JWT_SECRET or ENTERPRISE_JWT_PUBLIC_KEY env var.")
        return None

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[ENTERPRISE_JWT_ALGORITHM],
            options={"verify_exp": True}
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
