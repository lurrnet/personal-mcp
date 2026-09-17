import os
from collections import deque
from typing import Any

import httpx


class TriliumError(RuntimeError):
    pass


class WriteScopeError(PermissionError):
    pass


class TriliumClient:
    def __init__(self) -> None:
        self.base_url = os.environ["TRILIUM_ETAPI_URL"].rstrip("/")
        self.token = os.environ["TRILIUM_ETAPI_TOKEN"]
        self.write_root = os.getenv("TRILIUM_WRITE_ROOT_NOTE_ID", "").strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self.token,
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = self._headers()
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                **kwargs,
            )
        if response.is_error:
            raise TriliumError(
                f"Trilium ETAPI {method} {path} failed: "
                f"HTTP {response.status_code}: {response.text[:500]}"
            )
        return response

    async def app_info(self) -> dict[str, Any]:
        return (await self._request("GET", "/app-info")).json()

    async def search_notes(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        params = {"search": query, "limit": max(1, min(limit, 100))}
        data = (await self._request("GET", "/notes", params=params)).json()
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data["results"]
        if isinstance(data, list):
            return data
        return [data]

    async def get_note_metadata(self, note_id: str) -> dict[str, Any]:
        return (await self._request("GET", f"/notes/{note_id}")).json()

    async def get_note(self, note_id: str) -> dict[str, Any]:
        meta = await self.get_note_metadata(note_id)
        content_resp = await self._request("GET", f"/notes/{note_id}/content")
        return {"note": meta, "content": content_resp.text}

    async def is_descendant_or_self(
        self,
        note_id: str,
        root_note_id: str,
        max_nodes: int = 5000,
    ) -> bool:
        if note_id == root_note_id:
            return True

        queue: deque[str] = deque([note_id])
        visited: set[str] = set()

        while queue and len(visited) < max_nodes:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            meta = await self.get_note_metadata(current)
            for parent_id in meta.get("parentNoteIds", []) or []:
                if parent_id == root_note_id:
                    return True
                if parent_id not in visited:
                    queue.append(parent_id)
        return False

    async def assert_write_allowed(self, note_id: str) -> None:
        if not self.write_root:
            raise WriteScopeError(
                "Trilium writes are disabled because TRILIUM_WRITE_ROOT_NOTE_ID "
                "is not configured."
            )
        if not await self.is_descendant_or_self(note_id, self.write_root):
            raise WriteScopeError(
                f"Write blocked: note {note_id!r} is outside the configured Trilium write root."
            )

    async def create_note(
        self,
        parent_note_id: str,
        title: str,
        content: str,
        note_type: str = "text",
    ) -> dict[str, Any]:
        await self.assert_write_allowed(parent_note_id)
        payload = {
            "parentNoteId": parent_note_id,
            "title": title,
            "type": note_type,
            "content": content,
        }
        return (await self._request("POST", "/create-note", json=payload)).json()

    async def update_note(
        self,
        note_id: str,
        title: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        await self.assert_write_allowed(note_id)
        if title is None and content is None:
            raise ValueError("At least one of title or content must be provided")

        out: dict[str, Any] = {"noteId": note_id}
        if title is not None:
            current = await self.get_note_metadata(note_id)
            payload = {
                "noteId": current["noteId"],
                "title": title,
                "type": current["type"],
                "mime": current.get("mime", ""),
            }
            out["note"] = (
                await self._request("PATCH", f"/notes/{note_id}", json=payload)
            ).json()

        if content is not None:
            response = await self._request(
                "PUT",
                f"/notes/{note_id}/content",
                content=content.encode("utf-8"),
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
            out["contentUpdated"] = response.status_code in (200, 204)
        return out
