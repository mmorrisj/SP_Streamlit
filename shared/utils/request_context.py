"""Per-request context for propagating the enterprise gateway JWT.

In production the enterprise gateway injects a JWT on every inbound request via
the ``x-kiosk-gateway-jwt`` header. The LiteLLM endpoint that serves LLM calls
lives behind the same enterprise infrastructure and authenticates by that JWT —
it does **not** want a static API key. To call LiteLLM we therefore need the
caller's JWT available at the outbound boundary, which may be several hops away
from the request that carried it (endpoint -> rag_service -> proxy -> LiteLLM).

A :class:`contextvars.ContextVar` is the right tool: a pure-ASGI middleware
stores the inbound token at the start of each request, and every in-process LLM
call site reads it back without having to thread the token through every
function signature. Starlette copies the context when dispatching sync
endpoints to its threadpool, so the value is visible there too.

Outbound HTTP hops (e.g. rag_service calling the proxy) must re-attach the
header explicitly via :func:`get_gateway_jwt` so the receiving service's own
middleware can re-populate its context.
"""
from __future__ import annotations

import contextvars
from typing import Optional

# The HTTP header the enterprise gateway uses to pass the JWT. Mirrors
# server.auth.ENTERPRISE_JWT_HEADER but lives here so shared/ and services/
# code can reference it without importing the server package.
ENTERPRISE_JWT_HEADER = "x-kiosk-gateway-jwt"

_gateway_jwt: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "gateway_jwt", default=None
)


def set_gateway_jwt(token: Optional[str]) -> None:
    """Store the current request's gateway JWT (or clear it with None/empty)."""
    _gateway_jwt.set(token or None)


def get_gateway_jwt() -> Optional[str]:
    """Return the gateway JWT for the current request context, if any."""
    return _gateway_jwt.get()


class GatewayJWTMiddleware:
    """Pure-ASGI middleware that captures the gateway JWT into the context.

    Implemented as raw ASGI (not Starlette's BaseHTTPMiddleware) so the
    contextvar set here propagates to the route handler — including sync
    handlers that Starlette dispatches on its threadpool, which copies the
    context at dispatch time.
    """

    def __init__(self, app):
        self.app = app
        self._header = ENTERPRISE_JWT_HEADER.encode("latin-1")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            token = None
            for k, v in scope.get("headers", []):
                if k == self._header:
                    token = v.decode("latin-1")
                    break
            set_gateway_jwt(token)
        await self.app(scope, receive, send)
