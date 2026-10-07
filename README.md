# Personal MCP Gateway v0.4

A security-first MCP gateway for exposing a small, controlled set of personal-service tools to ChatGPT, OpenClaw, automations, and other MCP clients.

Trilium is the first integration. The gateway is designed so backend credentials stay on the server while each MCP client gets its own identity, token, tool permissions, and data-access scope.

## What v0.4 adds

v0.4 introduces **multi-client static bearer tokens + per-client ACLs**.

Instead of every service sharing one MCP token, each client gets a separate token:

```text
ChatGPT   -> token A
OpenClaw  -> token B
Script    -> token C
               |
               v
        Personal MCP Gateway
               |
               v
           Trilium ETAPI
```

Each token maps to an ACL that controls:

- which MCP tools the client may call;
- which Trilium subtrees the client may read;
- which Trilium subtrees the client may write;
- the client name recorded in the audit log.

A leaked or revoked token therefore affects only that client.

## Architecture

```text
ChatGPT / OpenClaw / automation / MCP client
                    |
                    | HTTPS
                    | Authorization: Bearer <client-specific-token>
                    v
             Personal MCP Gateway
                    |
                    | per-client ACL
                    |
             +------+------+
             |             |
             v             v
        Trilium ETAPI   future integrations
                        Nextcloud / Immich /
                        Plex / OCI / ...
```

Backend credentials such as `TRILIUM_ETAPI_TOKEN` remain on the MCP server and are never given to ChatGPT or other MCP clients.

## Security model

v0.4 uses several layers of protection:

- Docker publishes MCP only on `127.0.0.1:8765`.
- Public access is expected through a secure tunnel or reverse proxy such as Cloudflare Tunnel.
- `/mcp` uses bearer authentication.
- Recommended auth mode is `multi_bearer`.
- Every client has its own static token.
- Only SHA-256 token digests are stored in `config/clients.json`.
- Per-client ACLs control tool access and Trilium read/write roots.
- `TRILIUM_WRITE_ROOT_NOTE_ID` is an optional global write ceiling.
- There is intentionally no delete tool.
- Backend API credentials remain server-side in `.env`.
- Audit logs contain client identity and operation metadata, but not note contents or secrets.
- The container runs as an unprivileged user, drops Linux capabilities, and uses a read-only filesystem.

Do not treat the MCP hostname itself as a secret.

## Current MCP tools

| Tool | Type | Purpose |
|---|---|---|
| `gateway_status` | READ | Gateway version, client identity, and enabled integrations |
| `trilium_health_check` | READ | Test Trilium ETAPI connectivity |
| `trilium_search_notes` | READ | Search notes within the client's permitted read scope |
| `trilium_get_note` | READ | Read a note within the client's permitted read scope |
| `trilium_create_note` | WRITE | Create a child note within an allowed write root |
| `trilium_update_note` | WRITE | Update a note within an allowed write root |

There is intentionally no Trilium delete tool.

---

## 1. Clone and prepare

```bash
git clone https://github.com/lurrnet/personal-mcp.git
cd personal-mcp
cp .env.example .env
chmod 600 .env
```

Edit the server-side configuration:

```bash
nano .env
```

Recommended v0.4 configuration:

```env
MCP_PUBLIC_HOST=mcp.example.com
MCP_HOST=0.0.0.0
MCP_PORT=8765

MCP_AUTH_MODE=multi_bearer
MCP_CLIENTS_FILE=/config/clients.json

MCP_INTEGRATIONS=trilium
MCP_AUDIT_LOG=true

TRILIUM_ETAPI_URL=https://notes.example.com/etapi
TRILIUM_ETAPI_TOKEN=<dedicated-etapi-token>

# Optional global ceiling. Leave blank when different clients need
# unrelated Trilium write roots.
TRILIUM_WRITE_ROOT_NOTE_ID=
```

Never commit `.env`.

### About `TRILIUM_WRITE_ROOT_NOTE_ID`

In v0.4, normal write authorization should usually be defined by each client's `write_roots`.

If all clients must remain under one common Trilium subtree, you can additionally set:

```env
TRILIUM_WRITE_ROOT_NOTE_ID=<common-parent-note-id>
```

That becomes a second, global write boundary.

If different clients need unrelated roots, leave it blank:

```env
TRILIUM_WRITE_ROOT_NOTE_ID=
```

The per-client ACLs will then define the write boundaries.

---

## 2. Create a token for each client

Do **not** reuse the same token for ChatGPT, OpenClaw, scripts, or other services.

Generate one random token per client:

```bash
openssl rand -hex 32
```

For example, generate separate raw tokens for:

```text
chatgpt
openclaw
automation
```

Keep each raw token private. It is entered only into the corresponding MCP client.

For each raw token, calculate its SHA-256 digest:

