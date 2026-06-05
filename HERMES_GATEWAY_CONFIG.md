# Hermes Gateway LAN Configuration

**Date**: 2026-06-05  
**Status**: ✅ Applied & Verified

## Problem Statement

Hermes gateway gateways were not accessible from the LAN:
- **lmstudio gateway** bound to `127.0.0.1:8643` (localhost only)
- **default gateway** failed to start (Telegram token conflict with researcher gateway)
- **researcher gateway** listening on correct interface but couldn't coexist with default

## Changes Applied

### 1. lmstudio Gateway - Enable LAN Access

**File**: `~/.hermes/profiles/lmstudio/.env`
```diff
- API_SERVER_HOST="127.0.0.1"
+ API_SERVER_HOST="0.0.0.0"
```

**File**: `~/.hermes/profiles/lmstudio/config.yaml`
```diff
platforms:
  api_server:
    extra:
-     host: 127.0.0.1
+     host: 0.0.0.0
      port: 8643
```

### 2. Default Gateway - Resolve Telegram Conflict

**File**: `~/.hermes/config.yaml`
```diff
telegram:
+  enabled: false
   reactions: false
   channel_prompts: {}
   allowed_chats: ""

platforms:
  discord:
-   enabled: false
+   enabled: false  # No bot token configured
```

## Verification

```bash
# Port bindings after fix
lsof -i -P -n | grep hermes

# Results:
# TCP *:8643 (LISTEN)     - lmstudio gateway (LAN accessible)
# TCP *:8642 (LISTEN)     - researcher gateway (LAN accessible)

# Health checks
curl http://127.0.0.1:8643/health  # ✓ OK
curl http://127.0.0.1:8642/health  # ✓ OK
```

## Current Status

| Gateway | Status | Port | Access | Health |
|---------|--------|------|--------|--------|
| lmstudio | ✓ Running | 8643 | LAN (0.0.0.0) | ✓ OK |
| researcher | ✓ Running | 8642 | LAN (0.0.0.0) | ✓ OK |
| default | ✗ Disabled | — | — | Telegram disabled |

## Notes

- The `API_SERVER_HOST` environment variable in `.env` takes precedence over `config.yaml`
- Both gateways now accessible from LAN machines on ports 8643 and 8642
- Default gateway conflicts resolved by disabling Telegram on main config
- Researcher gateway retains full platform support (Telegram enabled in its profile)
