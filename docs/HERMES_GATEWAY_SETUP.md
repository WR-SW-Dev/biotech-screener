# Hermes Gateway & LLM Fallback Configuration

**Last Updated**: 2026-05-13  
**Status**: ✓ Operational

## Overview

Hermes gateway routes LLM requests through a cascading fallback chain. Current configuration:

1. **Primary**: OpenRouter (Claude Sonnet 4.6) — **Out of credits**
2. **Fallback 1**: Together AI (Llama 3.3 70B Instruct Turbo) — **Active**
3. **Fallback 2**: Nous Research (Trinity Large Thinking) — **Backup**

## Configuration Files

### Hermes Config
Location: `~/.hermes/config.yaml`

```yaml
model:
  default: anthropic/claude-sonnet-4.6
  provider: openrouter
  base_url: https://openrouter.ai/api/v1

providers:
  together:
    base_url: https://api.together.xyz/v1
    api_key: $TOGETHER_API_KEY  # Set in ~/.bashrc
    default_model: meta-llama/Llama-3.3-70B-Instruct-Turbo

fallback_providers:
- provider: together
  model: meta-llama/Llama-3.3-70B-Instruct-Turbo
  base_url: https://api.together.xyz/v1
  api_key: $TOGETHER_API_KEY  # Set in ~/.bashrc
- provider: nous
  model: arcee-ai/trinity-large-thinking
  base_url: https://inference-api.nousresearch.com/v1
```

### Bash Environment
Location: `~/.bashrc`

```bash
export TOGETHER_API_KEY="<api-key-from-together.ai>"  # Configure in ~/.bashrc
```

**Note**: API key must be set in `~/.bashrc` and also in `~/.hermes/config.yaml` (direct embedding needed for systemd service to access it).

## Gateway Status

**Gateway Process**: Hermes Agent v0.13.0 (2026.5.7)  
**Service**: `hermes-gateway.service` (systemd user service)  
**Port**: 8642  
**Status**: Running ✓

### Start/Stop Commands
```bash
# Check status
hermes gateway status

# Restart gateway (picks up config changes)
hermes gateway restart

# View logs
journalctl --user-unit hermes-gateway -f
```

## API Endpoints & Models

### Together AI (Llama 3.3 70B)
```
Endpoint: https://api.together.xyz/v1/chat/completions
Model: meta-llama/Llama-3.3-70B-Instruct-Turbo
Context Length: 131,072 tokens
Pricing: $0.88 per 1M input + output tokens
Status: ✓ Operational
```

### Nous Research (Trinity)
```
Endpoint: https://inference-api.nousresearch.com/v1
Model: arcee-ai/trinity-large-thinking
Context Length: 262,144 tokens
Status: ✓ Backup
```

## Testing

### Direct Together API Test
```bash
source ~/.bashrc
curl -X POST https://api.together.xyz/v1/chat/completions \
  -H "Authorization: Bearer $TOGETHER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "messages": [{"role": "user", "content": "test"}],
    "max_tokens": 50
  }'
```

### Hermes Interactive Chat
```bash
hermes chat                        # Interactive
hermes chat -q "your query"        # Single query
hermes chat -q "query" -Q          # Quiet mode (response only)
```

### View Fallback Chain in Action
```bash
hermes chat -q "What is the capital of France?"
```

Output will show cascade:
```
❌ OpenRouter: HTTP 402 (out of credits)
🔄 Switching to fallback: meta-llama/Llama-3.3-70B-Instruct-Turbo via together
✓ Response generated
```

## Known Issues & Fixes

### Issue: Together API Returns HTTP 401
**Cause**: API key as environment variable reference in config, but systemd service doesn't load bashrc.

**Fix Applied** (2026-05-13):
- Embedded API key directly in `~/.hermes/config.yaml` (both `providers:` and `fallback_providers:` sections)
- Registered credential via `hermes auth add together --type api-key --api-key <key>`
- Restarted gateway: `hermes gateway restart`

**Result**: Fallback chain now functional. Hermes cascades from OpenRouter → Llama successfully.

### Issue: Compression Model Context Mismatch
**Warning**: Qwen compression model has 65K context, but main model threshold is 500K.

**To Fix Permanently**:
```yaml
# In config.yaml, either:
# Option 1: Use larger compression model
auxiliary:
  compression:
    model: claude-sonnet-4.6

# Option 2: Lower compression threshold
compression:
  threshold: 0.06
```

## Governance Notes

- **Hermes** manages model routing and fallback chain
- **OpenClaw** agents use Hermes for LLM inference
- Both currently route through **Llama 3.3 70B** (fallback 1)
- No code changes to model logic — configuration only

## Related

- Biotech Screener memory: `memory/biotech_stabilization_checkpoint_2026_05_08.md`
- OpenRouter out of credits status documented in session logs
- Together AI fallback integration: commit `799630f0` (ranker decision) + this setup

## Next Steps

1. **Monitor**: Track Llama performance on governance tasks
2. **Optional**: Request OpenRouter credits restoration if cost-effective
3. **Review**: Post-h20d checkpoint (2026-05-26) — may migrate back to primary when credits available
