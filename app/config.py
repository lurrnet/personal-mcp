import json
import os
import re
from dataclasses import dataclass, field


def _csv(name: str, default: str = "") -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip()}


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ClientPolicy:
    name: str
    token_sha256: str
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    trilium_read_roots: tuple[str, ...] = ()
    trilium_write_roots: tuple[str, ...] = ()


def _load_clients(path: str) -> dict[str, ClientPolicy]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}

    clients_raw = raw.get("clients", {})
    if not isinstance(clients_raw, dict):
        raise RuntimeError("MCP clients file must contain an object named 'clients'")

    out: dict[str, ClientPolicy] = {}
    for name, item in clients_raw.items():
        if not isinstance(item, dict):
            raise RuntimeError(f"Client {name!r} must be an object")

        token_hash = str(item.get("token_sha256", "")).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
            raise RuntimeError(
                f"Client {name!r} token_sha256 must be a 64-character SHA-256 hex digest"
            )

        trilium = item.get("trilium", {}) or {}
        if not isinstance(trilium, dict):
            raise RuntimeError(f"Client {name!r} trilium policy must be an object")

        allowed_tools = frozenset(str(x) for x in item.get("allowed_tools", []) or [])
        read_roots = tuple(str(x) for x in trilium.get("read_roots", []) or [])
        write_roots = tuple(str(x) for x in trilium.get("write_roots", []) or [])

        out[name] = ClientPolicy(
            name=name,
            token_sha256=token_hash,
            allowed_tools=allowed_tools,
            trilium_read_roots=read_roots,
            trilium_write_roots=write_roots,
        )
    return out


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    public_host: str
    auth_mode: str
    api_token: str
    clients_file: str
    clients: dict[str, ClientPolicy]
    integrations: frozenset[str]
    audit_log: bool


_clients_file = os.getenv("MCP_CLIENTS_FILE", "/config/clients.json").strip()

settings = Settings(
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8765")),
    public_host=os.getenv("MCP_PUBLIC_HOST", "").strip(),
    auth_mode=os.getenv("MCP_AUTH_MODE", "multi_bearer").strip().lower(),
    api_token=os.getenv("MCP_API_TOKEN", ""),
    clients_file=_clients_file,
    clients=_load_clients(_clients_file),
    integrations=frozenset(_csv("MCP_INTEGRATIONS", "trilium")),
    audit_log=_bool("MCP_AUDIT_LOG", True),
)

if settings.auth_mode not in {"multi_bearer", "bearer", "proxy", "none"}:
    raise RuntimeError(
        "MCP_AUTH_MODE must be one of: multi_bearer, bearer, proxy, none"
    )
if settings.auth_mode == "multi_bearer" and not settings.clients:
    raise RuntimeError(
        f"MCP_AUTH_MODE=multi_bearer requires at least one client in {settings.clients_file}"
    )
if settings.auth_mode == "bearer" and not settings.api_token:
    raise RuntimeError("MCP_API_TOKEN is required when MCP_AUTH_MODE=bearer")
