# Personal MCP Gateway v0.4

A security-first MCP gateway for exposing a small, controlled set of tools from personal services to ChatGPT or other MCP clients.

Trilium is the first integration. The project is intentionally structured so future integrations such as Nextcloud, Immich, Plex, OCI, Home Assistant, or custom APIs can be added without giving the MCP client their native API tokens.

## Architecture

```text
ChatGPT / OpenClaw / MCP client
            |
            | HTTPS + MCP authentication
            v
      Personal MCP Gateway
      |        |        |
      |        |        +--> future: OCI / Plex / ...
      |        +-----------> future: Nextcloud / Immich
      +--------------------> Trilium ETAPI
```

Each backend credential remains server-side. The MCP client sees only the tools you choose to expose.

## v0.3 security model

- Docker publishes only to `127.0.0.1:8765`.
- Public ingress is expected to be a secure tunnel/reverse proxy.
- `/mcp` uses Bearer authentication by default.
- Backend credentials stay in `.env` on the server.
- Trilium writes are restricted to one configured subtree.
- There is no delete tool.
- Read/write intent is exposed with MCP tool annotations.
- Tool calls are audit-logged as JSON without note contents or secrets.
- Container runs as an unprivileged user, drops Linux capabilities, and has a read-only filesystem.

Do not treat the MCP hostname as secret.

## Current tools

| Tool | Class | Scope |
|---|---|---|
| `gateway_status` | READ | Gateway metadata only |
| `trilium_health_check` | READ | Trilium app info |
| `trilium_search_notes` | READ | Notes visible to ETAPI token |
| `trilium_get_note` | READ | Notes visible to ETAPI token |
| `trilium_create_note` | WRITE | Configured Trilium write subtree |
| `trilium_update_note` | WRITE | Configured Trilium write subtree |

There is intentionally no delete tool.

## 1. Create a Trilium AI Workspace

Create a note such as:

```text
AI Workspace
├── Inbox
├── Travel
├── Research
└── Drafts
```

Copy the `noteId` for `AI Workspace`. Trilium writes will be rejected unless the target is this note or a descendant.

## 2. Configure

```bash
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
nano .env
```

Example:

```env
MCP_PUBLIC_HOST=mcp.example.com
MCP_AUTH_MODE=bearer
MCP_API_TOKEN=<64-hex-random-secret>
MCP_INTEGRATIONS=trilium
MCP_AUDIT_LOG=true

TRILIUM_ETAPI_URL=https://notes.example.com/etapi
TRILIUM_ETAPI_TOKEN=<dedicated-etapi-token>
TRILIUM_WRITE_ROOT_NOTE_ID=<AI-Workspace-noteId>
```

Never commit `.env`.

## 3. Start

```bash
docker compose build
docker compose up -d
docker compose logs -f personal-mcp
```

Verify loopback-only publishing:

```bash
ss -lntp | grep 8765
```

Expected:

```text
127.0.0.1:8765
```

Do not open port 8765 in OCI Security Lists / NSGs.

## 4. Cloudflare Tunnel

Point a public hostname to the local service:

```text
mcp.example.com -> http://localhost:8765
```

The MCP URL is then:

```text
https://mcp.example.com/mcp
```

With `MCP_AUTH_MODE=bearer`, requests without the gateway token should receive HTTP 401.

## 5. Test authentication

Without token:

```bash
curl -i https://mcp.example.com/mcp
```

Expected: `401 Unauthorized`.

With token:

```bash
curl -i \
  -H "Authorization: Bearer $MCP_API_TOKEN" \
  https://mcp.example.com/mcp
```

This should get past the gateway auth layer. A bare GET is not a complete MCP protocol exchange, so the final response need not be a normal web page.

## 6. Connect ChatGPT

In ChatGPT's custom MCP app dialog:

- Name: `Personal MCP`
- Connection: `Server URL`
- URL: `https://mcp.example.com/mcp`
- Authentication: `Access token / API key`
- Token: the value of `MCP_API_TOKEN`

Do **not** enter `TRILIUM_ETAPI_TOKEN` into ChatGPT.

