import logging
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from audit import record
from auth import MCPAuthMiddleware
from config import settings

logging.basicConfig(level=logging.INFO, format="%(message)s")

mcp = FastMCP("Personal MCP Gateway")


@mcp.tool(annotations={"readOnlyHint": True})
async def gateway_status() -> dict[str, Any]:
    """Return enabled integrations and gateway capabilities without exposing secrets."""
    return {
        "service": "personal-mcp",
        "version": "0.3.0",
        "integrations": sorted(settings.integrations),
        "authMode": settings.auth_mode,
        "auditLogging": settings.audit_log,
    }


if "trilium" in settings.integrations:
    from integrations.trilium import TriliumClient

    trilium = TriliumClient()

    @mcp.tool(annotations={"readOnlyHint": True})
    async def trilium_health_check() -> dict[str, Any]:
        """Check connectivity to Trilium ETAPI and return basic app information."""
        try:
            result = await trilium.app_info()
            record("trilium_health_check", "read", True)
            return result
        except Exception:
            record("trilium_health_check", "read", False)
            raise

    @mcp.tool(annotations={"readOnlyHint": True})
    async def trilium_search_notes(query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Trilium notes using a Trilium search expression or free-text query."""
        try:
            result = await trilium.search_notes(query, limit)
            record("trilium_search_notes", "read", True, query_length=len(query), result_count=len(result))
            return result
        except Exception:
            record("trilium_search_notes", "read", False, query_length=len(query))
            raise

    @mcp.tool(annotations={"readOnlyHint": True})
    async def trilium_get_note(note_id: str) -> dict[str, Any]:
        """Read a Trilium note's metadata and content by note ID."""
        try:
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
        """Create a Trilium child note inside the configured write-root subtree."""
        try:
            result = await trilium.create_note(parent_note_id, title, content, note_type)
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
        """Update a Trilium note inside the configured write-root subtree."""
        try:
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


if settings.public_host:
    security = TransportSecuritySettings(
        allowed_hosts=[
            settings.public_host,
            f"{settings.public_host}:*",
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
        ]
    )
else:
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp_app = mcp.streamable_http_app(transport_security=security)
app = MCPAuthMiddleware(mcp_app)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=True)
