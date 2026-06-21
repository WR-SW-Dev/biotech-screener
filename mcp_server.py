"""MCP Server for Biotech Screener — exposes screener tools to Hermes Agent.

Tools exposed:
  - screen_universe(as_of, filters) — run the screener
  - get_catalysts(ticker) — upcoming catalysts for a ticker
  - get_clinical_trials(ticker) — trial data for a ticker
  - compare_snapshots(date_a, date_b) — diff two snapshots
  - get_atlas_data(category) — scientific cartography data
  - get_universe() — list all biotech companies in universe
  - get_company_detail(ticker) — comprehensive detail for a single ticker
  - get_backtest() — backtest results (IC, bucket returns, hit rates)

Usage:
  Register in Hermes config.yaml under mcp_servers:
    biotech-screener:
      command: python
      args: ["C:\\Projects\\biotech_screener\\biotech-screener\\mcp_server.py"]
      env:
        BIOTECH_PROJECT_DIR: "C:\\Projects\\biotech_screener\\biotech-screener"

  Or run standalone:
    python mcp_server.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Resolve project directory
PROJECT_DIR = Path(os.environ.get("BIOTECH_PROJECT_DIR", Path(__file__).parent))
DATA_DIR = PROJECT_DIR / "data"
UNIVERSE_FILE = DATA_DIR / "universe" / "biotech_universe_v1.csv"
TRIAL_MAP_FILE = DATA_DIR / "trial_mapping.csv"
PRICES_FILE = DATA_DIR / "daily_prices.csv"
AACT_DIR = DATA_DIR / "aact_snapshots"
SNAPSHOTS_DIR = PROJECT_DIR / "output"  # snapshots live in output/

# Scientific cartography (if available)
CARTOGRAPHY_DIR = PROJECT_DIR / "scientific_cartography"


def _load_universe() -> list[dict[str, str]]:
    """Load the biotech universe CSV."""
    if not UNIVERSE_FILE.exists():
        return []
    with open(UNIVERSE_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_trial_map() -> dict[str, list[dict]]:
    """Load trial mapping, grouped by ticker."""
    if not TRIAL_MAP_FILE.exists():
        return {}
    mapping: dict[str, list[dict]] = {}
    with open(TRIAL_MAP_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").upper()
            if ticker:
                mapping.setdefault(ticker, []).append(row)
    return mapping


def _load_prices() -> dict[str, dict]:
    """Load daily prices, grouped by ticker."""
    if not PRICES_FILE.exists():
        return {}
    prices: dict[str, dict] = {}
    with open(PRICES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").upper()
            if ticker:
                prices[ticker] = row
    return prices


def _load_aact_studies() -> dict[str, dict]:
    """Load AACT studies from the latest snapshot dir."""
    if not AACT_DIR.is_dir():
        return {}
    subdirs = sorted(p for p in AACT_DIR.iterdir() if p.is_dir())
    if not subdirs:
        return {}
    studies_file = subdirs[-1] / "studies.csv"
    if not studies_file.exists():
        return {}
    out: dict[str, dict] = {}
    with open(studies_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nct = (row.get("nct_id") or "").strip()
            if nct:
                out[nct] = row
    return out


def _load_aact_sponsors() -> dict[str, list[str]]:
    """Load AACT sponsors -> {nct_id: [sponsor_name, ...]}."""
    if not AACT_DIR.is_dir():
        return {}
    subdirs = sorted(p for p in AACT_DIR.iterdir() if p.is_dir())
    if not subdirs:
        return {}
    sponsors_file = subdirs[-1] / "sponsors.csv"
    if not sponsors_file.exists():
        return {}
    out: dict[str, list[str]] = {}
    with open(sponsors_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nct = (row.get("nct_id") or "").strip()
            name = (row.get("name") or "").strip()
            if nct and name:
                out.setdefault(nct, []).append(name)
    return out


def _load_snapshots() -> list[str]:
    """List available snapshot dates."""
    if not SNAPSHOTS_DIR.exists():
        return []
    dates = []
    for p in SNAPSHOTS_DIR.glob("snapshot_*.json"):
        ds = p.stem.replace("snapshot_", "")
        if len(ds) == 10 and ds[4] == "-":
            dates.append(ds)
    return sorted(dates)


def _find_snapshot(date: str) -> Path | None:
    """Find snapshot file for a given date."""
    for name in (f"snapshot_{date}.json", f"{date}.json"):
        p = SNAPSHOTS_DIR / name
        if p.exists():
            return p
    return None


def _load_json_file(path: Path) -> dict | None:
    """Load a JSON file, returning None on failure."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ─── Tool implementations ────────────────────────────────────────────

