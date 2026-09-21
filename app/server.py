import logging
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from audit import record
from auth import (
    MCPAuthMiddleware,
    get_client_name,
    require_tool,
    trilium_roots,
)
from config import settings

logging.basicConfig(level=logging.INFO, format="%(message)s")


if settings.public_host:
    security = TransportSecuritySettings(
        allowed_hosts=[
            settings.public_host,
            f"{settings.public_host}:*",
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
        ],
        allowed_origins=[
            f"https://{settings.public_host}",
            f"https://{settings.public_host}:*",
            "http://localhost:*",
            "http://127.0.0.1:*",
        ],
    )
else:
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "Personal MCP Gateway",
    host=settings.host,
    port=settings.port,
    transport_security=security,
)


@mcp.tool(annotations={"readOnlyHint": True})
async def gateway_status() -> dict[str, Any]:
    """Return gateway status for the authenticated client without exposing secrets."""
    require_tool("gateway_status")
    policy = settings.clients.get(get_client_name())
    return {
        "service": "personal-mcp",
        "version": "0.4.0",
        "client": get_client_name(),
        "integrations": sorted(settings.integrations),
        "authMode": settings.auth_mode,
        "auditLogging": settings.audit_log,
        "allowedTools": sorted(policy.allowed_tools) if policy else ["*"],
    }


if "trilium" in settings.integrations:
    from integrations.trilium import TriliumClient

    trilium = TriliumClient()

    @mcp.tool(annotations={"readOnlyHint": True})
    async def trilium_health_check() -> dict[str, Any]:
        """Check connectivity to Trilium ETAPI and return basic app information."""
        require_tool("trilium_health_check")
        try:
            result = await trilium.app_info()
            record("trilium_health_check", "read", True)
            return result
        except Exception:
            record("trilium_health_check", "read", False)
            raise

    @mcp.tool(annotations={"readOnlyHint": True})
    async def trilium_search_notes(query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Trilium notes and return only results inside the client's read roots."""
        require_tool("trilium_search_notes")
        try:
            raw = await trilium.search_notes(query, limit)
            result = await trilium.filter_search_results(raw, trilium_roots("read"))
            record(
                "trilium_search_notes",
                "read",
                True,
                query_length=len(query),
                raw_result_count=len(raw),
                result_count=len(result),
            )
            return result
        except Exception:
            record("trilium_search_notes", "read", False, query_length=len(query))
            raise

    @mcp.tool(annotations={"readOnlyHint": True})
    async def trilium_get_note(note_id: str) -> dict[str, Any]:
        """Read a Trilium note by note ID if it is inside the client's read roots."""
        require_tool("trilium_get_note")
        try:
            await trilium.assert_read_allowed(note_id, trilium_roots("read"))
            result = await trilium.get_note(note_id)
            record("trilium_get_note", "read", True, note_id=note_id)
            return result
        except Exception:
            record("trilium_get_note", "read", False, note_id=note_id)
            raise

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    async def trilium_create_note(
        parent_note_id: str,
        title: str,
        content: str,
        note_type: str = "text",
    ) -> dict[str, Any]:
        """Create a Trilium child note inside the client's configured write roots."""
        require_tool("trilium_create_note")
        try:
            await trilium.assert_client_write_allowed(
                parent_note_id, trilium_roots("write")
            )
            result = await trilium.create_note(
                parent_note_id, title, content, note_type
            )
            record(
                "trilium_create_note",
                "write",
                True,
                parent_note_id=parent_note_id,
                title_length=len(title),
            )
            return result
        except Exception:
            record(
                "trilium_create_note",
                "write",
                False,
                parent_note_id=parent_note_id,
                title_length=len(title),
            )
            raise

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    async def trilium_update_note(
        note_id: str,
        title: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Update a Trilium note inside the client's configured write roots."""
        require_tool("trilium_update_note")
        try:
            await trilium.assert_client_write_allowed(
                note_id, trilium_roots("write")
            )
            result = await trilium.update_note(note_id, title, content)
            record(
                "trilium_update_note",
                "write",
                True,
                note_id=note_id,
                changes={"title": title is not None, "content": content is not None},
            )
            return result
        except Exception:
            record(
                "trilium_update_note",
                "write",
                False,
                note_id=note_id,
                changes={"title": title is not None, "content": content is not None},
            )
            raise


mcp_app = mcp.streamable_http_app()
app = MCPAuthMiddleware(mcp_app)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=True)
