#!/usr/bin/env python3
"""Run OpenClaw agents directly via Llama 3.3 70B (Together AI) or Claude (Anthropic).

Auto-routes based on model name:
- "claude-*" → Anthropic SDK (uses ANTHROPIC_API_KEY)
- "meta-llama/*" → Together AI API (uses TOGETHER_API_KEY)

Workaround for OpenClaw gateway billing issue (OPENCLAW_SETUP_TOKEN
triggers "third-party apps" rejection). Uses direct API keys instead.

Reads the agent's IDENTITY.md + SOUL.md + memory, constructs a system
prompt, sends the message, and logs the response.

Usage:
    python3 tools/run_agent_direct.py --agent ops --message "HEARTBEAT"
    python3 tools/run_agent_direct.py --agent sentinel --message "HEARTBEAT" --model meta-llama/Llama-3.3-70B-Instruct-Turbo
    python3 tools/run_agent_direct.py --agent catalyst_delta --message "DAILY" --write-memory
    python3 tools/run_agent_direct.py --agent shadow_monitor --message "DAILY" --write-memory

--write-memory: after a successful run, write the LLM response to
    agents/<name>/memory/YYYY-MM-DD.md (local date). Skipped if response is
    a bare heartbeat status token (HEARTBEAT_OK, SNAPSHOT_MISSING, etc.).
    Appends a timestamp footer. Idempotent: overwrites same-day file if rerun.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"

# Bare status tokens that indicate a heartbeat-only response — do not write to memory.
_HEARTBEAT_TOKENS = re.compile(
    r"^\s*(HEARTBEAT_OK|SNAPSHOT_MISSING|NO_PRIOR_DELTA|DELTA_STALE"
    r"|HEALTHY|NO_MONITOR|STALE|NO_PERF_DATA|NO_DATA|BUILDER_FAILED"
    r"|HEARTBEAT_FAIL|OK|PASS)\s*$",
    re.IGNORECASE,
)


def maybe_write_memory(agent_name: str, response_text: str) -> Path | None:
    """Write LLM response to agents/<name>/memory/YYYY-MM-DD.md if it contains
    substantive content (not just a bare heartbeat status token).

    Returns the path written, or None if skipped.
    """
    if _HEARTBEAT_TOKENS.match(response_text.strip()):
        return None  # bare status token — nothing to persist

    memory_dir = AGENTS_DIR / agent_name / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    mem_path = memory_dir / f"{today}.md"

    # Append run timestamp footer if not already present
    footer = (
        f"\n\n---\n_Written by run_agent_direct.py at {datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_\n"
    )
    content = response_text.rstrip() + footer

    mem_path.write_text(content, encoding="utf-8")
    return mem_path


# Per-agent model overrides. Agents not listed default to Llama 3.3 70B.
# Llama is used for all agents via Together AI API.
# Model format: "llama-3.3-70b" (auto-routed to Together)
AGENT_MODELS = {
    "aact_trial_ingest": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "company_news_ingest": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "postmortem": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "ctgov_poller": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "price_action_watch": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "biotech_news_digest": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "shadow_monitor": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "ops": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "sentinel": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "data_auditor": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "ic_health_monitor": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "fleet_steward": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
}


def load_agent_context(agent_name: str) -> str:
    """Load agent identity + soul + memory into a system prompt."""
    agent_dir = AGENTS_DIR / agent_name
    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    parts = []

    # Identity
    identity_path = agent_dir / "IDENTITY.md"
    if identity_path.exists():
        parts.append(identity_path.read_text(encoding="utf-8"))

    # Soul
    soul_path = agent_dir / "SOUL.md"
    if soul_path.exists():
        parts.append(soul_path.read_text(encoding="utf-8"))

    # Memory files
    memory_dir = agent_dir / "memory"
    if memory_dir.exists():
        for mem_file in sorted(memory_dir.glob("*.md")):
            parts.append(f"## Memory: {mem_file.stem}\n\n{mem_file.read_text(encoding='utf-8')}")

    # Heartbeat template
    heartbeat_path = agent_dir / "HEARTBEAT.md"
    if heartbeat_path.exists():
        parts.append(f"## Heartbeat Protocol\n\n{heartbeat_path.read_text(encoding='utf-8')}")

    return "\n\n---\n\n".join(parts)


def resolve_model(agent_name: str, cli_model: str | None = None) -> str:
    """Resolve model for an agent: CLI override > AGENT_MODELS > default Llama 3.3 70B."""
    if cli_model:
        return cli_model  # explicit CLI override takes precedence
    return AGENT_MODELS.get(agent_name, "meta-llama/Llama-3.3-70B-Instruct-Turbo")


def run_agent(
    agent_name: str, message: str, model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo", max_tokens: int = 4096
) -> dict:
    """Run an agent via Anthropic SDK (Claude) or Together API (Llama).

    Auto-detects model type and routes to appropriate provider:
    - "claude-*" → Anthropic SDK
    - "meta-llama/*" → Together AI API (OpenAI-compatible)
    """
    system_prompt = load_agent_context(agent_name)
    if not system_prompt:
        return {"error": f"No context loaded for agent {agent_name}"}

    # Add current date and project context
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    system_prompt += f"\n\n---\n\nCurrent time: {now}\nProject root: {PROJECT_ROOT}\n"

    # Route to appropriate provider
    if "llama" in model.lower():
        return _run_agent_together(agent_name, message, model, max_tokens, system_prompt, now)
    else:
        return _run_agent_anthropic(agent_name, message, model, max_tokens, system_prompt, now)


def _run_agent_anthropic(
    agent_name: str, message: str, model: str, max_tokens: int, system_prompt: str, now: str
) -> dict:
    """Run agent via Anthropic SDK (Claude models)."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not found"}

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
        )

        result_text = response.content[0].text if response.content else ""

        return {
            "agent": agent_name,
            "model": model,
            "message": message,
            "response": result_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "timestamp": now,
            "status": "success",
        }

    except Exception as e:
        return {
            "agent": agent_name,
            "error": str(e),
            "timestamp": now,
            "status": "error",
        }


