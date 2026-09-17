import os
from dataclasses import dataclass


def _csv(name: str, default: str = "") -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip()}


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("MCP_HOST", "0.0.0.0")
    port: int = int(os.getenv("MCP_PORT", "8765"))
    public_host: str = os.getenv("MCP_PUBLIC_HOST", "").strip()
    auth_mode: str = os.getenv("MCP_AUTH_MODE", "bearer").strip().lower()
    api_token: str = os.getenv("MCP_API_TOKEN", "")
    integrations: set[str] = frozenset(_csv("MCP_INTEGRATIONS", "trilium"))
    audit_log: bool = _bool("MCP_AUDIT_LOG", True)


settings = Settings()

if settings.auth_mode not in {"bearer", "proxy", "none"}:
    raise RuntimeError("MCP_AUTH_MODE must be one of: bearer, proxy, none")
if settings.auth_mode == "bearer" and not settings.api_token:
    raise RuntimeError("MCP_API_TOKEN is required when MCP_AUTH_MODE=bearer")
