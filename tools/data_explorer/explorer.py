"""Dataset explorer — summary stats, distributions, missingness, correlations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

# Key score columns for the biotech screener
KEY_SCORE_COLUMNS = [
    "selector_score",
    "final_score",
    "ranker_v2_score",
    "coinvest_score_z",
    "inst_delta_z",
    "financial_score",
    "clinical_score_v2_z",
    "trap_overlay_score",
    "quality_overlay_score",
    "ees_v2_score",
]

KEY_RANK_COLUMNS = [
    "ranker_v2_rank",
    "actionable_rank",
]

GATE_COLUMNS = [
    "ees_eligible",
    "opt_liquidity_state",
]


def _to_numeric(series: pd.Series) -> pd.Series:
    """Convert series to numeric, coercing errors to NaN."""
    return pd.to_numeric(series, errors="coerce")


def summarize(df: pd.DataFrame) -> Dict[str, Any]:
    """Generate a summary of a DataFrame.

    Returns row count, column count, key columns present, and basic stats.
    """
    present_scores = [c for c in KEY_SCORE_COLUMNS if c in df.columns]
    present_ranks = [c for c in KEY_RANK_COLUMNS if c in df.columns]

    stats = {}
    for col in present_scores:
        num = _to_numeric(df[col])
        valid = num.dropna()
        if len(valid) > 0:
            stats[col] = {
                "count": len(valid),
                "mean": round(valid.mean(), 4),
                "std": round(valid.std(), 4),
                "min": round(valid.min(), 4),
                "p25": round(valid.quantile(0.25), 4),
                "median": round(valid.median(), 4),
                "p75": round(valid.quantile(0.75), 4),
                "max": round(valid.max(), 4),
            }

    return {
        "n_rows": len(df),
        "n_columns": len(df.columns),
        "source_path": df.attrs.get("source_path", ""),
        "snapshot_date": df.attrs.get("snapshot_date", ""),
        "key_scores_present": present_scores,
        "key_ranks_present": present_ranks,
        "score_stats": stats,
    }


def missingness(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute missingness statistics for all columns.

    Returns columns sorted by missing percentage (descending).
    """
    n = len(df)
    if n == 0:
        return {"n_rows": 0, "columns": []}

    cols = []
    for col in df.columns:
        # Count empty strings and actual NaN as missing
        missing = df[col].isna() | (df[col].astype(str).str.strip() == "")
        n_missing = int(missing.sum())
        cols.append(
            {
                "column": col,
                "n_missing": n_missing,
                "pct_missing": round(n_missing / n * 100, 1),
            }
        )

    cols.sort(key=lambda x: -x["pct_missing"])
    return {
        "n_rows": n,
        "n_columns": len(df.columns),
        "columns": cols,
        "fully_missing": [c for c in cols if c["pct_missing"] == 100.0],
        "top_10_missing": cols[:10],
    }