def tool_get_universe() -> str:
    """List all biotech companies in the investable universe."""
    universe = _load_universe()
    if not universe:
        return json.dumps({"error": "Universe file not found", "path": str(UNIVERSE_FILE)})

    result = {
        "total": len(universe),
        "companies": [
            {"ticker": r.get("ticker", ""), "name": r.get("name", ""), "sector": r.get("sector", "")}
            for r in universe
        ],
    }
    return json.dumps(result, indent=2)


def tool_get_clinical_trials(ticker: str) -> str:
    """Get clinical trial data for a specific ticker."""
    ticker = ticker.upper().strip()
    trial_map = _load_trial_map()
    trials = trial_map.get(ticker, [])

    aact_studies = _load_aact_studies()

    if not trials:
        return json.dumps({"ticker": ticker, "trials": [], "message": "No trials found for this ticker"})

    result = {
        "ticker": ticker,
        "trial_count": len(trials),
        "trials": [
            {
                "nct_id": t.get("nct_id", ""),
                "effective_start": t.get("effective_start", ""),
                "effective_end": t.get("effective_end", ""),
                "source": t.get("source", ""),
                "sponsor": t.get("sponsor_name_at_map_time", ""),
                "confidence": t.get("mapping_confidence", ""),
                "phase": aact_studies.get(t.get("nct_id", ""), {}).get("phase", "Unknown"),
                "overall_status": aact_studies.get(t.get("nct_id", ""), {}).get("overall_status", "Unknown"),
                "primary_completion_date": aact_studies.get(t.get("nct_id", ""), {}).get("primary_completion_date", ""),
            }
            for t in trials
        ],
    }
    return json.dumps(result, indent=2)


def tool_get_catalysts(ticker: str) -> str:
    """Get upcoming catalysts for a specific ticker."""
    ticker = ticker.upper().strip()
    trial_map = _load_trial_map()
    trials = trial_map.get(ticker, [])
    aact_studies = _load_aact_studies()

    catalysts = []
    today = datetime.utcnow().date()
    for t in trials:
        nct = t.get("nct_id", "")
        study = aact_studies.get(nct, {})
        pcd = study.get("primary_completion_date", "")
        status = study.get("overall_status", "")

        upcoming = False
        if pcd and len(pcd) >= 10:
            try:
                pcd_date = datetime.strptime(pcd[:10], "%Y-%m-%d").date()
                upcoming = pcd_date >= today
            except ValueError:
                pass

        if upcoming or status.lower() in {"recruiting", "active, not recruiting"}:
            catalysts.append({
                "nct_id": nct,
                "phase": study.get("phase", "Unknown"),
                "status": status,
                "primary_completion_date": pcd,
                "upcoming": upcoming,
            })

    result = {
        "ticker": ticker,
        "trial_count": len(trials),
        "active_trials": len([t for t in trials if not t.get("effective_end")]),
        "upcoming_catalysts": len(catalysts),
        "catalysts": catalysts,
    }
    return json.dumps(result, indent=2)


