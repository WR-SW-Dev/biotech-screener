"""CRT × Options join table — prep for catalyst EV model.

For each resolved CRT record, joins:
  - options surface state at time of prediction
  - event premium decomposition
  - implied vs realized move
  - price reaction

This is the foundation for the eventual:
  predicted_hit_prob × implied_move × historical_hit_rate

Usage:
    python scripts/research/build_crt_options_join.py
"""

from __future__ import annotations

import csv
import json
import logging
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
RESOLUTION_DIR = SNAPSHOT_DIR / "resolutions"
OUTPUT_DIR = REPO_ROOT / "output" / "catalyst_ev"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("crt_options_join")


def _sf(v) -> float:
    if v is None or v == "" or v == "None":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def load_crt_resolutions() -> list[dict]:
    """Load all CRT resolution records."""
    records = []
    if not RESOLUTION_DIR.exists():
        return records
    for month_dir in sorted(RESOLUTION_DIR.iterdir()):
        if not month_dir.is_dir() or not month_dir.name[:4].isdigit():
            continue
        for f in sorted(month_dir.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    rec = json.load(fh)
                if rec.get("outcome") and rec.get("outcome") not in ("INFORMATIONAL",):
                    records.append(rec)
            except (json.JSONDecodeError, OSError):
                pass
    return records


def find_prediction_snapshot(ticker: str, catalyst_date: str) -> str | None:
    """Find the most recent snapshot before the catalyst date for this ticker."""
    dates = sorted(
        d.name
        for d in SNAPSHOT_DIR.iterdir()
        if d.is_dir() and d.name < catalyst_date and (d / "rankings.csv").exists()
    )
    if not dates:
        return None
    # Find the closest date before catalyst
    return dates[-1]


def load_options_at_prediction(ticker: str, snapshot_date: str) -> dict:
    """Load options fields from the prediction-date snapshot."""
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return {}
    with open(rpath, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker", "").upper() == ticker.upper():
                return {
                    "opt_has_data": row.get("opt_has_data", ""),
                    "opt_atm_iv": _sf(row.get("opt_atm_iv")),
                    "opt_front_iv": _sf(row.get("opt_front_iv")),
                    "opt_back_iv": _sf(row.get("opt_back_iv")),
                    "opt_rr_25d": _sf(row.get("opt_rr_25d")),
                    "opt_term_slope": _sf(row.get("opt_term_slope")),
                    "opt_event_premium": row.get("opt_event_premium", ""),
                    "opt_iv_regime": row.get("opt_iv_regime", ""),
                    "opt_liquidity_ok": row.get("opt_liquidity_ok", ""),
                    "actual_implied_move_pctile": _sf(row.get("actual_implied_move_pctile")),
                    "implied_event_move": _sf(row.get("implied_event_move")),
                    "opt_dte": _sf(row.get("opt_dte")),
                    "catalyst_days": _sf(row.get("catalyst_days")),
                    "actionable_rank": row.get("actionable_rank", ""),
                    "tier_any": row.get("tier_any", ""),
                }
    return {}


def build_join_table() -> dict:
    """Build the CRT × options join table."""
    resolutions = load_crt_resolutions()
    log.info("Loaded %d CRT resolutions", len(resolutions))

    joined = []
    for rec in resolutions:
        ticker = rec.get("ticker", "")
        catalyst_date = rec.get("catalyst_date", "")
        if not ticker or not catalyst_date:
            continue

        # Find prediction snapshot
        snap_date = find_prediction_snapshot(ticker, catalyst_date)
        if not snap_date:
            continue

        # Load options state at prediction time
        opts = load_options_at_prediction(ticker, snap_date)

        # Compute implied vs realized
        implied_move = opts.get("implied_event_move", float("nan"))
        price_direction = rec.get("price_direction", "")
        price_return = _sf(rec.get("price_return_1d"))

        implied_vs_realized = None
        if not math.isnan(implied_move) and implied_move > 0 and not math.isnan(price_return):
            implied_vs_realized = abs(price_return) / implied_move

        # Event premium ratio
        front_iv = opts.get("opt_front_iv", float("nan"))
        back_iv = opts.get("opt_back_iv", float("nan"))
        epr = None
        if not math.isnan(front_iv) and not math.isnan(back_iv) and back_iv > 0:
            epr = front_iv / back_iv

        joined.append(
            {
                "ticker": ticker,
                "catalyst_date": catalyst_date,
                "catalyst_type": rec.get("catalyst_type", ""),
                "outcome": rec.get("outcome", ""),
                "price_direction": price_direction,
                "prediction_dem_rank": rec.get("prediction_dem_rank"),
                "prediction_tier": rec.get("prediction_tier", ""),
                "prediction_snapshot_date": snap_date,
                # Options at prediction time
                "opt_has_data": opts.get("opt_has_data", ""),
                "opt_atm_iv": opts.get("opt_atm_iv"),
                "opt_rr_25d": opts.get("opt_rr_25d"),
                "opt_event_premium": opts.get("opt_event_premium", ""),
                "opt_iv_regime": opts.get("opt_iv_regime", ""),
                "opt_liquidity_ok": opts.get("opt_liquidity_ok", ""),
                "implied_event_move": implied_move if not math.isnan(implied_move) else None,
                "actual_implied_move_pctile": opts.get("actual_implied_move_pctile"),
                "event_premium_ratio": epr,
                "catalyst_days_at_prediction": opts.get("catalyst_days"),
                # Outcome
                "realized_abs_return": abs(price_return) if not math.isnan(price_return) else None,
                "implied_vs_realized": implied_vs_realized,
                "market_overpriced": (
                    (implied_vs_realized is not None and implied_vs_realized < 1.0)
                    if implied_vs_realized is not None
                    else None
                ),
            }
        )

    # Summary stats
    n_with_options = sum(1 for j in joined if j.get("opt_has_data") == "1")
    n_with_implied = sum(1 for j in joined if j.get("implied_event_move") is not None)
    n_with_realized = sum(1 for j in joined if j.get("realized_abs_return") is not None)
    n_overpriced = sum(1 for j in joined if j.get("market_overpriced") is True)
    n_underpriced = sum(1 for j in joined if j.get("market_overpriced") is False)

    return {
        "schema": "crt_options_join.v1",
        "n_resolutions": len(joined),
        "n_with_options": n_with_options,
        "n_with_implied_move": n_with_implied,
        "n_with_realized_return": n_with_realized,
        "n_overpriced": n_overpriced,
        "n_underpriced": n_underpriced,
        "records": joined,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = build_join_table()

    output_path = OUTPUT_DIR / "crt_options_join.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    print(f"\nCRT × OPTIONS JOIN TABLE")
    print(f"  Resolutions: {result['n_resolutions']}")
    print(f"  With options: {result['n_with_options']}")
    print(f"  With implied move: {result['n_with_implied_move']}")
    print(f"  With realized return: {result['n_with_realized_return']}")
    print(f"  Market overpriced: {result['n_overpriced']}")
    print(f"  Market underpriced: {result['n_underpriced']}")

    # Print records
    if result["records"]:
        print(
            f"\n  {'Ticker':<7} {'Date':<12} {'Outcome':<8} {'EP':<5} {'IVreg':<10} {'Implied':<9} {'Realized':<9} {'Over?':<6}"
        )
        for r in result["records"]:
            imp = f"{r['implied_event_move']:.2f}" if r.get("implied_event_move") else "—"
            real = f"{r['realized_abs_return']:.2f}" if r.get("realized_abs_return") else "—"
            over = "YES" if r.get("market_overpriced") is True else "NO" if r.get("market_overpriced") is False else "—"
            print(
                f"  {r['ticker']:<7} {r['catalyst_date']:<12} {r['outcome']:<8} {r['opt_event_premium']:<5} {r['opt_iv_regime']:<10} {imp:<9} {real:<9} {over:<6}"
            )


if __name__ == "__main__":
    main()