```bash
printf '%s' 'PASTE_RAW_TOKEN_HERE' | sha256sum
```

On macOS, either of these also works:

```bash
printf '%s' 'PASTE_RAW_TOKEN_HERE' | shasum -a 256
```

Only the resulting 64-character SHA-256 digest goes into `config/clients.json`.

---

## 3. Configure per-client ACLs

Create the live ACL file:

```bash
mkdir -p config
cp config/clients.example.json config/clients.json
chmod 755 config
chmod 644 config/clients.json
nano config/clients.json
```

`config/clients.json` is gitignored.

The container runs as UID `10001`. Because `./config` is bind-mounted read-only into the container, a host-owned `clients.json` with mode `600` would normally be unreadable by that UID. The documented `644` mode allows the container to read the file.

The file contains token hashes and ACL metadata, not raw client tokens or backend API credentials. If you want stricter host permissions, make the file readable by UID `10001` through ownership/group permissions instead.

Example:

```json
{
  "clients": {
    "chatgpt": {
      "token_sha256": "SHA256_OF_CHATGPT_RAW_TOKEN",
      "allowed_tools": [
        "gateway_status",
        "trilium_health_check",
        "trilium_search_notes",
        "trilium_get_note",
        "trilium_create_note",
        "trilium_update_note"
      ],
      "trilium": {
        "read_roots": ["*"],
        "write_roots": ["AI_WORKSPACE_NOTE_ID"]
      }
    },
    "openclaw": {
      "token_sha256": "SHA256_OF_OPENCLAW_RAW_TOKEN",
      "allowed_tools": [
        "gateway_status",
        "trilium_search_notes",
        "trilium_get_note"
      ],
      "trilium": {
        "read_roots": ["PROJECTS_NOTE_ID"],
        "write_roots": []
      }
    }
  }
}
```

### ACL fields

`allowed_tools`

Defines the exact MCP tools that client may invoke.

Example:

```json
"allowed_tools": [
  "trilium_search_notes",
  "trilium_get_note"
]
```

Use:

```json
"allowed_tools": ["*"]
```

only if that client should be able to invoke every registered MCP tool.

`trilium.read_roots`

Defines the Trilium roots the client may read.

Read the entire Trilium account visible to the ETAPI token:

```json
"read_roots": ["*"]
```

Restrict reads to one or more subtrees:

```json
"read_roots": [
  "PROJECTS_NOTE_ID",
  "RESEARCH_NOTE_ID"
]
```

`trilium.write_roots`

Defines where the client may create or update notes:

```json
"write_roots": ["AI_WORKSPACE_NOTE_ID"]
```

Disable writes completely:

```json
"write_roots": []
```

Multiple independent write roots are supported:

```json
"write_roots": [
  "OPENCLAW_NOTE_ID",
  "AUTOMATION_INBOX_NOTE_ID"
]
```

---

## 4. Recommended client policies

A practical setup is:

```text
ChatGPT
  READ  -> all Trilium
  WRITE -> ChatGPT / AI Workspace
  TOOLS -> search, get, create, update

OpenClaw
  READ  -> selected OpenClaw / Projects subtrees
  WRITE -> OpenClaw Workspace
  TOOLS -> only what OpenClaw needs

Automation
  READ  -> Inbox or selected source notes
  WRITE -> Automation Inbox
  TOOLS -> minimum required set
```

The important rule is **one identity, one token, one ACL per service**.

---

## 5. Start the gateway

Build and start:

```bash
docker compose build
docker compose up -d
```

Check the logs:

```bash
docker compose logs --tail=100 personal-mcp
```

Follow logs continuously:

```bash
docker compose logs -f personal-mcp
```

Verify that Docker publishes only on loopback:

```bash
ss -lntp | grep 8765
```

Expected:

```text
127.0.0.1:8765
```

Do not expose port `8765` directly through OCI Security Lists or NSGs when using a tunnel/reverse proxy.

---

## 6. Cloudflare Tunnel

Point the public MCP hostname to the local service:

```text
mcp.example.com -> http://localhost:8765
```

The MCP endpoint is then:

```text
https://mcp.example.com/mcp
```

The public hostname can be reachable from the internet; authorization is enforced by the MCP bearer token.

---

## 7. Test authentication

Without a token:

```bash
curl -i https://mcp.example.com/mcp
```

Expected:

```text
401 Unauthorized
```

With one client's raw token:

```bash
curl -i \
  -H "Authorization: Bearer YOUR_CLIENT_RAW_TOKEN" \
  https://mcp.example.com/mcp
```

This should pass the authentication layer.

A simple GET request is not a complete MCP protocol exchange, so the final response does not need to look like a normal web page. The important distinction is that a valid token should not receive the gateway's `401 Unauthorized` response.

Test an invalid token as well:

