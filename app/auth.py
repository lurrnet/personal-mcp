import hmac

from starlette.types import ASGIApp, Receive, Scope, Send

from config import settings


class MCPAuthMiddleware:
    """Protect /mcp with bearer auth, an authenticated proxy, or no auth.

    - bearer: require Authorization: Bearer <MCP_API_TOKEN>
    - proxy: trust the upstream identity layer. Use only behind a locked-down proxy.
    - none: local development only.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        if settings.auth_mode in {"proxy", "none"}:
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        prefix = "Bearer "
        supplied = auth[len(prefix):] if auth.startswith(prefix) else ""

        if not supplied or not hmac.compare_digest(supplied, settings.api_token):
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"cache-control", b"no-store"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error":"unauthorized"}',
            })
            return

        await self.app(scope, receive, send)
