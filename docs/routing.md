Let me dive into the gateway routing logic to trace the exact path from user request to container.


Let me also check how the gateway resolves user identity and switches routing modes.


Now I have the complete routing chain. Here's how Eido routes different users to their fixed containers:

---

## User → Container Routing: The Full Chain

### Step 1 — Identity Resolution (Gateway)

When a request hits `eido-gateway`, `get_current_user_id()` in `auth.py` resolves who you are via a **priority chain**:

```
1. CAS Session Cookie  (production)
2. X-Eido-User-Token   (scheduled task execution)
3. Auth-disabled mode  (dev — falls back to "dev-local")
```

The resolved `user_id` string is the routing key for everything downstream.

### Step 2 — Route Dispatch by Mode (`api.py`)

The API router is wired differently depending on which process is running:

| Process | What it runs | Routes for chat/sessions/workspace |
|---------|-------------|-----------------------------------|
| **eido-gateway** (`EIDO_SANDBOX_MODE=docker`) | Auth + proxy only | → `router_user` (proxy to user container) |
| **eido-user container** (`EIDO_TRUST_GATEWAY=1`) | Business logic only | → Direct uvicorn handlers |
| **Local/single-tenant** (default) | Everything in one process | → Direct uvicorn handlers |

### Step 3 — Sandbox Registry Lookup (`sandbox_manager.py`)

Every proxied request in `router_user.py` calls:

```python
handle = await get_sandbox_manager().ensure_running(user_id)
```

This consults `sandbox_registry.db` — a SQLite table keyed by `user_id`:

```
sandbox_registry
├── user_id          ← "alice@example.com" (CAS identity)
├── safe_user_id     ← "alice-example-com-a1b2c3d4" (Docker-safe)
├── container_name   ← "eido-user-alice-example-com-a1b2c3d4"
├── internal_host    ← container name (Docker DNS resolves it)
├── internal_port    ← 8000
├── status           ← "running" / "stopped"
├── last_active_at   ← epoch timestamp
├── created_at
└── updated_at
```

The `_safe_user_id()` function sanitizes the raw CAS identity into a Docker-compatible string (only `[A-Za-z0-9_-]` allowed, truncate + SHA1 suffix for collision avoidance).

### Step 4 — Container Lifecycle (`ensure_running`)

`ensure_running(user_id)` is **idempotent** — it handles every scenario:

```
sandbox_registry.db
        │
        ├── No row exists? ──► _create_container()
        │                     ├── image: damaohongtu/eido-user
        │                     ├── name: eido-user-<safe_user_id>
        │                     ├── network: eido-net
        │                     ├── volume: eido-user-<safe>
        │                     ├── mounts: skills/ (read-only bind)
        │                     └── env: EIDO_USER_ID, EIDO_GATEWAY_SECRET, LLM keys
        │
        ├── Row exists, container running? ──► Reuse immediately, refresh last_active_at
        │
        ├── Row exists, container stopped? ──► docker start → reuse
        │
        └── Container missing entirely? ──► Force remove stale record → recreate
```

### Step 5 — Reverse Proxy with Trust Header Injection (`proxy.py`)

Once the `SandboxHandle` points to `http://eido-user-<safe>:8000`, the proxy:

1. **Strips** incoming headers that could be forged by a malicious client:
   - `Cookie`, `X-Eido-User-Id`, `X-Eido-Gateway-Secret`, `X-Eido-User-Token`, `X-Forwarded-User`

2. **Injects** fresh trust headers from gateway to user container:
   - `X-Eido-User-Id: alice@example.com`
   - `X-Eido-Gateway-Secret: <32+ char random secret>`

3. **Proxies** the request to `http://<container_name>:8000/api/v1/...`

4. For **SSE responses**: disables buffering, sets `X-Accel-Buffering: no`, keeps the connection alive. When the stream ends, calls `release(user_id)` to refresh `last_active_at` (preventing GC during long-running tasks).

### Step 6 — User Container Verification (Trusted Gateway)

Inside the `eido-user` container, `auth.py` has a separate code path:

```python
# Only active when EIDO_TRUST_GATEWAY=1
user_id = request.headers.get("X-Eido-User-Id")
# Verify: hmac.compare_digest(provided_secret, EIDO_GATEWAY_SECRET)
# Verify: user_id == EIDO_USER_ID (container's bound identity)
```

The user container trusts the gateway **blindly** only if:
- `EIDO_TRUST_GATEWAY=1`
- `X-Eido-Gateway-Secret` matches the shared secret via constant-time comparison
- `X-Eido-User-Id` matches the container's own `EIDO_USER_ID` env var

This prevents a compromised container from impersonating another user, and prevents anyone from directly hitting a user container's port without going through the gateway.

---

### Summary Diagram

```
Browser (Alice)                   Browser (Bob)
     │                                  │
     ▼                                  ▼
[eido-gateway :80] ◄── nginx
     │
     ├── auth.py: get_current_user_id()
     │   └── Session cookie → "alice@example.com"    "bob@example.com"
     │
     ├── api.py: route dispatch
     │   └── /chat/* → router_user (proxy)
     │
     ├── router_user.py:
     │   └── ensure_running("alice@example.com")
     │       └── sandbox_registry.db lookup
     │           └── container_name = "eido-user-alice-..."
     │
     ├── proxy.py:
     │   ├── strip incoming Cookie/X-Eido-* headers
     │   ├── inject X-Eido-User-Id + X-Eido-Gateway-Secret
     │   └── proxy → http://eido-user-alice-...:8000/api/v1/chat/chat
     │
     ├──→ [eido-user-alice-... :8000]
     │       └── auth.py: verify gateway secret + bound user_id
     │       └── direct uvicorn handler (chat/sessions/workspace)
     │
     └──→ [eido-user-bob-... :8000]
             └── (same verification chain)
```

The key design principle: **user_id is the single routing key**. It flows from CAS login → session → `get_current_user_id()` → `sandbox_registry.db` → container DNS name → proxy target. At no point can a client influence which container they're routed to — the gateway owns the identity-resolution and container-mapping chain end-to-end.