def tool_screen_universe(as_of: str = "", filters: str = "") -> str:
    """Run the biotech screener for a given date."""
    universe = _load_universe()
    trial_map = _load_trial_map()
    prices = _load_prices()

    # Parse filters
    filter_dict: dict[str, str] = {}
    if filters:
        for pair in filters.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                filter_dict[k.strip()] = v.strip()

    # Build screen results
    results: list[dict] = []
    for company in universe:
        ticker = company.get("ticker", "").upper()
        trials = trial_map.get(ticker, [])
        price = prices.get(ticker, {})

        record = {
            "ticker": ticker,
            "name": company.get("name", ""),
            "sector": company.get("sector", ""),
            "trial_count": len(trials),
            "active_trials": len([t for t in trials if not t.get("effective_end")]),
            "has_price_data": bool(price),
            "as_of_date": as_of or datetime.now().strftime("%Y-%m-%d"),
        }

        # Load snapshot score if available
        snap_date = as_of or (_load_snapshots()[-1] if _load_snapshots() else "")
        if snap_date:
            snap_file = _find_snapshot(snap_date)
            if snap_file:
                snap_data = _load_json_file(snap_file)
                if snap_data:
                    for sec in snap_data.get("ranked_securities") or []:
                        if sec.get("ticker", "").upper() == ticker:
                            record["composite_score"] = sec.get("composite_score")
                            record["composite_rank"] = sec.get("composite_rank")
                            record["stage_bucket"] = sec.get("stage_bucket")
                            break

        results.append(record)

    # Apply filters
    if "min_trials" in filter_dict:
        min_t = int(filter_dict["min_trials"])
        results = [r for r in results if r["trial_count"] >= min_t]
    if "min_score" in filter_dict:
        min_s = float(filter_dict["min_score"])
        def _safe_score(r):
            s = r.get("composite_score")
            if s is None:
                return False
            try:
                return float(s) >= min_s
            except (TypeError, ValueError):
                return False
        results = [r for r in results if _safe_score(r)]

    return json.dumps({
        "as_of": as_of or "latest",
        "total_companies": len(results),
        "filters_applied": filter_dict,
        "results": results,
    }, indent=2)


def tool_compare_snapshots(date_a: str, date_b: str) -> str:
    """Compare two point-in-time snapshots."""
    snap_a = _find_snapshot(date_a)
    snap_b = _find_snapshot(date_b)

    if not snap_a:
        return json.dumps({"error": f"Snapshot not found for {date_a}"})
    if not snap_b:
        return json.dumps({"error": f"Snapshot not found for {date_b}"})

    data_a = _load_json_file(snap_a) or {}
    data_b = _load_json_file(snap_b) or {}

    # Compare ranked securities
    secs_a = {s.get("ticker", "").upper(): s for s in data_a.get("ranked_securities") or []}
    secs_b = {s.get("ticker", "").upper(): s for s in data_b.get("ranked_securities") or []}

    diffs = []
    for ticker in sorted(set(secs_a.keys()) | set(secs_b.keys())):
        a = secs_a.get(ticker)
        b = secs_b.get(ticker)
        if a and not b:
            diffs.append({"ticker": ticker, "status": "removed_in_b"})
        elif b and not a:
            diffs.append({"ticker": ticker, "status": "added_in_b"})
        elif a.get("composite_score") != b.get("composite_score"):
            diffs.append({
                "ticker": ticker,
                "status": "score_changed",
                "score_a": a.get("composite_score"),
                "score_b": b.get("composite_score"),
                "rank_a": a.get("composite_rank"),
                "rank_b": b.get("composite_rank"),
            })
        elif a.get("composite_rank") != b.get("composite_rank"):
            diffs.append({
                "ticker": ticker,
                "status": "rank_changed",
                "rank_a": a.get("composite_rank"),
                "rank_b": b.get("composite_rank"),
            })

    return json.dumps({
        "date_a": date_a,
        "date_b": date_b,
        "tickers_compared": len(set(secs_a.keys()) | set(secs_b.keys())),
        "diffs": diffs,
    }, indent=2)


