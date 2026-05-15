# Hermes Telegram Command Handler

Enables two-way Telegram communication with Hermes. The operator can send commands to the Telegram bot to query system state in real-time.

## Quick Start

### 1. Verify credentials in `.env`
```bash
grep TELEGRAM_ .env
```
Expected output:
```
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_ID=<chat_id>
```

If not set, get the token from [@BotFather](https://t.me/BotFather) and chat ID from [@userinfobot](https://t.me/userinfobot).

### 2. Test in dry-run mode
```bash
python3 tools/telegram_command_handler.py --dry-run --once --log-level INFO
```

Expected output:
```
[timestamp] __main__ INFO: Telegram command handler starting (dry_run=True)
[timestamp] __main__ INFO: No updates; exiting (--once)
```

### 3. Send a test command
Open the Telegram chat and send:
```
/help
```

If the bot responds with a list of commands, everything is working.

### 4. (Optional) Launch as daemon on system boot
Add to crontab:
```bash
crontab -e
```

Add this line:
```
@reboot sleep 60 && cd /mnt/c/Projects/biotech_screener/biotech-screener && python3 tools/telegram_command_handler.py >> logs/telegram_handler.log 2>&1
```

The daemon will:
- Auto-start on system reboot
- Wait 60 seconds for network to be ready (WSL2 timing)
- Run indefinitely, polling Telegram every 30 seconds
- Log to `logs/telegram_handler.log`
- Use PID file at `artifacts/ops/telegram_handler.pid` to prevent duplicate instances

## Available Commands

| Command | Response |
|---------|----------|
| `/help` | List all commands |
| `/status` | System health overview (latest snapshot, git HEAD, ops verdict) |
| `/agents` | Fleet agent health summary from latest heartbeat |
| `/held` | List of held specs and their status |
| `/snap` | Latest snapshot pipeline status (module pass/fail counts) |

## Architecture

### Long-polling (not webhook)
- No public HTTPS URL required
- Suitable for WSL2 / local development
- Polls `getUpdates` with 30-second timeout every cycle
- Tracks `last_update_id` to avoid re-processing

### Authorization
- Only responds to the configured `TELEGRAM_CHAT_ID` from `.env`
- Other users in the chat are silently ignored
- No permission checking beyond chat ID

### Read-only state
All commands read existing artifacts; nothing is mutated:
- `artifacts/ops/knowledge_layer/latest_state.json`
- `artifacts/ops/held_spec_ledger/latest.json`
- `artifacts/heartbeat/<date>_heartbeat.md`
- `data/snapshots/<date>/run_manifest.json`

## Modes

### Daemon (default)
```bash
python3 tools/telegram_command_handler.py
```
Runs indefinitely, polling Telegram in a loop. PID file guard prevents multiple instances.

### Dry-run (testing)
```bash
python3 tools/telegram_command_handler.py --dry-run --once
```
- `--dry-run` — logs replies without sending to Telegram
- `--once` — process one batch of updates and exit
- Useful for testing command handlers before enabling live mode

### Manual one-shot polling
```bash
python3 tools/telegram_command_handler.py --once
```
Polls once, processes any pending messages, and exits. Can be wired into cron for periodic checks (e.g., every 5 minutes).

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Chat ID where bot listens (from @userinfobot) |
| `TELEGRAM_HANDLER_DRY_RUN` | No | "0" | "1" to skip sending (can override with `--dry-run` flag) |

## Monitoring

### Check if daemon is running
```bash
ps aux | grep telegram_command_handler
```

### Check daemon logs
```bash
tail -f logs/telegram_handler.log
```

### Check PID file
```bash
cat artifacts/ops/telegram_handler.pid
```

### Stop daemon
```bash
kill $(cat artifacts/ops/telegram_handler.pid)
```

## Troubleshooting

### Bot doesn't respond to commands
1. Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly:
   ```bash
   source .env && echo "Token: $TELEGRAM_BOT_TOKEN" && echo "Chat ID: $TELEGRAM_CHAT_ID"
   ```
2. Test in dry-run mode:
   ```bash
   python3 tools/telegram_command_handler.py --dry-run --once
   ```
3. Check if daemon is running:
   ```bash
   ps aux | grep telegram_command_handler
   ```

### Daemon exits immediately
1. Check for existing daemon:
   ```bash
   ps aux | grep telegram_command_handler
   ```
   Kill it: `kill $(cat artifacts/ops/telegram_handler.pid)`
2. Check logs:
   ```bash
   tail -20 logs/telegram_handler.log
   ```

### Command returns "No artifacts found"
This is normal if the required artifacts don't exist yet. Artifacts are created by Hermes jobs:
- `/status` needs `artifacts/ops/knowledge_layer/latest_state.json`
- `/agents` needs `artifacts/heartbeat/<date>_heartbeat.md`
- `/held` needs `artifacts/ops/held_spec_ledger/latest.json`
- `/snap` needs `data/snapshots/<date>/run_manifest.json`

## Testing

Run the test suite:
```bash
python3 -m pytest tests/test_telegram_command_handler.py -v
```

Expected: 27/27 tests pass.

## Files

| File | Purpose |
|------|---------|
| `tools/telegram_command_handler.py` | Main handler (daemon + commands) |
| `tests/test_telegram_command_handler.py` | Unit tests (27 tests) |
| `docs/TELEGRAM_COMMAND_HANDLER.md` | This file |
