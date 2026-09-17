import json
import logging
from datetime import datetime, timezone
from typing import Any

from config import settings

logger = logging.getLogger("personal_mcp.audit")


def record(tool: str, action: str, ok: bool, **fields: Any) -> None:
    """Write a minimal JSON audit event to stdout.

    Deliberately exclude note contents, API tokens, Authorization headers,
    and other secret-bearing values from callers.
    """
    if not settings.audit_log:
        return
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "action": action,
        "ok": ok,
        **fields,
    }
    logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