```bash
curl -i \
  -H "Authorization: Bearer wrong-token" \
  https://mcp.example.com/mcp
```

Expected:

```text
401 Unauthorized
```

---

## 8. Connect ChatGPT

Create or edit the custom MCP app in ChatGPT:

```text
Name:           Personal MCP
Connection:     Server URL
Server URL:     https://mcp.example.com/mcp
Authentication: Access token / API key
Token:          <ChatGPT's raw client token>
```

Use the **raw token generated specifically for the `chatgpt` client**.

Do not enter any of these into ChatGPT:

- `TRILIUM_ETAPI_TOKEN`;
- another service's MCP token;
- the SHA-256 digest from `clients.json`.

After connecting, a useful verification sequence is:

1. call `gateway_status` and confirm `client=chatgpt`;
2. call `trilium_health_check`;
3. search for a harmless note;
4. read the note;
5. create a test note inside an allowed write root;
6. update that note;
7. attempt a write outside the allowed root and confirm that it is rejected.

---

## 9. Connect additional MCP clients

For OpenClaw or another service:

1. generate a new raw token;
2. calculate its SHA-256 digest;
3. add a new entry to `config/clients.json`;
4. define the minimum required `allowed_tools`, `read_roots`, and `write_roots`;
5. restart the gateway if the configuration has changed;
6. configure that service with its own raw token.

Do not copy ChatGPT's raw token into another service.

---

## 10. Audit log

Audit events include the authenticated client identity.

Example:

```json
{
  "ts": "2026-10-06T12:00:00+00:00",
  "client": "chatgpt",
  "tool": "trilium_search_notes",
  "action": "read",
  "ok": true,
  "query_length": 8,
  "result_count": 2
}
```

Another client would appear separately:

```json
{
  "client": "openclaw",
  "tool": "trilium_get_note",
  "action": "read",
  "ok": true
}
```

The audit logger intentionally does not record:

- raw MCP tokens;
- token hashes;
- Trilium ETAPI tokens;
- Authorization headers;
- note contents.

View logs with:

```bash
docker compose logs -f personal-mcp
```

---

## 11. How authorization works

For `MCP_AUTH_MODE=multi_bearer`, each request follows this flow:

```text
Authorization: Bearer <raw token>
        |
        v
SHA-256(raw token)
        |
        v
match token_sha256 in clients.json
        |
        v
identify client
        |
        +--> allowed_tools check
        |
        +--> Trilium read_roots / write_roots check
        |
        +--> optional global TRILIUM_WRITE_ROOT_NOTE_ID check
        |
        v
execute tool
```

A request is rejected if:

- the bearer token is missing or invalid;
- the client is not permitted to invoke that tool;
- the target note is outside the client's read roots;
- the target note is outside the client's write roots;
- a global write root is configured and the target falls outside it.

---

## 12. Updating v0.4

Pull the latest code:

```bash
cd ~/github/personal-mcp
git pull
```

If application code, the Dockerfile, or dependencies changed:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

If only `config/clients.json` or `.env` changed, restarting is usually sufficient:

```bash
docker compose restart personal-mcp
```

Then verify:

```bash
docker compose logs --tail=100 personal-mcp
```

---

## 13. Project layout

```text
personal-mcp/
├── README.md
├── compose.yml
├── .env.example
├── .gitignore
├── config/
│   ├── clients.example.json
│   └── clients.json          # local only, gitignored
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

---

## 14. Adding another integration

Add one module per backend under:

```text
app/integrations/
```

For example:

```text
app/integrations/
├── trilium/
├── nextcloud/
├── immich/
└── oci/
```

Keep the same security principles:

1. backend credentials stay server-side;
2. expose narrow MCP tools rather than raw passthrough HTTP endpoints;
3. prefix tools by integration, such as `nextcloud_read_file`;
4. give every client only the tools and resources it actually needs;
5. avoid destructive tools unless there is a clear authorization model;
6. never log secrets or private payload contents.

---

## Legacy single-token mode

v0.4 still contains compatibility support for:

```env
MCP_AUTH_MODE=bearer
MCP_API_TOKEN=<single-shared-token>
```

This mode gives every holder of that token the same MCP identity and does not provide the v0.4 per-client ACL model.

It is retained for compatibility only. New deployments should use:

```env
MCP_AUTH_MODE=multi_bearer
MCP_CLIENTS_FILE=/config/clients.json
```

---

## Future improvements

Possible future upgrades include:

- OAuth or JWT-based client identity;
- token rotation and expiration;
- rate limits per client;
- immutable or remote audit storage;
- approval workflows for destructive operations;
- additional backend integrations;
- a secret manager instead of environment-file secrets.

For the current personal/private deployment model, **multi-client static tokens + per-client ACLs** provide a practical balance between simplicity, isolation, and auditability.