def score_distributions(
    df: pd.DataFrame,
    columns: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Compute distribution statistics for numeric score columns."""
    if columns is None:
        columns = [c for c in KEY_SCORE_COLUMNS if c in df.columns]

    result = {}
    for col in columns:
        if col not in df.columns:
            continue
        num = _to_numeric(df[col])
        valid = num.dropna()
        if len(valid) == 0:
            result[col] = {"count": 0}
            continue
        result[col] = {
            "count": len(valid),
            "mean": round(valid.mean(), 4),
            "std": round(valid.std(), 4),
            "min": round(valid.min(), 4),
            "p5": round(valid.quantile(0.05), 4),
            "p25": round(valid.quantile(0.25), 4),
            "median": round(valid.median(), 4),
            "p75": round(valid.quantile(0.75), 4),
            "p95": round(valid.quantile(0.95), 4),
            "max": round(valid.max(), 4),
            "n_zero": int((valid == 0).sum()),
            "n_negative": int((valid < 0).sum()),
        }
    return result


def gate_counts(df: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """Count pass/fail for gate columns."""
    result = {}

    if "ees_eligible" in df.columns:
        eligible = df["ees_eligible"].astype(str).str.strip().str.lower()
        result["ees_eligible"] = {
            "pass": int((eligible == "true").sum()),
            "fail": int((eligible == "false").sum()),
            "unknown": int(~eligible.isin(["true", "false"]).sum()),
        }

    if "ineligible_reasons" in df.columns:
        has_reasons = df["ineligible_reasons"].astype(str).str.strip() != ""
        result["ineligible_reasons"] = {
            "has_reasons": int(has_reasons.sum()),
            "no_reasons": int((~has_reasons).sum()),
        }

    if "opt_liquidity_state" in df.columns:
        liq = df["opt_liquidity_state"].astype(str).str.strip().str.lower()
        result["opt_liquidity_state"] = {
            "liquid": int((liq == "liquid").sum()),
            "illiquid": int((liq != "liquid").sum()),
        }

    return result


def top_n(
    df: pd.DataFrame,
    rank_col: str = "ranker_v2_rank",
    n: int = 30,
    display_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Return the top-N names by a rank column.

    Returns a DataFrame with selected display columns.
    """
    if rank_col not in df.columns:
        return pd.DataFrame()

    ranked = df[_to_numeric(df[rank_col]).notna()].copy()
    ranked[rank_col] = _to_numeric(ranked[rank_col])
    ranked = ranked.sort_values(rank_col).head(n)

    if display_cols is None:
        display_cols = ["ticker", rank_col]
        for c in ["ranker_v2_score", "selector_score", "coinvest_score_z", "financial_score"]:
            if c in ranked.columns:
                display_cols.append(c)

    available = [c for c in display_cols if c in ranked.columns]
    return ranked[available].reset_index(drop=True)


def correlations(
    df: pd.DataFrame,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Compute pairwise correlations between numeric score columns."""
    if columns is None:
        columns = [c for c in KEY_SCORE_COLUMNS if c in df.columns]

    numeric_df = df[columns].apply(_to_numeric)
    return numeric_df.corr().round(4)


def qa_checks(df: pd.DataFrame) -> Dict[str, Any]:
    """Run QA checks on a rankings DataFrame.

    Returns issues found: duplicates, missing key columns, suspicious values.
    """
    issues: List[Dict[str, str]] = []

    # Duplicate tickers
    if "ticker" in df.columns:
        dupes = df["ticker"].value_counts()
        dupes = dupes[dupes > 1]
        if len(dupes) > 0:
            issues.append(
                {
                    "check": "duplicate_tickers",
                    "severity": "error",
                    "detail": f"{len(dupes)} duplicated: {', '.join(dupes.index[:10])}",
                }
            )

    # Missing key columns
    required = ["ticker", "selector_score", "final_score"]
    for col in required:
        if col not in df.columns:
            issues.append(
                {
                    "check": "missing_key_column",
                    "severity": "error",
                    "detail": f"Column '{col}' not found",
                }
            )

    # Constant columns (suspicious)
    for col in df.columns:
        if df[col].nunique() <= 1 and len(df) > 10:
            issues.append(
                {
                    "check": "constant_column",
                    "severity": "warning",
                    "detail": f"Column '{col}' has only {df[col].nunique()} unique value(s)",
                }
            )

    # Extreme outliers in score columns
    for col in KEY_SCORE_COLUMNS:
        if col not in df.columns:
            continue
        num = _to_numeric(df[col]).dropna()
        if len(num) < 10:
            continue
        q1 = num.quantile(0.25)
        q3 = num.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        outliers = num[(num < q1 - 3 * iqr) | (num > q3 + 3 * iqr)]
        if len(outliers) > 0:
            issues.append(
                {
                    "check": "extreme_outlier",
                    "severity": "info",
                    "detail": f"Column '{col}': {len(outliers)} values beyond 3×IQR",
                }
            )

    return {
        "n_issues": len(issues),
        "issues": issues,
        "n_rows": len(df),
        "n_columns": len(df.columns),
    }
