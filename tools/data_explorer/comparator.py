"""Snapshot comparator — overlap, drift, schema diff, added/removed analysis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

import pandas as pd

from tools.data_explorer.explorer import KEY_SCORE_COLUMNS, _to_numeric


def top_n_overlap(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    n: int = 30,
    rank_col: str = "ranker_v2_rank",
) -> Dict[str, Any]:
    """Compute top-N overlap between two snapshots.

    Returns overlap count, added names, removed names.
    """

    def _top_n_set(df: pd.DataFrame) -> Set[str]:
        if rank_col not in df.columns or "ticker" not in df.columns:
            return set()
        ranked = df[_to_numeric(df[rank_col]).notna()].copy()
        ranked["_rk"] = _to_numeric(ranked[rank_col])
        ranked = ranked.sort_values("_rk").head(n)
        return set(ranked["ticker"])

    set_a = _top_n_set(df_a)
    set_b = _top_n_set(df_b)

    overlap = set_a & set_b
    added = set_b - set_a  # in B but not A (new)
    removed = set_a - set_b  # in A but not B (dropped)

    return {
        "n": n,
        "rank_col": rank_col,
        "n_a": len(set_a),
        "n_b": len(set_b),
        "overlap_count": len(overlap),
        "overlap_pct": round(len(overlap) / max(n, 1) * 100, 1),
        "overlap_names": sorted(overlap),
        "added": sorted(added),
        "removed": sorted(removed),
        "n_added": len(added),
        "n_removed": len(removed),
    }


def score_drift(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    columns: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Compute score changes for tickers present in both snapshots.

    Returns per-ticker score deltas, sorted by largest absolute change.
    """
    if columns is None:
        columns = [c for c in KEY_SCORE_COLUMNS if c in df_a.columns and c in df_b.columns]

    if "ticker" not in df_a.columns or "ticker" not in df_b.columns:
        return []

    merged = pd.merge(
        df_a[["ticker"] + [c for c in columns if c in df_a.columns]],
        df_b[["ticker"] + [c for c in columns if c in df_b.columns]],
        on="ticker",
        suffixes=("_a", "_b"),
        how="inner",
    )

    drifts = []
    for _, row in merged.iterrows():
        ticker = row["ticker"]
        deltas = {}
        max_abs_delta = 0.0
        for col in columns:
            a_col = f"{col}_a"
            b_col = f"{col}_b"
            if a_col in row.index and b_col in row.index:
                va = pd.to_numeric(row[a_col], errors="coerce")
                vb = pd.to_numeric(row[b_col], errors="coerce")
                if pd.notna(va) and pd.notna(vb):
                    delta = round(float(vb - va), 4)
                    deltas[col] = {
                        "before": round(float(va), 4),
                        "after": round(float(vb), 4),
                        "delta": delta,
                    }
                    max_abs_delta = max(max_abs_delta, abs(delta))
        if deltas:
            drifts.append(
                {
                    "ticker": ticker,
                    "max_abs_delta": max_abs_delta,
                    "deltas": deltas,
                }
            )

    drifts.sort(key=lambda x: -x["max_abs_delta"])
    return drifts


def schema_diff(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
) -> Dict[str, Any]:
    """Compare column schemas between two DataFrames."""
    cols_a = set(df_a.columns)
    cols_b = set(df_b.columns)

    return {
        "n_columns_a": len(cols_a),
        "n_columns_b": len(cols_b),
        "common": sorted(cols_a & cols_b),
        "only_in_a": sorted(cols_a - cols_b),
        "only_in_b": sorted(cols_b - cols_a),
        "n_common": len(cols_a & cols_b),
        "n_only_a": len(cols_a - cols_b),
        "n_only_b": len(cols_b - cols_a),
    }


def compare_snapshots(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    n: int = 30,
    rank_col: str = "ranker_v2_rank",
    score_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Full snapshot comparison: overlap, drift, schema diff."""
    overlap = top_n_overlap(df_a, df_b, n=n, rank_col=rank_col)
    drift = score_drift(df_a, df_b, columns=score_columns)
    schema = schema_diff(df_a, df_b)

    date_a = df_a.attrs.get("snapshot_date", "unknown")
    date_b = df_b.attrs.get("snapshot_date", "unknown")

    return {
        "date_a": date_a,
        "date_b": date_b,
        "path_a": df_a.attrs.get("source_path", ""),
        "path_b": df_b.attrs.get("source_path", ""),
        "n_rows_a": len(df_a),
        "n_rows_b": len(df_b),
        "overlap": overlap,
        "top_drift": drift[:20],
        "schema": schema,
    }
