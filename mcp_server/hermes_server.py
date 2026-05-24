"""Repo-native Hermes MCP server.

This stdlib-only server provides the read-only Hermes tools referenced by
`.cursor/rules/hermes-context.mdc`. It intentionally avoids the external
Hermes checkout and the Python MCP SDK so Cursor can discover tools in fresh
cloud workspaces with only this repository present.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SERVER_NAME = "Hermes"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"

REPO_ROOT = Path(os.environ.get("HERMES_REPO", Path(__file__).resolve().parent.parent)).resolve()
AGENTS_DIR = Path(os.environ.get("HERMES_AGENTS_DIR", REPO_ROOT / "agents")).resolve()
REGISTRY_FILE = AGENTS_DIR / "AGENT_REGISTRY.json"
CONTEXT_RULE_FILE = REPO_ROOT / ".cursor" / "rules" / "hermes-context.mdc"
ROUTING_POLICY_FILE = REPO_ROOT / "governance" / "AGENT_ROUTING_POLICY.md"

AGENT_NAME_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
_OUTPUT_FRAMING = "ndjson"


def main() -> int:
    for line in _read_message_payloads():
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _write(_error_response(None, -32700, f"Parse error: {exc.msg}"))
            continue

        messages = message if isinstance(message, list) else [message]
        responses = [_handle_message(item) for item in messages]
        responses = [response for response in responses if response is not None]
        if not responses:
            continue
        if isinstance(message, list):
            _write(responses)
        else:
            _write(responses[0])

    return 0


def _read_message_payloads():
    global _OUTPUT_FRAMING

    stdin = sys.stdin.buffer
    while True:
        raw_line = stdin.readline()
        if raw_line == b"":
            return

        stripped = raw_line.strip()
        if not stripped:
            continue

        if stripped.lower().startswith(b"content-length:"):
            _OUTPUT_FRAMING = "content-length"
            length_text = stripped.split(b":", 1)[1].strip()
            try:
                content_length = int(length_text)
            except ValueError:
                yield "{"
                continue

            while True:
                header_line = stdin.readline()
                if header_line in (b"", b"\n", b"\r\n"):
                    break

            body = stdin.read(content_length)
            if body == b"":
                return
            yield body.decode("utf-8")
            continue

        yield raw_line.decode("utf-8").strip()


def _handle_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return _error_response(None, -32600, "Invalid Request")

    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if "id" not in message:
        return None

    if not isinstance(method, str):
        return _error_response(request_id, -32600, "Invalid Request")

    try:
        if method == "initialize":
            return _success_response(request_id, _initialize_result(params))
        if method == "ping":
            return _success_response(request_id, {})
        if method == "tools/list":
            return _success_response(request_id, {"tools": _tool_definitions()})
        if method == "tools/call":
            return _success_response(request_id, _call_tool(params))
        if method == "resources/list":
            return _success_response(request_id, {"resources": []})
        if method == "prompts/list":
            return _success_response(request_id, {"prompts": []})
    except ValueError as exc:
        return _error_response(request_id, -32602, str(exc))
    except Exception as exc:  # pragma: no cover - defensive MCP boundary
        print(f"{SERVER_NAME} MCP internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return _error_response(request_id, -32603, "Internal error")

    return _error_response(request_id, -32601, f"Method not found: {method}")


def _initialize_result(params: dict[str, Any]) -> dict[str, Any]:
    requested_version = params.get("protocolVersion") if isinstance(params, dict) else None
    return {
        "protocolVersion": requested_version or PROTOCOL_VERSION,
        "capabilities": {
            "tools": {
                "listChanged": False,
            },
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
        "instructions": (
            "Read-only Hermes fleet context for the biotech screener. "
            "Tools expose agent registry entries, agent SOUL/heartbeat files, "
            "and generated knowledge-layer artifacts when present."
        ),
    }


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "fleet_context_snapshot",
            "description": "Return a bounded read-only summary of Hermes fleet context and artifact availability.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "agents_list",
            "description": "List registered Hermes agents, optionally including heartbeat availability.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_heartbeat": {
                        "type": "boolean",
                        "description": "Whether to include HEARTBEAT.md availability for each agent.",
                        "default": False,
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter, for example active, shadow, or deprecated.",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "agents_get",
            "description": "Read one agent registry entry plus bounded local identity file metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Agent directory name from agents/AGENT_REGISTRY.json.",
                    },
                    "include_files": {
                        "type": "boolean",
                        "description": "Whether to list identity and tooling files in the agent directory.",
                        "default": True,
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "name": "skills_read",
            "description": "Read a bounded agent SOUL.md document.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Agent directory name.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return.",
                        "minimum": 1,
                        "maximum": 50000,
                        "default": 20000,
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "name": "knowledge_read",
            "description": "Read generated Hermes knowledge-layer artifacts when available.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "artifact": {
                        "type": "string",
                        "description": (
                            "Artifact name: latest_state, knowledge_layer, "
                            "held_spec_ledger, contradiction_ledger, or first_fire_ledger."
                        ),
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return from text artifacts.",
                        "minimum": 1,
                        "maximum": 100000,
                        "default": 50000,
                    },
                },
                "required": ["artifact"],
                "additionalProperties": False,
            },
        },
    ]


def _call_tool(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("tools/call params must be an object")

    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str):
        raise ValueError("tools/call requires string name")
    if not isinstance(arguments, dict):
        raise ValueError("tools/call arguments must be an object")

    tools = {
        "fleet_context_snapshot": _fleet_context_snapshot,
        "agents_list": _agents_list,
        "agents_get": _agents_get,
        "skills_read": _skills_read,
        "knowledge_read": _knowledge_read,
    }
    if name not in tools:
        raise ValueError(f"Unknown tool: {name}")

    result = tools[name](arguments)
    return {
        "content": [
            {
                "type": "text",
                "text": _json_text(result),
            }
        ],
        "isError": False,
    }


def _fleet_context_snapshot(_arguments: dict[str, Any]) -> dict[str, Any]:
    registry = _load_registry()
    agents = registry.get("agents", {}) if isinstance(registry.get("agents"), dict) else {}
    status_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    for entry in agents.values():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "unknown"))
        category = str(entry.get("category", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

    return {
        "server": SERVER_NAME,
        "mode": "read-only",
        "repo_root": _repo_relative(REPO_ROOT),
        "agent_registry": {
            "exists": REGISTRY_FILE.exists(),
            "path": _repo_relative(REGISTRY_FILE),
            "schema_version": registry.get("schema_version"),
            "as_of": registry.get("as_of"),
            "agent_count": len(agents),
            "status_counts": _sorted_dict(status_counts),
            "category_counts": _sorted_dict(category_counts),
        },
        "knowledge_artifacts": _knowledge_availability(),
        "context_rule": _file_summary(CONTEXT_RULE_FILE),
        "routing_policy": _file_summary(ROUTING_POLICY_FILE),
        "tooling_note": "This MCP server is read-only and does not mutate data, config, jobs, or artifacts.",
    }


def _agents_list(arguments: dict[str, Any]) -> dict[str, Any]:
    include_heartbeat = bool(arguments.get("include_heartbeat", False))
    status_filter = arguments.get("status")
    if status_filter is not None and not isinstance(status_filter, str):
        raise ValueError("status must be a string")

    registry = _load_registry()
    agents = registry.get("agents", {}) if isinstance(registry.get("agents"), dict) else {}
    rows = []
    for agent_name in sorted(agents):
        entry = agents[agent_name]
        if not isinstance(entry, dict):
            continue
        if status_filter and entry.get("status") != status_filter:
            continue
        row = {
            "name": agent_name,
            "role": entry.get("role"),
            "category": entry.get("category"),
            "cadence": entry.get("cadence"),
            "status": entry.get("status"),
            "authority_level": entry.get("authority_level"),
            "llm_policy": entry.get("llm_policy"),
            "supervised_by_orchestrator": entry.get("supervised_by_orchestrator"),
        }
        if include_heartbeat:
            row["heartbeat"] = _file_summary(AGENTS_DIR / agent_name / "HEARTBEAT.md")
        rows.append(row)

    return {
        "registry_path": _repo_relative(REGISTRY_FILE),
        "count": len(rows),
        "agents": rows,
    }


def _agents_get(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_name = _require_agent_name(arguments.get("name"))
    include_files = bool(arguments.get("include_files", True))
    registry = _load_registry()
    agents = registry.get("agents", {}) if isinstance(registry.get("agents"), dict) else {}
    if agent_name not in agents:
        raise ValueError(f"Unknown agent: {agent_name}")

    agent_dir = _agent_dir(agent_name)
    result: dict[str, Any] = {
        "name": agent_name,
        "registry_path": _repo_relative(REGISTRY_FILE),
        "registry_entry": agents[agent_name],
        "directory": _repo_relative(agent_dir),
        "directory_exists": agent_dir.exists(),
        "identity_files": {
            "SOUL.md": _file_summary(agent_dir / "SOUL.md"),
            "IDENTITY.md": _file_summary(agent_dir / "IDENTITY.md"),
            "HEARTBEAT.md": _file_summary(agent_dir / "HEARTBEAT.md"),
            "TOOLS.md": _file_summary(agent_dir / "TOOLS.md"),
            "AGENTS.md": _file_summary(agent_dir / "AGENTS.md"),
        },
    }

    if include_files:
        result["files"] = _list_agent_files(agent_dir)

    return result


def _skills_read(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_name = _require_agent_name(arguments.get("name"))
    max_chars = _max_chars(arguments.get("max_chars"), default=20000, upper=50000)
    registry = _load_registry()
    agents = registry.get("agents", {}) if isinstance(registry.get("agents"), dict) else {}
    if agent_name not in agents:
        raise ValueError(f"Unknown agent: {agent_name}")

    soul_file = _agent_dir(agent_name) / "SOUL.md"
    return _read_text_file(soul_file, max_chars=max_chars)


def _knowledge_read(arguments: dict[str, Any]) -> dict[str, Any]:
    artifact = arguments.get("artifact")
    if not isinstance(artifact, str) or not artifact:
        raise ValueError("artifact is required")
    max_chars = _max_chars(arguments.get("max_chars"), default=50000, upper=100000)

    candidates = _knowledge_candidates(artifact)
    for candidate in candidates:
        if candidate.exists():
            if candidate.suffix == ".json":
                return {
                    "artifact": artifact,
                    "selected_path": _repo_relative(candidate),
                    "exists": True,
                    "format": "json",
                    "content": _read_json(candidate),
                }
            payload = _read_text_file(candidate, max_chars=max_chars)
            payload["artifact"] = artifact
            return payload

    return {
        "artifact": artifact,
        "exists": False,
        "checked_paths": [_repo_relative(path) for path in candidates],
        "note": "Artifact not present in this checkout; run tools/build_hermes_knowledge_layer.py if needed.",
    }


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_FILE.exists():
        return {}
    return _read_json(REGISTRY_FILE)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"value": data}
    return data


def _read_text_file(path: Path, *, max_chars: int) -> dict[str, Any]:
    summary = _file_summary(path)
    if not path.exists():
        return {
            **summary,
            "content": "",
            "truncated": False,
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return {
        **summary,
        "content": text[:max_chars],
        "truncated": truncated,
        "max_chars": max_chars,
    }


def _knowledge_candidates(artifact: str) -> list[Path]:
    normalized = artifact.strip().lower().replace("-", "_")
    aliases = {
        "latest_state": "knowledge_layer",
        "state": "knowledge_layer",
    }
    directory = aliases.get(normalized, normalized)

    filenames = {
        "knowledge_layer": ["latest_state.json", "latest_state.md"],
        "held_spec_ledger": ["latest.json", "latest.md"],
        "contradiction_ledger": ["latest.json", "latest.md"],
        "first_fire_ledger": ["latest.json", "latest.md"],
    }
    if directory not in filenames:
        raise ValueError(f"Unknown knowledge artifact: {artifact}")

    return [REPO_ROOT / "artifacts" / "ops" / directory / filename for filename in filenames[directory]]


def _knowledge_availability() -> dict[str, Any]:
    artifacts = {}
    for artifact in ["knowledge_layer", "held_spec_ledger", "contradiction_ledger", "first_fire_ledger"]:
        candidates = _knowledge_candidates(artifact)
        artifacts[artifact] = {
            "exists": any(path.exists() for path in candidates),
            "paths": [_repo_relative(path) for path in candidates],
        }
    return artifacts


def _file_summary(path: Path) -> dict[str, Any]:
    return {
        "path": _repo_relative(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
    }


def _list_agent_files(agent_dir: Path) -> list[str]:
    if not agent_dir.exists() or not agent_dir.is_dir():
        return []
    return sorted(_repo_relative(path) for path in agent_dir.iterdir() if path.is_file())


def _require_agent_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("name is required")
    if not AGENT_NAME_RE.fullmatch(value):
        raise ValueError("name must be a safe agent directory name")
    return value


def _agent_dir(agent_name: str) -> Path:
    path = (AGENTS_DIR / agent_name).resolve()
    if AGENTS_DIR not in path.parents and path != AGENTS_DIR:
        raise ValueError("agent path escapes agents directory")
    return path


def _max_chars(value: Any, *, default: int, upper: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("max_chars must be an integer")
    if value < 1 or value > upper:
        raise ValueError(f"max_chars must be between 1 and {upper}")
    return value


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sorted_dict(values: dict[str, int]) -> dict[str, int]:
    return {key: values[key] for key in sorted(values)}


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _success_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _write(message: Any) -> None:
    text = _json_text(message)
    if _OUTPUT_FRAMING == "content-length":
        encoded = text.encode("utf-8")
        sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii") + encoded)
        sys.stdout.buffer.flush()
        return

    sys.stdout.write(text + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
