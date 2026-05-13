#!/usr/bin/env python3
"""Spec 092 Phase D — Forward returns analysis for bioshort research panel.

Join PIT-safe forward returns (T+1, T+5, T+20) to feature panel and compute
descriptive statistics: verdict accuracy, median returns by verdict/confidence,
correlation with hedge score.

Labels output as pseudo-PIT per Spec 092 §A6 (no promotion claims).
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT
PANEL_PATH = REPO_ROOT / "artifacts" / "research" / "bioshort_backfill" / "panel.csv"
MARKET_DATA_PATH = REPO_ROOT / "production_data" / "market_data.json"
OUTPUT_BASE = REPO_ROOT / "artifacts" / "research" / "bioshort_backfill"
ANALYSIS_PATH = OUTPUT_BASE / "forward_analysis"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_panel() -> pd.DataFrame:
    """Load feature panel from CSV."""
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Panel not found: {PANEL_PATH}")

    df = pd.read_csv(PANEL_PATH)
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    logger.info(f"Loaded panel: {len(df)} rows")
    return df


def load_market_data() -> dict:
    """Load PIT-safe market data for forward returns.

    Returns dict mapping ticker -> {'prices': {date_str -> price}}.
    """
    prices_dict = {}

    # Try indices_prices.csv first (XBI/SPY data)
    indices_path = REPO_ROOT / "data" / "indices_prices.csv"
    if indices_path.exists():
        with open(indices_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row["date"]
                if "XBI" in row and row["XBI"]:
                    if "XBI" not in prices_dict:
                        prices_dict["XBI"] = {}
                    try:
                        prices_dict["XBI"][date_str] = float(row["XBI"])
                    except (ValueError, TypeError):
                        pass

        logger.info(f"Loaded {len(prices_dict.get('XBI', {}))} XBI prices from indices_prices.csv")

    # Try production price history for more recent data
    prod_prices_path = REPO_ROOT / "production_data" / "price_history.csv"
    xbi_before = len(prices_dict.get("XBI", {}))
    ibb_before = len(prices_dict.get("IBB", {}))

    if prod_prices_path.exists():
        with open(prod_prices_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "")
                if ticker in ["XBI", "IBB"]:
                    date_str = row["date"]
                    if ticker not in prices_dict:
                        prices_dict[ticker] = {}
                    try:
                        # Merge/update with production data (may have newer dates)
                        prices_dict[ticker][date_str] = float(row["close"])
                    except (ValueError, TypeError):
                        pass

        xbi_after = len(prices_dict.get("XBI", {}))
        ibb_after = len(prices_dict.get("IBB", {}))
        logger.info(f"After production merge: XBI {xbi_before}→{xbi_after}, " f"IBB {ibb_before}→{ibb_after}")

    return prices_dict


def compute_forward_returns(
    panel: pd.DataFrame,
    market_data: dict,
) -> pd.DataFrame:
    """Join forward returns to panel using PIT-safe price history.

    Computes T+1, T+5, T+20 forward returns for each as_of_date.

    Returns:
        Panel with additional columns: forward_1d, forward_5d, forward_20d,
        max_drawdown_20d, realized_vol_20d (all nullable).
    """
    panel = panel.copy()
    panel["forward_1d"] = None
    panel["forward_5d"] = None
    panel["forward_20d"] = None
    panel["max_drawdown_20d"] = None
    panel["realized_vol_20d"] = None

    if not market_data:
        logger.warning("No market data available, skipping forward returns")
        return panel

    # Extract XBI prices (portfolio proxy)
    if "XBI" not in market_data:
        logger.warning("XBI not in market data, cannot compute forward returns")
        return panel

    # xbi_prices is a dict of {date_str: price}
    xbi_prices = market_data["XBI"]
    if not xbi_prices:
        logger.warning("XBI prices empty, cannot compute forward returns")
        return panel

    # Convert price keys to dates
    price_dates = {}
    for date_str, price in xbi_prices.items():
        try:
            price_dates[pd.to_datetime(date_str)] = float(price)
        except (ValueError, TypeError):
            continue

    sorted_dates = sorted(price_dates.keys())

    for idx, row in panel.iterrows():
        as_of_date = row["as_of_date"]

        if as_of_date not in price_dates:
            continue

        as_of_price = price_dates[as_of_date]

        # Find future dates for T+1, T+5, T+20
        future_dates = [d for d in sorted_dates if d > as_of_date]

        if len(future_dates) >= 1:
            t1_price = price_dates[future_dates[0]]
            panel.at[idx, "forward_1d"] = (t1_price - as_of_price) / as_of_price * 100

        if len(future_dates) >= 5:
            t5_price = price_dates[future_dates[4]]
            panel.at[idx, "forward_5d"] = (t5_price - as_of_price) / as_of_price * 100

        if len(future_dates) >= 20:
            t20_price = price_dates[future_dates[19]]
            panel.at[idx, "forward_20d"] = (t20_price - as_of_price) / as_of_price * 100

            # Max drawdown and realized vol over 20 days
            window_prices = [price_dates[d] for d in future_dates[:20]]
            min_val = min(window_prices)
            panel.at[idx, "max_drawdown_20d"] = (min_val - as_of_price) / as_of_price * 100

            # Realized vol: annualized std dev of daily returns
            returns = []
            for i in range(1, len(window_prices)):
                ret = (window_prices[i] - window_prices[i - 1]) / window_prices[i - 1]
                returns.append(ret)
            if returns:
                vol = pd.Series(returns).std() * (252**0.5) * 100  # Annualized %
                panel.at[idx, "realized_vol_20d"] = vol

    logger.info("Forward returns computed")
    return panel


def compute_verdict_accuracy(panel: pd.DataFrame) -> dict:
    """Compute verdict accuracy: % of rows where forward_5d hit positive target."""
    results = {}

    for verdict in panel["verdict"].unique():
        if pd.isna(verdict) or verdict == "":
            continue

        subset = panel[panel["verdict"] == verdict].copy()
        subset = subset.dropna(subset=["forward_5d"])

        if len(subset) == 0:
            results[verdict] = {
                "n": 0,
                "hit_pct": None,
                "median_5d": None,
                "median_20d": None,
            }
            continue

        hit = (subset["forward_5d"] >= 0).sum()
        hit_pct = hit / len(subset) * 100 if len(subset) > 0 else None

        results[verdict] = {
            "n": len(subset),
            "hit_pct": round(hit_pct, 1) if hit_pct is not None else None,
            "median_5d": round(subset["forward_5d"].median(), 2),
            "median_20d": round(subset["forward_20d"].median(), 2),
            "median_1d": round(subset["forward_1d"].median(), 2),
        }

    return results


def compute_confidence_correlation(panel: pd.DataFrame) -> dict:
    """Compute forward returns by confidence level."""
    results = {}

    for conf in panel["confidence"].unique():
        if pd.isna(conf) or conf == "":
            continue

        subset = panel[panel["confidence"] == conf].copy()
        subset = subset.dropna(subset=["forward_5d"])

        if len(subset) == 0:
            continue

        results[conf] = {
            "n": len(subset),
            "median_1d": round(subset["forward_1d"].median(), 2),
            "median_5d": round(subset["forward_5d"].median(), 2),
            "median_20d": round(subset["forward_20d"].median(), 2),
        }

    return results


def write_analysis_csv(panel: pd.DataFrame, output_csv: Path) -> None:
    """Write panel with forward returns to CSV."""
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # Format datetime back to string
    panel["as_of_date"] = panel["as_of_date"].dt.strftime("%Y-%m-%d")

    panel.to_csv(output_csv, index=False)
    logger.info(f"Wrote analysis panel to {output_csv}")


def write_analysis_report(
    panel: pd.DataFrame,
    verdict_stats: dict,
    confidence_stats: dict,
    output_json: Path,
) -> None:
    """Write descriptive analysis report."""
    output_json.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "schema": "bioshort_forward_analysis.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pseudo_pit_caveat": (
            "Features computed using current producer logic against historical snapshots. "
            "No promotion claims supported. Descriptive analysis only per Spec 092 §A6."
        ),
        "summary": {
            "total_rows": len(panel),
            "rows_with_forward_5d": len(panel.dropna(subset=["forward_5d"])),
            "rows_with_forward_20d": len(panel.dropna(subset=["forward_20d"])),
        },
        "by_verdict": verdict_stats,
        "by_confidence": confidence_stats,
        "forward_return_stats": {
            "forward_1d_median": round(panel["forward_1d"].median(), 2),
            "forward_5d_median": round(panel["forward_5d"].median(), 2),
            "forward_20d_median": round(panel["forward_20d"].median(), 2),
            "max_drawdown_20d_median": round(panel["max_drawdown_20d"].median(), 2),
            "realized_vol_20d_median": round(panel["realized_vol_20d"].median(), 2),
        },
    }

    with open(output_json, "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Wrote analysis report to {output_json}")


def main():
    """Run Phase D forward returns analysis."""
    logger.info("=== Spec 092 Phase D — Forward Returns Analysis ===")

    # Load panel
    panel = load_panel()

    # Load market data (PIT-safe)
    market_data = load_market_data()

    # Compute forward returns
    panel = compute_forward_returns(panel, market_data)

    # Compute descriptive statistics
    verdict_stats = compute_verdict_accuracy(panel)
    confidence_stats = compute_confidence_correlation(panel)

    # Write outputs
    ANALYSIS_PATH.mkdir(parents=True, exist_ok=True)
    write_analysis_csv(panel, ANALYSIS_PATH / "panel_with_returns.csv")
    write_analysis_report(
        panel,
        verdict_stats,
        confidence_stats,
        ANALYSIS_PATH / "forward_analysis_report.json",
    )

    logger.info("Phase D complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