After tool scanning succeeds, test in this order:

1. `gateway_status`
2. `trilium_health_check`
3. Search for a harmless note
4. Read the note
5. Create a test note under `AI Workspace`
6. Update that test note
7. Attempt a write outside `AI Workspace` and confirm it is rejected

## 7. Audit log

The server writes compact JSON events to stdout, for example:

```json
{"ts":"...","tool":"trilium_search_notes","action":"read","ok":true,"query_length":8,"result_count":2}
```

It intentionally does not log note content, ETAPI tokens, MCP tokens, or Authorization headers.

View logs with:

```bash
docker compose logs -f personal-mcp
```

## 8. Adding another integration later

Use one module per backend under:

```text
app/integrations/
```

Recommended pattern:

```text
app/integrations/
├── trilium/
│   ├── __init__.py
│   └── client.py
├── nextcloud/
│   └── client.py
├── immich/
│   └── client.py
└── oci/
    └── client.py
```

Keep these rules:

1. Each backend token is read only from server-side environment variables or a secret manager.
2. Expose narrow MCP tools rather than raw passthrough HTTP endpoints.
3. Prefix tool names by integration, e.g. `nextcloud_read_file`.
4. Separate read tools from write tools using MCP annotations.
5. Put destructive operations behind a separate, stricter policy or omit them entirely.
6. Never log secrets or full private payloads in audit logs.

To enable another integration, add its module and include its name in `MCP_INTEGRATIONS`.

## 9. Recommended future evolution

For a larger gateway, move from a single shared bearer token to per-client OAuth or an authenticated private tunnel. Also consider:

- per-client permissions
- rate limits
- immutable audit storage
- explicit approval for dangerous actions
- backend-specific read scopes
- secret manager instead of `.env`
- a policy file mapping clients to tools

## Project layout

```text
personal-mcp/
├── README.md
├── compose.yml
├── .env.example
├── .gitignore
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── server.py
    ├── config.py
    ├── auth.py
    ├── audit.py
    └── integrations/
        ├── __init__.py
        └── trilium/
            ├── __init__.py
            └── client.py
```


## v0.4 multi-client authentication and ACLs

v0.4 adds one static bearer token per client plus per-client ACLs. Do not reuse the same token across ChatGPT, OpenClaw, automations, or other services.

### Create client tokens

Generate one random token per client:

```bash
openssl rand -hex 32
```

For each token, calculate its SHA-256 digest:

```bash
printf '%s' 'PASTE_RAW_TOKEN_HERE' | sha256sum
```

Only the digest goes into `config/clients.json`. The raw token is configured only in the client that uses it.

Create the live ACL file:

```bash
mkdir -p config
cp config/clients.example.json config/clients.json
chmod 600 config/clients.json
nano config/clients.json
```

`config/clients.json` is gitignored.

Example policy semantics:

- `allowed_tools`: exact MCP tools the client may invoke. `"*"` means all registered tools.
- `trilium.read_roots`: Trilium note roots the client may read. `"*"` means all notes visible to the ETAPI token.
- `trilium.write_roots`: Trilium note roots the client may create/update within. An empty list disables writes.
- `TRILIUM_WRITE_ROOT_NOTE_ID`: optional global write ceiling that applies in addition to every per-client write ACL.

Recommended example:

```text
ChatGPT
  read  -> all Trilium
  write -> AI Workspace

OpenClaw
  read  -> Projects subtree
  write -> disabled
```

Set:

```env
MCP_AUTH_MODE=multi_bearer
MCP_CLIENTS_FILE=/config/clients.json
```

Then rebuild and restart:

```bash
git pull
docker compose down
docker compose build --no-cache
docker compose up -d
docker compose logs --tail=100 personal-mcp
```

When ChatGPT connects, use the raw token generated specifically for the `chatgpt` client. OpenClaw must use its own raw token.

Audit events now include the authenticated client identity:

```json
{"client":"chatgpt","tool":"trilium_search_notes","action":"read","ok":true}
```

If a client calls a tool not listed in its ACL, or attempts to access a Trilium note outside its allowed roots, the request is rejected.
