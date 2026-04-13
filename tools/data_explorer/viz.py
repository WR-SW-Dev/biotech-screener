"""Visualization — simple, readable charts for operator reports."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Lazy import matplotlib to avoid import-time failures
_plt = None
_HAS_MPL = None


def _get_plt():
    global _plt, _HAS_MPL
    if _HAS_MPL is None:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            _plt = plt
            _HAS_MPL = True
        except ImportError:
            _HAS_MPL = False
    if not _HAS_MPL:
        raise ImportError("matplotlib is required for visualization")
    return _plt


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def plot_score_distributions(
    df: pd.DataFrame,
    columns: Optional[List[str]] = None,
    out_path: Optional[Path] = None,
    title_prefix: str = "",
) -> Optional[Path]:
    """Plot histograms of key score columns."""
    plt = _get_plt()

    if columns is None:
        from tools.data_explorer.explorer import KEY_SCORE_COLUMNS

        columns = [c for c in KEY_SCORE_COLUMNS if c in df.columns]

    if not columns:
        logger.warning("No score columns to plot")
        return None

    n_cols = min(len(columns), 3)
    n_rows = (len(columns) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 3.5 * n_rows))
    if n_rows * n_cols == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    for i, col in enumerate(columns):
        ax = axes[i]
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(vals) == 0:
            ax.set_title(f"{col} (no data)")
            continue
        ax.hist(vals, bins=30, color="#4a86c8", alpha=0.8, edgecolor="white")
        ax.set_title(col, fontsize=10)
        ax.set_xlabel("")
        ax.axvline(vals.median(), color="red", linestyle="--", linewidth=1, label=f"med={vals.median():.3f}")
        ax.legend(fontsize=7)

    for i in range(len(columns), len(axes)):
        axes[i].set_visible(False)

    title = f"{title_prefix}Score Distributions" if title_prefix else "Score Distributions"
    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()

    if out_path is None:
        out_path = Path("reports/data_explorer/score_distributions.png")
    _ensure_dir(out_path)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_gate_bars(
    gate_data: Dict[str, Dict[str, int]],
    out_path: Optional[Path] = None,
    title: str = "Gate Pass/Fail Counts",
) -> Optional[Path]:
    """Plot bar chart of gate pass/fail counts."""
    plt = _get_plt()

    if not gate_data:
        return None

    fig, ax = plt.subplots(figsize=(8, max(3, len(gate_data) * 0.8)))

    gates = list(gate_data.keys())
    pass_counts = []
    fail_counts = []
    for gate in gates:
        d = gate_data[gate]
        # Normalize: first value is "pass", rest is "fail"
        vals = list(d.values())
        pass_counts.append(vals[0] if vals else 0)
        fail_counts.append(sum(vals[1:]) if len(vals) > 1 else 0)

    y_pos = range(len(gates))
    ax.barh(y_pos, pass_counts, color="#4caf50", label="Pass", height=0.4, align="edge")
    ax.barh([y + 0.4 for y in y_pos], fail_counts, color="#f44336", label="Fail", height=0.4, align="edge")
    ax.set_yticks([y + 0.4 for y in y_pos])
    ax.set_yticklabels(gates)
    ax.set_xlabel("Count")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()

    if out_path is None:
        out_path = Path("reports/data_explorer/gate_bars.png")
    _ensure_dir(out_path)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_overlap_chart(
    overlap_data: Dict[str, Any],
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    """Plot a simple overlap / added / removed chart."""
    plt = _get_plt()

    fig, ax = plt.subplots(figsize=(6, 4))

    labels = ["Overlap", "Added", "Removed"]
    values = [
        overlap_data.get("overlap_count", 0),
        overlap_data.get("n_added", 0),
        overlap_data.get("n_removed", 0),
    ]
    colors = ["#4caf50", "#2196f3", "#f44336"]
    bars = ax.bar(labels, values, color=colors, edgecolor="white")

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            str(val),
            ha="center",
            fontsize=11,
        )

    n = overlap_data.get("n", 30)
    ax.set_title(f"Top-{n} Overlap Analysis")
    ax.set_ylabel("Count")
    fig.tight_layout()

    if out_path is None:
        out_path = Path("reports/data_explorer/overlap_chart.png")
    _ensure_dir(out_path)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_rank_comparison(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    n: int = 30,
    rank_col: str = "ranker_v2_rank",
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    """Plot rank changes between two snapshots (bump chart style)."""
    plt = _get_plt()

    if rank_col not in df_a.columns or rank_col not in df_b.columns:
        return None
    if "ticker" not in df_a.columns or "ticker" not in df_b.columns:
        return None

    # Get top-N from each
    def _get_ranked(df: pd.DataFrame) -> pd.DataFrame:
        ranked = df[pd.to_numeric(df[rank_col], errors="coerce").notna()].copy()
        ranked["_rk"] = pd.to_numeric(ranked[rank_col])
        return ranked.sort_values("_rk").head(n)[["ticker", "_rk"]]

    ra = _get_ranked(df_a).rename(columns={"_rk": "rank_a"})
    rb = _get_ranked(df_b).rename(columns={"_rk": "rank_b"})

    merged = pd.merge(ra, rb, on="ticker", how="outer")
    merged = merged.sort_values("rank_b", na_position="last")

    fig, ax = plt.subplots(figsize=(6, max(6, n * 0.25)))

    for _, row in merged.iterrows():
        ra_val = row.get("rank_a")
        rb_val = row.get("rank_b")
        tk = row["ticker"]

        if pd.notna(ra_val) and pd.notna(rb_val):
            color = "#4caf50" if rb_val < ra_val else ("#f44336" if rb_val > ra_val else "#888")
            ax.plot([0, 1], [ra_val, rb_val], color=color, alpha=0.6, linewidth=1.5)
            ax.text(-0.05, ra_val, tk, ha="right", fontsize=7, va="center")
            ax.text(1.05, rb_val, tk, ha="left", fontsize=7, va="center")
        elif pd.notna(rb_val):
            ax.text(1.05, rb_val, f"{tk} (new)", ha="left", fontsize=7, va="center", color="#2196f3")
            ax.plot(1, rb_val, "o", color="#2196f3", markersize=4)
        elif pd.notna(ra_val):
            ax.text(-0.05, ra_val, f"{tk} (dropped)", ha="right", fontsize=7, va="center", color="#f44336")
            ax.plot(0, ra_val, "o", color="#f44336", markersize=4)

    ax.set_xlim(-0.3, 1.3)
    ax.set_ylim(n + 1, 0)
    ax.set_xticks([0, 1])
    date_a = df_a.attrs.get("snapshot_date", "A")
    date_b = df_b.attrs.get("snapshot_date", "B")
    ax.set_xticklabels([date_a, date_b])
    ax.set_ylabel("Rank")
    ax.set_title(f"Top-{n} Rank Changes")
    fig.tight_layout()

    if out_path is None:
        out_path = Path("reports/data_explorer/rank_comparison.png")
    _ensure_dir(out_path)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path