def _run_agent_together(
    agent_name: str, message: str, model: str, max_tokens: int, system_prompt: str, now: str
) -> dict:
    """Run agent via Together AI API (Llama models, OpenAI-compatible)."""
    from openai import OpenAI

    api_key = os.environ.get("TOGETHER_API_KEY")
    if not api_key:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("TOGETHER_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        return {"error": "TOGETHER_API_KEY not found"}

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.together.xyz/v1",
    )

    try:
        # Build messages with system prompt as first message (OpenAI format)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        # Note: Together API supports additional params via extra_body if needed
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.2,  # Deterministic for governance tasks
            top_p=0.95,
            frequency_penalty=0.1,
            messages=messages,
        )

        result_text = response.choices[0].message.content if response.choices else ""

        return {
            "agent": agent_name,
            "model": model,
            "message": message,
            "response": result_text,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
            "timestamp": now,
            "status": "success",
        }

    except Exception as e:
        return {
            "agent": agent_name,
            "error": str(e),
            "timestamp": now,
            "status": "error",
        }


def main():
    parser = argparse.ArgumentParser(description="Run agent directly via Anthropic SDK or Together AI (Llama)")
    parser.add_argument("--agent", required=True, help="Agent name (e.g., ops, sentinel)")
    parser.add_argument("--message", default="HEARTBEAT", help="Message to send")
    parser.add_argument(
        "--model",
        default="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        help="Model to use (auto-routes to Anthropic or Together based on model name)",
    )
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "logs" / "agents_direct")
    parser.add_argument(
        "--write-memory",
        action="store_true",
        default=False,
        help="Write LLM response to agents/<name>/memory/YYYY-MM-DD.md " "(skipped for bare heartbeat status tokens)",
    )
    args = parser.parse_args()

    # Load .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key and val and key not in os.environ:
                    os.environ[key] = val

    resolved_model = resolve_model(args.agent, args.model)
    print(f"Running agent '{args.agent}' (direct SDK, {resolved_model})...")
    result = run_agent(args.agent, args.message, resolved_model, args.max_tokens)

    if result.get("status") == "success":
        print(f"\n{result['response'][:2000]}")
        print(f"\n[{result['usage']['input_tokens']} in / {result['usage']['output_tokens']} out tokens]")
        if args.write_memory:
            mem_path = maybe_write_memory(args.agent, result["response"])
            if mem_path:
                print(f"Memory written: {mem_path}")
                result["memory_written"] = str(mem_path)
            else:
                print("Memory write skipped (bare status token response)")
                result["memory_written"] = None
    else:
        print(f"ERROR: {result.get('error', 'unknown')}")

    # Log
    args.log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file = args.log_dir / f"{args.agent}_{stamp}_{uuid.uuid4().hex[:8]}.json"
    with open(log_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nLogged: {log_file}")
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