def tool_get_atlas_data(category: str = "") -> str:
    """Get scientific cartography data."""
    if not CARTOGRAPHY_DIR.exists():
        return json.dumps({
            "error": "Scientific cartography module not found",
            "expected_path": str(CARTOGRAPHY_DIR),
        })

    result: dict[str, Any] = {
        "module": "scientific_cartography",
        "path": str(CARTOGRAPHY_DIR),
    }

    # List subdirectories as phases
    phases_dir = CARTOGRAPHY_DIR
    if phases_dir.exists():
        result["subdirectories"] = sorted([d.name for d in phases_dir.iterdir() if d.is_dir()])

    # List artifacts
    artifacts_dir = PROJECT_DIR / "artifacts"
    if artifacts_dir.exists():
        result["artifacts"] = sorted([d.name for d in artifacts_dir.iterdir() if d.is_dir()])[:20]

    # List normalizers
    normalize_dir = CARTOGRAPHY_DIR / "normalize"
    if normalize_dir.exists():
        result["normalizers"] = [f.stem for f in normalize_dir.glob("*.py") if f.name != "__init__.py"]

    # List schemas
    schemas_dir = CARTOGRAPHY_DIR / "schemas"
    if schemas_dir.exists():
        result["schemas"] = [f.stem for f in schemas_dir.glob("*.py") if f.name != "__init__.py"]

    if category:
        result["filter_applied"] = category

    return json.dumps(result, indent=2)


def tool_get_company_detail(ticker: str) -> str:
    """Get comprehensive detail for a single biotech company."""
    ticker = ticker.upper().strip()
    universe = _load_universe()
    trial_map = _load_trial_map()
    prices = _load_prices()
    aact_studies = _load_aact_studies()
    aact_sponsors = _load_aact_sponsors()

    company = next((c for c in universe if c.get("ticker", "").upper() == ticker), None)
    if not company:
        return json.dumps({"error": f"Ticker {ticker} not found in universe"})

    trials = trial_map.get(ticker, [])
    price = prices.get(ticker, {})

    # Load latest snapshot score
    snapshots = _load_snapshots()
    score_data = {}
    if snapshots:
        snap_file = _find_snapshot(snapshots[-1])
        if snap_file:
            snap_data = _load_json_file(snap_file)
            if snap_data:
                for sec in snap_data.get("ranked_securities") or []:
                    if sec.get("ticker", "").upper() == ticker:
                        score_data = sec
                        break

    result = {
        "ticker": ticker,
        "company": company,
        "scores": {
            "composite_score": score_data.get("composite_score"),
            "composite_rank": score_data.get("composite_rank"),
            "clinical_dev_score": score_data.get("clinical_dev_normalized"),
            "financial_score": score_data.get("financial_normalized"),
            "catalyst_score": score_data.get("catalyst_normalized"),
            "stage_bucket": score_data.get("stage_bucket"),
            "severity": score_data.get("severity"),
            "flags": score_data.get("flags", []),
        },
        "clinical_trials": {
            "count": len(trials),
            "active": len([t for t in trials if not t.get("effective_end")]),
            "details": [
                {
                    "nct_id": t.get("nct_id", ""),
                    "start": t.get("effective_start", ""),
                    "end": t.get("effective_end", ""),
                    "sponsor": t.get("sponsor_name_at_map_time", ""),
                    "source": t.get("source", ""),
                    "confidence": t.get("mapping_confidence", ""),
                    "phase": aact_studies.get(t.get("nct_id", ""), {}).get("phase", "Unknown"),
                    "overall_status": aact_studies.get(t.get("nct_id", ""), {}).get("overall_status", "Unknown"),
                    "primary_completion_date": aact_studies.get(t.get("nct_id", ""), {}).get("primary_completion_date", ""),
                    "all_sponsors": aact_sponsors.get(t.get("nct_id", ""), []),
                }
                for t in trials
            ],
        },
        "market_data": price if price else {"message": "No price data available"},
        "available_snapshots": snapshots,
    }

    return json.dumps(result, indent=2)


