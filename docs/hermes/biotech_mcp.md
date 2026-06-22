# biotech-mcp — read-only diagnostic MCP server

`tools/biotech_mcp_server.py` is a stdlib-only, **read-only** MCP server that
gives Hermes (or any MCP client) a small, typed view of the biotech model's
existing diagnostic artifacts. It is Package C of the containment-first Hermes
upgrade (see `docs/incidents/INC_2026_06_20_AUTOPUSH_CLOSEOUT_2026_06_22.md`
and `docs/governance/HERMES_OPENCLAW_LANGGRAPH_RUNTIME_BOUNDARY_2026_06_22.md`).

Goal: make the model **more observable** without making it more autonomous —
answer "what changed in today's snapshot?", "are the gates passing?", "is
Event-EV feature coverage starved?", "which disease maps have unknowns?",
"what Semgrep rules are in force?" — with no write path of any kind.

## Safety guarantees (by construction)

| Constraint | How it's enforced |
|---|---|
| No shell escape | The server never spawns a subprocess. `run_readonly_diagnostics` aggregates already-generated artifacts in-process; it does **not** run the diagnostics scripts. |
| No arbitrary file read | Every tool is pinned to a known artifact under a fixed subtree (`data/snapshots/`, `artifacts/`, `.semgrep/`). Date inputs are validated against `^\d{4}-\d{2}-\d{2}$` and resolved with a path-escape guard. |
| No git / config / job writes | No tool writes anything; there is no write code path. |
| No network | No sockets, no HTTP, no MCP-to-MCP calls. |
| No mutation / trading / "repair" | Not implemented and not reachable. |
| Bounded output | JSONL tails, CSV row caps, dir-entry caps, integer-arg bounds. |

Mirrors the conventions of the repo's existing read-only server
`mcp_server/hermes_server.py` (JSON-RPC 2.0 over NDJSON / Content-Length).

## Tools

| Tool | Args | Reads |
|---|---|---|
| `list_snapshots` | `limit?` (1–500, default 30) | `data/snapshots/<date>/` dirs + key-file presence |
| `read_latest_snapshot_manifest` | `date?` | `data/snapshots/<date>/snapshot_manifest.json` |
| `read_gate_verdicts` | `limit?` (1–50, default 5), `date?` | `artifacts/gate_verdict_ledger.jsonl` (tail) + `ees_gate_diagnostics.json` |
| `read_phase2_health` | `date?` | `data/snapshots/<date>/phase2_health.json` |
| `read_rankings_schema` | `date?`, `sample_rows?` (0–5) | `rankings.csv` headers + row count (+ optional small sample) |
| `read_event_ev_feature_coverage` | `date?` | `artifacts/scientific_cartography/<date>/landscape_feature_coverage_report.json` |
| `read_forward_eval_ic_ledger` | `limit?` (1–50, default 10) | `artifacts/readiness/forward_eval_ic_baseline.json` (recent observations) |
| `read_scientific_cartography_status` | `date?` | `artifacts/scientific_cartography/<date>/scientific_cartography_status.json` |
| `list_disease_map_artifacts` | `date?` | `artifacts/scientific_cartography/<date>/` files + `disease_map_summary.json` |
| `read_semgrep_findings` | — | `.semgrep/*.y*ml` rule inventory (findings are **not** persisted in-repo; CI/pre-commit generate them) |
| `run_readonly_diagnostics` | `date?` | in-process rollup of the above (snapshot/gates/phase2/cartography/IC) |

`date` defaults to the latest available snapshot or cartography run when omitted.

## Run / verify

```bash
# health check
python3 tools/biotech_mcp_server.py --health
# -> {"ok": true, "server": "biotech-mcp", "mode": "stdio", "version": "0.1.0"}

# speak JSON-RPC over stdio (one message per line, NDJSON)
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 tools/biotech_mcp_server.py

# tests
python3 -m pytest tests/test_biotech_mcp_server.py -q
```

`BIOTECH_MCP_REPO` overrides the repo root (used by the test fixture).

## Registration (NOT YET WIRED — operator decision)

Per the containment-first plan, the server is built and tested but **not**
registered into any agent runtime. Adding it to Hermes/Cursor is a config
change to make deliberately. Reference config when ready:

```jsonc
// Hermes MCP server entry — read-only; expose only these tools.
{
  "biotech": {
    "command": "python3",
    "args": ["tools/biotech_mcp_server.py"],
    "cwd": "/mnt/c/Projects/biotech_screener/biotech-screener",
    "tools": { "include": [
      "list_snapshots", "read_latest_snapshot_manifest", "read_gate_verdicts",
      "read_phase2_health", "read_rankings_schema", "read_event_ev_feature_coverage",
      "read_forward_eval_ic_ledger", "read_scientific_cartography_status",
      "list_disease_map_artifacts", "read_semgrep_findings", "run_readonly_diagnostics"
    ] }
  }
}
```

Every tool is read-only, so an `include` allowlist is belt-and-suspenders, not
a security boundary — but keep it explicit so the surface stays auditable.

## Status

Package C complete: server + 25 hermetic tests (all passing) + this doc.
Next (Package D/E): an MCP-server intake rubric, then admit external MCPs
(Semgrep MCP first) one at a time through it.
