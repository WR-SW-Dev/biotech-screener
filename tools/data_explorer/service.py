"""Command dispatch — service layer for the Data Explorer.

Every public ``run_*`` function returns a response envelope (dict).

Artifact generation (reports, charts, manifests) is triggered by passing an
``out_dir`` parameter.  When ``out_dir`` is None the function does pure
computation with no file I/O beyond reading source data.  When provided,
artifacts are generated from the *already-computed* data — no re-loading,
no re-computation.

Both CLI (agent.py) and TUI (tui_app.py) call these functions directly.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from tools.data_explorer.catalog import catalog_summary, list_snapshot_dates
from tools.data_explorer.comparator import compare_snapshots
from tools.data_explorer.explorer import gate_counts, missingness, qa_checks, score_distributions, summarize, top_n
from tools.data_explorer.loader import load_file
from tools.data_explorer.reporter import comparison_report, qa_report, snapshot_report
from tools.data_explorer.schemas import envelope, qa_exit_code, qa_severity_summary

logger = logging.getLogger("data_explorer.service")


# ---------------------------------------------------------------------------
# Public loader (shared by CLI/TUI when they need the raw DataFrame)
# ---------------------------------------------------------------------------


def load_rankings(path_str: str) -> pd.DataFrame:
    """Load rankings.csv — accepts file path or snapshot directory."""
    path = Path(path_str)
    if path.is_dir():
        rankings_path = path / "rankings.csv"
        if rankings_path.exists():
            return load_file(rankings_path)
        raise FileNotFoundError(f"No rankings.csv in {path}")
    return load_file(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _snap_date(df: pd.DataFrame) -> str:
    return df.attrs.get("snapshot_date", "")


def _elapsed(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


def _try_charts_score(df, g, out_dir, title_prefix=""):
    """Generate score distribution + gate bar charts. Returns list of paths."""
    paths = []
    try:
        from tools.data_explorer.viz import plot_gate_bars, plot_score_distributions

        cp = plot_score_distributions(
            df,
            out_path=out_dir / "score_distributions.png",
            title_prefix=title_prefix,
        )
        if cp:
            paths.append(cp)
        gp = plot_gate_bars(g, out_path=out_dir / "gate_bars.png")
        if gp:
            paths.append(gp)
    except ImportError:
        logger.debug("matplotlib not available, skipping charts")
    return paths


def _try_charts_compare(df_a, df_b, overlap, n, out_dir):
    """Generate overlap + rank comparison charts. Returns list of paths."""
    paths = []
    try:
        from tools.data_explorer.viz import plot_overlap_chart, plot_rank_comparison

        op = plot_overlap_chart(overlap, out_path=out_dir / "overlap_chart.png")
        if op:
            paths.append(op)
        rp = plot_rank_comparison(df_a, df_b, n=n, out_path=out_dir / "rank_comparison.png")
        if rp:
            paths.append(rp)
    except ImportError:
        pass
    return paths


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def run_summary(
    path: str,
    *,
    verbose: bool = False,
    out_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Snapshot summary.  Pass ``out_dir`` to also write report + charts."""
    t0 = time.monotonic()

    df = load_rankings(path)
    s = summarize(df)
    m = missingness(df)
    g = gate_counts(df)
    t = top_n(df, n=10)
    qa = qa_checks(df)

    # Artifacts (optional)
    chart_paths: List[Path] = []
    report_path = None
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        chart_paths = _try_charts_score(df, g, out_dir)
        report_md = snapshot_report(s, m, g, t, qa, chart_paths)
        report_path = out_dir / "snapshot_summary.md"
        report_path.write_text(report_md, encoding="utf-8")

    data = {
        "rows": s["n_rows"],
        "columns": s["n_columns"],
        "source": s["source_path"],
        "score_stats": s.get("score_stats", {}),
        "key_scores_present": s.get("key_scores_present", []),
        "key_ranks_present": s.get("key_ranks_present", []),
        "gates": g,
        "top_10": t.to_dict("records") if not t.empty else [],
        "missingness": {
            "fully_missing": [c["column"] for c in m.get("fully_missing", [])],
            "top_10_missing": m.get("top_10_missing", []),
        },
        "qa": {
            "n_issues": qa["n_issues"],
            "severity_summary": qa_severity_summary(qa["issues"]),
            "issues": qa["issues"],
        },
    }
    if report_path:
        data["report_path"] = str(report_path)
    if chart_paths:
        data["chart_paths"] = [str(p) for p in chart_paths]

    return envelope(
        "summary",
        data,
        path=path,
        snapshot_date=_snap_date(df),
        elapsed_ms=_elapsed(t0),
    )