def tool_get_backtest() -> str:
    """Get backtest results — IC, bucket returns, hit rates."""
    backtest_file = SNAPSHOTS_DIR / "backtest_results.json"
    data = _load_json_file(backtest_file)
    if not data:
        return json.dumps({"error": "Backtest results not found", "path": str(backtest_file)})

    # Summarize
    periods = data.get("period_metrics", {})
    horizons = data.get("horizons_display", ["3m", "6m", "12m"])
    horizon_keys = data.get("horizons", ["63d", "126d", "252d"])

    summary = []
    for date_str in sorted(periods.keys()):
        period = periods[date_str]
        period_summary = {"date": date_str, "n_ranked": period.get("n_ranked", 0), "horizons": {}}
        for hk, hd in zip(horizon_keys, horizons):
            h_data = period.get("horizons", {}).get(hk, {})
            period_summary["horizons"][hd] = {
                "ic_spearman": h_data.get("ic_spearman"),
                "n_obs": h_data.get("n_obs", 0),
                "coverage_pct": h_data.get("coverage_pct"),
                "q5_minus_q1": h_data.get("q5_minus_q1"),
                "hit_rate_q5": h_data.get("hit_rate_q5"),
            }
        summary.append(period_summary)

    return json.dumps({
        "run_id": data.get("run_id"),
        "horizons": horizons,
        "periods": summary,
        "aggregate": data.get("aggregate_metrics", {}),
    }, indent=2)


# ─── MCP Protocol (stdio) ────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_universe",
        "description": "List all biotech companies in the investable universe.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_clinical_trials",
        "description": "Get clinical trial data for a specific biotech ticker, including phase and status from AACT.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Stock ticker (e.g., MRNA, BNTX)"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_catalysts",
        "description": "Get upcoming catalysts (trial readouts, PDUFA dates) for a biotech ticker.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Stock ticker"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "screen_universe",
        "description": "Run the biotech screener. Returns all companies with trial counts, scores, and basic metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "description": "Point-in-time date (YYYY-MM-DD). Defaults to latest."},
                "filters": {"type": "string", "description": "Comma-separated filters (e.g., 'min_trials=2,min_score=30')"},
            },
            "required": [],
        },
    },
    {
        "name": "compare_snapshots",
        "description": "Compare two point-in-time snapshots to see what changed (scores, ranks, additions, removals).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_a": {"type": "string", "description": "First date (YYYY-MM-DD)"},
                "date_b": {"type": "string", "description": "Second date (YYYY-MM-DD)"},
            },
            "required": ["date_a", "date_b"],
        },
    },
    {
        "name": "get_atlas_data",
        "description": "Get scientific cartography data — disease maps, program records, normalizers, schemas.",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "Optional filter: diseases, programs, review"}},
            "required": [],
        },
    },
    {
        "name": "get_company_detail",
        "description": "Get comprehensive detail for a single biotech company — scores, trials, prices, catalysts.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Stock ticker"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_backtest",
        "description": "Get backtest results — IC (Spearman), bucket returns, hit rates across all snapshot periods and horizons.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

TOOL_HANDLERS = {
    "get_universe": lambda args: tool_get_universe(),
    "get_clinical_trials": lambda args: tool_get_clinical_trials(args.get("ticker", "")),
    "get_catalysts": lambda args: tool_get_catalysts(args.get("ticker", "")),
    "screen_universe": lambda args: tool_screen_universe(args.get("as_of", ""), args.get("filters", "")),
    "compare_snapshots": lambda args: tool_compare_snapshots(args.get("date_a", ""), args.get("date_b", "")),
    "get_atlas_data": lambda args: tool_get_atlas_data(args.get("category", "")),
    "get_company_detail": lambda args: tool_get_company_detail(args.get("ticker", "")),
    "get_backtest": lambda args: tool_get_backtest(),
}


def handle_request(request: dict) -> dict | None:
    """Handle a single MCP JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "biotech-screener", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # No response for notifications

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        try:
            result = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                    "isError": True,
                },
            }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main():
    """Run the MCP server over stdio."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
