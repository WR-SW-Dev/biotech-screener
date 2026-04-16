#!/usr/bin/env python3
"""Run OpenClaw agents directly via Anthropic SDK, bypassing the gateway.

Workaround for OpenClaw gateway billing issue (OPENCLAW_SETUP_TOKEN
triggers "third-party apps" rejection). Uses ANTHROPIC_API_KEY directly.

Reads the agent's IDENTITY.md + SOUL.md + memory, constructs a system
prompt, sends the message, and logs the response.

Usage:
    python3 tools/run_agent_direct.py --agent ops --message "HEARTBEAT"
    python3 tools/run_agent_direct.py --agent sentinel --message "HEARTBEAT"
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"

# Per-agent model overrides. Agents not listed default to Sonnet.
# Haiku is used for routine/deterministic tasks (file checks, structured capture).
AGENT_MODELS = {
    "aact_trial_ingest": "claude-haiku-4-5-20251001",
    "company_news_ingest": "claude-haiku-4-5-20251001",
    "postmortem": "claude-haiku-4-5-20251001",
    "ctgov_poller": "claude-haiku-4-5-20251001",
    "price_action_watch": "claude-haiku-4-5-20251001",
    "biotech_news_digest": "claude-haiku-4-5-20251001",
    "shadow_monitor": "claude-haiku-4-5-20251001",
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
    """Resolve model for an agent: CLI override > AGENT_MODELS > default Sonnet."""
    if cli_model and cli_model != "claude-sonnet-4-6":
        return cli_model  # explicit CLI override takes precedence
    return AGENT_MODELS.get(agent_name, "claude-sonnet-4-6")


def run_agent(agent_name: str, message: str, model: str = "claude-sonnet-4-6", max_tokens: int = 4096) -> dict:
    """Run an agent via direct Anthropic SDK call."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Try loading from .env
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not found"}

    system_prompt = load_agent_context(agent_name)
    if not system_prompt:
        return {"error": f"No context loaded for agent {agent_name}"}

    # Add current date and project context
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    system_prompt += f"\n\n---\n\nCurrent time: {now}\nProject root: {PROJECT_ROOT}\n"

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


def main():
    parser = argparse.ArgumentParser(description="Run agent directly via Anthropic SDK")
    parser.add_argument("--agent", required=True, help="Agent name (e.g., ops, sentinel)")
    parser.add_argument("--message", default="HEARTBEAT", help="Message to send")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "logs" / "agents_direct")
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
    else:
        print(f"ERROR: {result.get('error', 'unknown')}")

    # Log
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = args.log_dir / f"{args.agent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nLogged: {log_file}")


if __name__ == "__main__":
    main()