def run_compare(
    path_a: str,
    path_b: str,
    *,
    n: int = 30,
    verbose: bool = False,
    out_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Compare two snapshots.  Pass ``out_dir`` for report + charts."""
    t0 = time.monotonic()

    df_a = load_rankings(path_a)
    df_b = load_rankings(path_b)
    comp = compare_snapshots(df_a, df_b, n=n)
    overlap = comp["overlap"]

    # Artifacts (optional)
    chart_paths: List[Path] = []
    report_path = None
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        report_md = comparison_report(comp)
        report_path = out_dir / "comparison_report.md"
        report_path.write_text(report_md, encoding="utf-8")
        chart_paths = _try_charts_compare(df_a, df_b, overlap, n, out_dir)

    data = {
        "snapshot_a": comp["date_a"],
        "snapshot_b": comp["date_b"],
        "n_rows_a": comp["n_rows_a"],
        "n_rows_b": comp["n_rows_b"],
        "top_n": n,
        "overlap_count": overlap["overlap_count"],
        "overlap_pct": overlap["overlap_pct"],
        "added": overlap["added"],
        "removed": overlap["removed"],
        "n_added": overlap["n_added"],
        "n_removed": overlap["n_removed"],
        "largest_rank_changes": [
            {
                "ticker": d["ticker"],
                "max_abs_delta": d["max_abs_delta"],
                "deltas": d["deltas"],
            }
            for d in comp.get("top_drift", [])[:15]
        ],
        "schema": comp.get("schema", {}),
    }
    if report_path:
        data["report_path"] = str(report_path)
    if chart_paths:
        data["chart_paths"] = [str(p) for p in chart_paths]

    return envelope(
        "compare",
        data,
        path=path_a,
        snapshot_date=comp["date_b"],
        elapsed_ms=_elapsed(t0),
    )


def run_qa(
    path: str,
    *,
    verbose: bool = False,
    out_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Run QA checks.  Pass ``out_dir`` for a QA report file."""
    t0 = time.monotonic()

    df = load_rankings(path)
    qa = qa_checks(df)
    issues = qa["issues"]
    exit_code = qa_exit_code(issues)

    # Artifacts (optional)
    report_path = None
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        report_md = qa_report(qa)
        report_path = out_dir / "qa_report.md"
        report_path.write_text(report_md, encoding="utf-8")

    data = {
        "rows": qa["n_rows"],
        "columns": qa["n_columns"],
        "n_issues": qa["n_issues"],
        "severity_summary": qa_severity_summary(issues),
        "exit_code": exit_code,
        "issues": issues,
    }
    if report_path:
        data["report_path"] = str(report_path)

    return envelope(
        "qa",
        data,
        ok=(exit_code < 2),
        path=path,
        snapshot_date=_snap_date(df),
        elapsed_ms=_elapsed(t0),
    )


def run_catalog(path: str) -> Dict[str, Any]:
    """List artifacts in a snapshot directory."""
    t0 = time.monotonic()

    cat = catalog_summary(path)

    artifacts_list = []
    for name, info in cat.get("artifacts", {}).items():
        artifacts_list.append(
            {
                "name": name,
                "category": info["category"],
                "description": info["description"],
                "size_bytes": info["size_bytes"],
                "path": info["path"],
                "extension": info["extension"],
            }
        )

    data = {
        "snapshot_dir": cat["snapshot_dir"],
        "artifact_count": cat["n_artifacts"],
        "by_category": cat["by_category"],
        "has_rankings": cat.get("has_rankings", False),
        "has_ees": cat.get("has_ees", False),
        "has_expression": cat.get("has_expression", False),
        "has_options": cat.get("has_options", False),
        "artifacts": artifacts_list,
    }

    return envelope(
        "catalog",
        data,
        path=path,
        snapshot_date=cat.get("snapshot_date", ""),
        elapsed_ms=_elapsed(t0),
        data_source="snapshot directory",
    )


def run_field(path: str, field: str) -> Dict[str, Any]:
    """Stats for a single column."""
    t0 = time.monotonic()

    df = load_rankings(path)

    if field not in df.columns:
        available = sorted(df.columns)[:30]
        return envelope(
            "field",
            {"field": field, "available_columns": available},
            ok=False,
            path=path,
            snapshot_date=_snap_date(df),
            errors=[f"Column '{field}' not found. Available: {', '.join(available[:20])}..."],
            elapsed_ms=_elapsed(t0),
        )

    dist = score_distributions(df, columns=[field])
    stats = dist.get(field, {})

    # Value counts
    vals = df[field].value_counts().head(20)
    value_counts = [{"value": str(v), "count": int(c)} for v, c in vals.items()]

    # Top/bottom for numeric
    num = pd.to_numeric(df[field], errors="coerce").dropna()
    top_values = []
    bottom_values = []
    if len(num) > 0 and "ticker" in df.columns:
        df_num = df.loc[num.index].copy()
        df_num["_num"] = num
        top5 = df_num.nlargest(5, "_num")
        bottom5 = df_num.nsmallest(5, "_num")
        top_values = [{"ticker": r["ticker"], "value": float(r["_num"])} for _, r in top5.iterrows()]
        bottom_values = [{"ticker": r["ticker"], "value": float(r["_num"])} for _, r in bottom5.iterrows()]

    # Missing / zero stats
    n_total = len(df)
    n_missing = int(df[field].isna().sum() + (df[field].astype(str).str.strip() == "").sum())
    n_zero = int((num == 0).sum()) if len(num) > 0 else 0

    data = {
        "field": field,
        "count": int(stats.get("count", len(num))),
        "missing_count": n_missing,
        "missing_pct": round(n_missing / n_total * 100, 1) if n_total else 0,
        "zero_count": n_zero,
        "zero_pct": round(n_zero / max(len(num), 1) * 100, 1),
        "unique_count": int(df[field].nunique()),
        **{k: v for k, v in stats.items() if k != "count"},
        "top_values": top_values,
        "bottom_values": bottom_values,
        "value_counts": value_counts,
    }

    return envelope(
        "field",
        data,
        path=path,
        snapshot_date=_snap_date(df),
        elapsed_ms=_elapsed(t0),
    )


def run_top_n(path: str, *, n: int = 30) -> Dict[str, Any]:
    """Top-N ranked names."""
    t0 = time.monotonic()

    df = load_rankings(path)
    t = top_n(df, n=n)

    data = {
        "n": n,
        "rows": t.to_dict("records") if not t.empty else [],
    }

    return envelope(
        "top-n",
        data,
        path=path,
        snapshot_date=_snap_date(df),
        elapsed_ms=_elapsed(t0),
    )


def run_daily(
    path: str,
    *,
    verbose: bool = False,
    out_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Full daily report: summary + compare + qa + catalog.

    Pass ``out_dir`` to generate daily_report.md, charts, and
    daily_manifest.json — all from the same single computation.
    """
    t0 = time.monotonic()

    snap_dir = Path(path)
    if not snap_dir.is_dir():
        return envelope(
            "daily", {}, ok=False, path=path, errors=[f"{snap_dir} is not a directory"], elapsed_ms=_elapsed(t0)
        )

    # ---- Load + compute ONCE ----
    df = load_rankings(str(snap_dir))
    s = summarize(df)
    m = missingness(df)
    g = gate_counts(df)
    t = top_n(df, n=30)
    qa = qa_checks(df)
    qa_issues = qa["issues"]
    qa_ec = qa_exit_code(qa_issues)

    cat = catalog_summary(snap_dir)

    # Prior snapshot comparison
    snapshots_dir = snap_dir.parent
    dates = list_snapshot_dates(snapshots_dir)
    current_date = snap_dir.name[:10]
    prior_dates = [d for d in dates if d < current_date]

    comp = None
    prior_date = None
    df_prior = None
    if prior_dates:
        prior_dir = snapshots_dir / prior_dates[0]
        prior_path = prior_dir / "rankings.csv"
        if prior_path.exists():
            prior_date = prior_dates[0]
            df_prior = load_file(prior_path)
            comp = compare_snapshots(df_prior, df, n=30)

    # ---- Artifacts (optional, from already-computed data) ----
    chart_paths: List[Path] = []
    report_path = None
    manifest_path = None

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Charts from raw DataFrames
        chart_paths = _try_charts_score(
            df,
            g,
            out_dir,
            title_prefix=f"{s.get('snapshot_date', '')} ",
        )
        if comp and df_prior is not None:
            chart_paths.extend(_try_charts_compare(df_prior, df, comp["overlap"], 30, out_dir))

        # Report from already-computed intermediates
        report = snapshot_report(s, m, g, t, qa, chart_paths)
        if comp:
            report += "\n---\n\n" + comparison_report(comp)

        # Catalog section
        report += "\n---\n\n## Artifact Catalog\n\n"
        for category, files in cat["by_category"].items():
            report += f"### {category.upper()}\n"
            for f in files:
                info = cat["artifacts"][f]
                report += f"- `{f}` ({info['size_bytes'] / 1024:.1f} KB) — {info['description']}\n"
            report += "\n"

        report_path = out_dir / "daily_report.md"
        report_path.write_text(report, encoding="utf-8")

    # ---- Build envelope ----
    overlap_data = None
    if comp:
        overlap = comp["overlap"]
        overlap_data = {
            "overlap_count": overlap["overlap_count"],
            "overlap_pct": overlap["overlap_pct"],
            "added": overlap["added"],
            "removed": overlap["removed"],
            "n_added": overlap["n_added"],
            "n_removed": overlap["n_removed"],
            "largest_rank_changes": [
                {
                    "ticker": d["ticker"],
                    "max_abs_delta": d["max_abs_delta"],
                    "deltas": d["deltas"],
                }
                for d in comp.get("top_drift", [])[:15]
            ],
        }

    data = {
        "snapshot_date": current_date,
        "prior_snapshot_date": prior_date,
        "summary": {
            "rows": s["n_rows"],
            "columns": s["n_columns"],
            "source": s["source_path"],
            "score_stats": s.get("score_stats", {}),
        },
        "qa": {
            "n_issues": qa["n_issues"],
            "severity_summary": qa_severity_summary(qa_issues),
            "exit_code": qa_ec,
            "issues": qa_issues,
        },
        "compare": overlap_data,
        "catalog": {
            "artifact_count": cat["n_artifacts"],
            "by_category": cat["by_category"],
            "has_expression": cat.get("has_expression", False),
        },
    }
    if report_path:
        data["report_path"] = str(report_path)
    if chart_paths:
        data["chart_paths"] = [str(p) for p in chart_paths]

    resp = envelope(
        "daily",
        data,
        path=path,
        snapshot_date=current_date,
        elapsed_ms=_elapsed(t0),
    )

    # ---- Manifest (optional, after envelope is built) ----
    if out_dir is not None:
        manifest = build_daily_manifest(
            resp,
            report_path=str(report_path) if report_path else None,
            chart_paths=[str(p) for p in chart_paths],
        )
        manifest_path = out_dir / "daily_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        resp["data"]["manifest_path"] = str(manifest_path)

    return resp


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------


def build_daily_manifest(
    daily_resp: Dict[str, Any],
    *,
    report_path: Optional[str] = None,
    chart_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a daily_manifest.json dict from a daily response envelope."""
    data = daily_resp.get("data", daily_resp)
    qa = data.get("qa", {})
    compare = data.get("compare", {})

    return {
        "snapshot_date": data.get("snapshot_date", ""),
        "prior_date": data.get("prior_snapshot_date"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_30_overlap": compare.get("overlap_pct") if compare else None,
        "added": compare.get("added", []) if compare else [],
        "removed": compare.get("removed", []) if compare else [],
        "qa_summary": qa.get("severity_summary", {}),
        "qa_exit_code": qa.get("exit_code", 0),
        "n_issues": qa.get("n_issues", 0),
        "report_path": report_path,
        "chart_paths": chart_paths or [],
        "artifact_count": data.get("catalog", {}).get("artifact_count", 0),
    }
