"""Read-only operator dashboard — Policy Control Tower.

Reads existing JSON/MD artifacts and serves a web UI. Does NOT modify
any production state, positions, rankings, or execution.

Usage:
    python dashboard/app.py
    python dashboard/app.py --port 8080
    uvicorn dashboard.app:app --reload --port 8050
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard")

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Biotech Screener — Policy Control Tower", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# --- Data loaders ---


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_jsonl(path: Path) -> List[Dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _available_snapshot_dates() -> List[str]:
    snap_dir = REPO_ROOT / "data" / "snapshots"
    import re

    date_pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    return sorted(
        (d.name for d in snap_dir.iterdir() if d.is_dir() and date_pat.match(d.name)),
        reverse=True,
    )


def _load_positions(date: str) -> List[Dict]:
    path = REPO_ROOT / "artifacts" / "live_shadow" / "positions" / f"{date}.json"
    data = _load_json(path)
    if not data:
        return []
    return data.get("positions", [])


def _load_rankings(date: str) -> Dict[str, Dict]:
    rpath = REPO_ROOT / "data" / "snapshots" / date / "rankings.csv"
    if not rpath.exists():
        return {}
    with open(rpath, encoding="utf-8") as f:
        return {r["ticker"]: r for r in csv.DictReader(f)}


def _load_policy_comparison(date: str) -> Optional[Dict]:
    path = REPO_ROOT / "artifacts" / "policy_shadow" / "tier_weighted" / f"{date}_comparison.json"
    return _load_json(path)


def _load_policy_history() -> List[Dict]:
    path = REPO_ROOT / "artifacts" / "policy_shadow" / "tier_weighted" / "history.jsonl"
    rows = _load_jsonl(path)
    # Deduplicate by date
    seen = set()
    deduped = []
    for r in rows:
        d = r.get("date")
        if d and d not in seen:
            seen.add(d)
            deduped.append(r)
    return sorted(deduped, key=lambda r: r["date"])


def _load_bioshort_watch() -> Optional[Dict]:
    watch_dir = REPO_ROOT / "artifacts" / "bioshort_watch"
    if not watch_dir.exists():
        return None
    files = sorted(watch_dir.glob("*_watch.json"), reverse=True)
    return _load_json(files[0]) if files else None


def _load_ops_digest(date: str) -> Optional[str]:
    path = REPO_ROOT / "artifacts" / "ops_digest" / f"{date}_digest.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _load_attribution(date: str) -> Optional[Dict]:
    path = REPO_ROOT / "artifacts" / "live_shadow" / "attribution" / date / "ATTRIBUTION_PACKET.json"
    return _load_json(path)


def _load_phase2_health(date: str) -> Optional[Dict]:
    path = REPO_ROOT / "data" / "snapshots" / date / "phase2_health.json"
    return _load_json(path)


def _load_shadow_performance() -> List[Dict]:
    path = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in csv.reader(f):
            if len(line) >= 10 and line[0] == "live_shadow_perf.v1":
                try:
                    rows.append(
                        {
                            "date": line[1],
                            "pnl": float(line[3]) if line[3] else 0,
                            "pnl_pct": float(line[4]) if line[4] else 0,
                            "xbi_pct": float(line[5]) if line[5] else 0,
                            "excess": float(line[6]) if line[6] else 0,
                            "positions": int(line[7]) if line[7] else 0,
                            "turnover": float(line[8]) if line[8] else 0,
                        }
                    )
                except (ValueError, IndexError):
                    pass
    return rows


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, date: str = ""):
    dates = _available_snapshot_dates()
    if not date and dates:
        date = dates[0]

    # Load all data for this date
    positions = _load_positions(date)
    rankings = _load_rankings(date)
    policy = _load_policy_comparison(date)
    policy_history = _load_policy_history()
    bioshort = _load_bioshort_watch()
    phase2 = _load_phase2_health(date)
    attribution = _load_attribution(date)
    perf = _load_shadow_performance()

    # Enrich positions with rankings data
    enriched_positions = []
    for p in positions:
        t = p.get("ticker", "")
        r = rankings.get(t, {})
        enriched_positions.append(
            {
                "ticker": t,
                "weight": p.get("weight_pct", 0),
                "bucket": p.get("bucket", ""),
                "tier": r.get("tier_dev", "?"),
                "rank": r.get("actionable_rank", ""),
                "mom": r.get("mom_state", ""),
                "risk": r.get("risk_flags", ""),
                "catalyst_days": r.get("catalyst_days", ""),
                "catalyst_family": r.get("catalyst_family", ""),
            }
        )
    enriched_positions.sort(key=lambda p: ({"A": 0, "B": 1, "C": 2, "D": 3}.get(p["tier"], 4), -p["weight"]))

    # Tier summary
    tier_summary = Counter(p["tier"] for p in enriched_positions)
    tier_weights = defaultdict(float)
    for p in enriched_positions:
        tier_weights[p["tier"]] += p["weight"]

    # Risky holds: C/D tier at >= 2% OR headwind + drawdown
    risky_holds = [
        p
        for p in enriched_positions
        if (p["tier"] in ("C", "D") and p["weight"] >= 2.0)
        or (p["mom"] == "headwind" and "deep_drawdown" in p.get("risk", ""))
    ]

    # Policy cumulative
    cum_current = 0.0
    cum_tiered = 0.0
    cum_exit = 0.0
    policy_path = []
    for row in policy_history:
        pc = row.get("pnl_current") or 0
        pt = row.get("pnl_tiered") or 0
        pe = row.get("pnl_exit") or 0
        cum_current += pc
        cum_tiered += pt
        cum_exit += pe
        if abs(pc) > 0.001:
            policy_path.append(
                {
                    "date": row["date"],
                    "current": round(cum_current, 2),
                    "tiered": round(cum_tiered, 2),
                    "exit": round(cum_exit, 2),
                }
            )

    # Attribution top/bottom
    attr_top = []
    attr_bottom = []
    if attribution:
        tc = attribution.get("top_contributors", {})
        attr_top = tc.get("top", [])[:5]
        attr_bottom = tc.get("bottom", [])[:5]

    # Shadow perf summary
    perf_trading = [p for p in perf if abs(p["pnl"]) > 0.01]
    cum_pnl = sum(p["pnl"] for p in perf)
    cum_pnl_pct = sum(p["pnl_pct"] for p in perf)

    # Alerts
    alerts = []
    if bioshort:
        for a in bioshort.get("alerts", []):
            alerts.append({"source": "bioshort", "level": bioshort.get("alert_level", "?"), "text": a})
    if policy:
        for ticker in policy.get("excluded_by_exit", []):
            alerts.append({"source": "policy", "level": "MEDIUM", "text": f"Exit overlay excluded: {ticker}"})
    if phase2 and phase2.get("status") == "FAIL":
        for reason in phase2.get("reasons", []):
            alerts.append({"source": "health", "level": "WARN", "text": f"Phase2: {reason}"})
    for p in risky_holds:
        alerts.append(
            {
                "source": "policy",
                "level": "LOW",
                "text": f"Risky hold: {p['ticker']} tier={p['tier']} wt={p['weight']:.1f}% mom={p['mom']} risk={p['risk']}",
            }
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "date": date,
            "dates": dates[:30],
            "positions": enriched_positions,
            "n_positions": len(enriched_positions),
            "tier_summary": dict(tier_summary),
            "tier_weights": {k: round(v, 1) for k, v in tier_weights.items()},
            "risky_holds": risky_holds,
            "policy": policy,
            "policy_path": policy_path,
            "policy_gap_tiered": round(cum_tiered - cum_current, 2),
            "policy_gap_exit": round(cum_exit - cum_current, 2),
            "bioshort": bioshort,
            "phase2": phase2,
            "alerts": alerts,
            "attr_top": attr_top,
            "attr_bottom": attr_bottom,
            "cum_pnl": round(cum_pnl, 0),
            "cum_pnl_pct": round(cum_pnl_pct, 2),
            "perf_trading": perf_trading[-10:],
            "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        },
    )


@app.get("/api/positions/{date}")
async def api_positions(date: str):
    return _load_positions(date)


@app.get("/api/policy/{date}")
async def api_policy(date: str):
    return _load_policy_comparison(date) or {"error": "not found"}


@app.get("/api/policy-history")
async def api_policy_history():
    return _load_policy_history()


@app.get("/api/bioshort")
async def api_bioshort():
    return _load_bioshort_watch() or {"error": "not found"}


# --- New endpoints for React dashboard (v2) ---


@app.get("/api/dates")
async def api_dates():
    """List available snapshot dates, newest first."""
    return _available_snapshot_dates()


@app.get("/api/rankings/{date}")
async def api_rankings(date: str, top_n: int = 200):
    """Full rankings table for a given date. Returns list of row dicts."""
    rpath = REPO_ROOT / "data" / "snapshots" / date / "rankings.csv"
    if not rpath.exists():
        return {"error": f"No rankings for {date}"}
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Sort by actionable_rank, filter to ranked names
    ranked = []
    for r in rows:
        ar = r.get("actionable_rank", "").strip()
        if ar:
            try:
                r["_rank_int"] = int(ar)
                ranked.append(r)
            except ValueError:
                pass
    ranked.sort(key=lambda r: r["_rank_int"])
    for r in ranked:
        r.pop("_rank_int", None)
    return ranked[:top_n]


@app.get("/api/decision_portfolio/{date}")
async def api_decision_portfolio(date: str):
    """DEM decision_portfolio.csv for a given date."""
    # Check output snapshots first (produced by daily production)
    for base in [REPO_ROOT / "output" / "snapshots", REPO_ROOT / "data" / "snapshots"]:
        path = base / date / "decision_portfolio.csv"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
            ranked.sort(key=lambda r: int(r["actionable_rank"]))
            return ranked
    return {"error": f"No decision_portfolio for {date}"}


@app.get("/api/ticker/{ticker}")
async def api_ticker_detail(ticker: str, date: str = ""):
    """Merged ticker detail: ranking row + position + options + CRT."""
    if not date:
        dates = _available_snapshot_dates()
        date = dates[0] if dates else ""
    if not date:
        return {"error": "No snapshots available"}

    # Rankings row
    rankings = _load_rankings(date)
    ranking_row = rankings.get(ticker.upper(), {})

    # Shadow position
    positions = _load_positions(date)
    position = next((p for p in positions if p.get("ticker") == ticker.upper()), {})

    # Options diagnostics from rankings row
    options = {
        "atm_iv_change_5d": ranking_row.get("atm_iv_change_5d", ""),
        "opt_rr_25d": ranking_row.get("opt_rr_25d", ""),
        "actual_implied_move_pctile": ranking_row.get("actual_implied_move_pctile", ""),
        "iv_percentile_30d": ranking_row.get("iv_percentile_30d", ""),
    }

    # CRT resolutions
    crt = []
    crt_dir = REPO_ROOT / "data" / "snapshots" / "resolutions"
    if crt_dir.exists():
        import glob

        for f in glob.glob(str(crt_dir / "**" / f"{ticker.upper()}_*.json"), recursive=True):
            try:
                with open(f, encoding="utf-8") as fh:
                    rec = json.load(fh)
                if rec.get("outcome") and rec.get("outcome") != "INFORMATIONAL":
                    crt.append(rec)
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "ticker": ticker.upper(),
        "date": date,
        "ranking": ranking_row,
        "position": position,
        "options": options,
        "crt_resolutions": crt,
    }


@app.get("/api/options_diagnostics/{date}")
async def api_options_diagnostics(date: str, top_n: int = 60):
    """Options fields extracted from rankings for the top-N names."""
    rankings = _load_rankings(date)
    if not rankings:
        return {"error": f"No rankings for {date}"}

    opts_fields = [
        "atm_iv_change_5d",
        "opt_rr_25d",
        "actual_implied_move_pctile",
        "iv_percentile_30d",
        "options_quality_composite",
    ]

    rows = []
    for ticker, r in rankings.items():
        ar = r.get("actionable_rank", "").strip()
        if not ar:
            continue
        try:
            rank = int(ar)
        except ValueError:
            continue
        if rank > top_n:
            continue
        row = {"ticker": ticker, "actionable_rank": rank}
        for field in opts_fields:
            row[field] = r.get(field, "")
        rows.append(row)

    rows.sort(key=lambda r: r["actionable_rank"])
    return rows


@app.get("/api/crt/resolutions")
async def api_crt_resolutions():
    """All CRT resolution records."""
    crt_dir = REPO_ROOT / "data" / "snapshots" / "resolutions"
    records = []
    if not crt_dir.exists():
        return records
    for month_dir in sorted(crt_dir.iterdir()):
        if not month_dir.is_dir() or not month_dir.name[:4].isdigit():
            continue
        for f in sorted(month_dir.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    rec = json.load(fh)
                if rec.get("outcome") and rec.get("outcome") != "INFORMATIONAL":
                    records.append(rec)
            except (json.JSONDecodeError, OSError):
                pass
    return records


@app.get("/api/crt/calibration")
async def api_crt_calibration():
    """Latest CRT calibration summary."""
    path = REPO_ROOT / "data" / "snapshots" / "resolutions" / "calibration_summary.json"
    return _load_json(path) or {"error": "No calibration summary"}


@app.get("/api/tier_bucket_heatmap/{date}")
async def api_tier_bucket_heatmap(date: str):
    """Tier x bucket counts for heatmap."""
    rankings = _load_rankings(date)
    if not rankings:
        return {"error": f"No rankings for {date}"}
    from collections import Counter

    grid = Counter()
    for r in rankings.values():
        tier = r.get("tier_any", "")
        bucket = r.get("catalyst_bucket", "")
        if tier and bucket:
            grid[(tier, bucket)] += 1
    buckets = sorted(set(b for _, b in grid.keys()))
    tiers = ["A", "B", "C", "D"]
    return {
        "tiers": tiers,
        "buckets": buckets,
        "counts": {f"{t}|{b}": grid.get((t, b), 0) for t in tiers for b in buckets},
    }


@app.get("/api/shadow_performance")
async def api_shadow_performance():
    """Shadow portfolio performance timeseries."""
    return _load_shadow_performance()


@app.get("/api/bioshort/verdict")
async def api_bioshort_verdict():
    """Latest bioshort verdict."""
    path = REPO_ROOT / "output" / "hedge_report" / "BIOSHORT_VERDICT.json"
    return _load_json(path) or {"error": "No bioshort verdict"}


@app.get("/api/bioshort/report")
async def api_bioshort_report():
    """Latest bioshort hedge report detail."""
    report_dir = REPO_ROOT / "output" / "hedge_report"
    if not report_dir.exists():
        return {"error": "No hedge reports"}
    files = sorted(report_dir.glob("hedge_report_*.json"), reverse=True)
    if not files:
        return {"error": "No hedge report files"}
    return _load_json(files[0]) or {"error": "Failed to load report"}


@app.get("/api/bioshort/watch")
async def api_bioshort_watch():
    """Latest bioshort watch alerts."""
    return _load_bioshort_watch() or {"error": "No bioshort watch"}


@app.get("/api/bioshort/archive")
async def api_bioshort_archive():
    """List of archived bioshort reports."""
    report_dir = REPO_ROOT / "output" / "hedge_report"
    if not report_dir.exists():
        return []
    files = sorted(report_dir.glob("hedge_report_*.json"), reverse=True)
    archive = []
    for f in files[:20]:
        data = _load_json(f)
        if data:
            archive.append(
                {
                    "date": data.get("as_of_date", f.stem.split("_")[-1]),
                    "file": f.name,
                }
            )
    return archive


@app.get("/api/herald/health")
async def api_herald_health():
    """Latest Herald health artifact."""
    health_dir = REPO_ROOT / "data" / "press_releases"
    if not health_dir.exists():
        return {"error": "No Herald data"}
    files = sorted(health_dir.glob("health_*.json"), reverse=True)
    if not files:
        return {"error": "No health reports"}
    return _load_json(files[0]) or {"error": "Failed to load health"}


@app.get("/api/herald/releases/{date}")
async def api_herald_releases(date: str, limit: int = 50):
    """Company press releases for a given date."""
    path = REPO_ROOT / "data" / "press_releases" / f"releases_{date}.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records[:limit]


@app.get("/api/herald/classified/{date}")
async def api_herald_classified(date: str, limit: int = 50):
    """Classified press releases for a given date."""
    path = REPO_ROOT / "data" / "press_releases" / "classified" / f"classified_{date}.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records[:limit]


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Biotech Screener Dashboard")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
