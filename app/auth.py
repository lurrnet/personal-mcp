import hashlib
import hmac
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

from config import ClientPolicy, settings


_current_client: ContextVar[str] = ContextVar("mcp_current_client", default="unknown")


def get_client_name() -> str:
    return _current_client.get()


def get_client_policy() -> ClientPolicy | None:
    name = get_client_name()
    return settings.clients.get(name)


def require_tool(tool_name: str) -> None:
    """Enforce tool-level ACL for multi-client bearer mode."""
    if settings.auth_mode != "multi_bearer":
        return
    policy = get_client_policy()
    if policy is None:
        raise PermissionError("No authenticated client policy is available")
    if "*" not in policy.allowed_tools and tool_name not in policy.allowed_tools:
        raise PermissionError(
            f"Client {policy.name!r} is not allowed to call tool {tool_name!r}"
        )


def trilium_roots(access: str) -> tuple[str, ...]:
    """Return the authenticated client's Trilium read/write roots."""
    if settings.auth_mode != "multi_bearer":
        return ("*",) if access == "read" else ()
    policy = get_client_policy()
    if policy is None:
        return ()
    if access == "read":
        return policy.trilium_read_roots
    if access == "write":
        return policy.trilium_write_roots
    raise ValueError("access must be 'read' or 'write'")


def _find_client_for_token(token: str) -> str | None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched: str | None = None
    # Compare against every configured digest to avoid an early-exit timing signal.
    for name, policy in settings.clients.items():
        if hmac.compare_digest(digest, policy.token_sha256):
            matched = name
    return matched


class MCPAuthMiddleware:
    """Protect /mcp and attach a client identity to each request.

    - multi_bearer: identify a client by SHA-256(token), then enforce its ACL.
    - bearer: legacy single shared bearer token.
    - proxy: trust an authenticated upstream proxy.
    - none: local development only.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        client_name = "unknown"

        if settings.auth_mode == "none":
            client_name = "anonymous"
        elif settings.auth_mode == "proxy":
            headers = {
                k.decode("latin1").lower(): v.decode("latin1")
                for k, v in scope.get("headers", [])
            }
            client_name = headers.get("cf-access-authenticated-user-email", "proxy")
        else:
            headers = {
                k.decode("latin1").lower(): v.decode("latin1")
                for k, v in scope.get("headers", [])
            }
            auth = headers.get("authorization", "")
            prefix = "Bearer "
            supplied = auth[len(prefix):] if auth.startswith(prefix) else ""

            if settings.auth_mode == "multi_bearer":
                client_name = _find_client_for_token(supplied) if supplied else None
                valid = client_name is not None
            else:
                valid = bool(supplied) and hmac.compare_digest(
                    supplied, settings.api_token
                )
                client_name = "legacy" if valid else None

            if not valid:
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

        token = _current_client.set(str(client_name))
        try:
            await self.app(scope, receive, send)
        finally:
            _current_client.reset(token)
