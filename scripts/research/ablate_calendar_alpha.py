#!/usr/bin/env python3
"""Calendar Alpha v2 single-component ablation tool.

Recomposes clinical_score_v2 from raw component scores already present
in snapshot rankings.csv, using a CalendarAlphaConfig with only one
component weight non-zero. Then re-z-scores and re-ranks through the
active decision engine ruleset.

This avoids re-running the full pipeline; all raw component data is
already materialized in snapshots by run_screen.py.

Usage:
    python scripts/research/ablate_calendar_alpha.py \
        --component execution_momentum \
        --snapshot-root data/snapshots \
        --out-root data/snapshots_ablation_execution_momentum \
        --dates manifests/catalyst_tilt_eval_dates.txt \
        --ruleset production_data/decision_rulesets/v1.11.0_b91_clinical_quality_w05_candidate.json
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_DIR / "scripts" / "research"))

from rerank_snapshots import rerank

from common.clinical_calendar_alpha import CalendarAlphaConfig, compose_clinical_score_v2, z_score_dict
from decision_engine import DecisionRuleset

# ---------------------------------------------------------------------------
# Component definitions
# ---------------------------------------------------------------------------

# Maps component name → (config field, CSV raw score column)
COMPONENTS = {
    "readout_curve": ("w_readout_curve", "readout_curve_score"),
    "readout_density": ("w_readout_density", "readout_density_90"),
    "execution_momentum": ("w_momentum", "execution_momentum"),
    "design_quality": ("w_design", "design_quality_score"),
    "endpoint_strength": ("w_endpoint", "endpoint_strength_score"),
    "competitive_intensity": ("w_competition", "competitive_intensity_z"),
}

# Weight to assign the sole active component (same total budget as default sum)
SOLO_WEIGHT = 0.60


def make_single_component_config(component: str) -> CalendarAlphaConfig:
    """Create a CalendarAlphaConfig with only one component active."""
    if component not in COMPONENTS:
        raise ValueError(f"Unknown component {component!r}. " f"Choose from: {', '.join(sorted(COMPONENTS))}")

    kwargs = {
        "w_readout_curve": 0.0,
        "w_readout_density": 0.0,
        "w_momentum": 0.0,
        "w_design": 0.0,
        "w_endpoint": 0.0,
        "w_competition": 0.0,
        "enable_sizing": False,
    }
    config_field = COMPONENTS[component][0]
    kwargs[config_field] = SOLO_WEIGHT
    return CalendarAlphaConfig(**kwargs)


# ---------------------------------------------------------------------------
# Recompose pipeline
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def recompose_snapshot(
    rows: List[Dict[str, str]],
    config: CalendarAlphaConfig,
) -> List[Dict[str, str]]:
    """Recompose clinical_score_v2 + z from raw component scores in rows.

    Modifies rows in-place and returns them.
    """
    # Step 1: Extract raw component scores per ticker
    ticker_scores: Dict[str, Dict[str, float]] = {}
    for row in rows:
        tk = row.get("ticker", "")
        if not tk:
            continue
        ticker_scores[tk] = {
            "readout_curve_score": _safe_float(row.get("readout_curve_score")),
            "readout_density_90": _safe_float(row.get("readout_density_90")),
            "execution_momentum": _safe_float(row.get("execution_momentum")),
            "design_quality_score": _safe_float(row.get("design_quality_score")),
            "endpoint_strength_score": _safe_float(row.get("endpoint_strength_score")),
            "competitive_intensity_z": _safe_float(row.get("competitive_intensity_z")),
            "clinical_score": _safe_float(row.get("clinical_score")),
        }

    # Step 2: Z-score each component cross-sectionally
    z_rc = z_score_dict({tk: s["readout_curve_score"] for tk, s in ticker_scores.items()})
    z_rd = z_score_dict({tk: s["readout_density_90"] for tk, s in ticker_scores.items()})
    z_mom = z_score_dict({tk: s["execution_momentum"] for tk, s in ticker_scores.items()})
    z_des = z_score_dict({tk: s["design_quality_score"] for tk, s in ticker_scores.items()})
    z_ep = z_score_dict({tk: s["endpoint_strength_score"] for tk, s in ticker_scores.items()})
    # competitive_intensity_z is already z-scored in the snapshot

    # Step 3: Recompose clinical_score_v2 for each ticker
    v2_scores: Dict[str, Optional[float]] = {}
    # Build ticker → row mapping for clinical_score presence check
    tk_row = {r.get("ticker", ""): r for r in rows}
    for tk, scores in ticker_scores.items():
        cs = scores["clinical_score"]
        raw_cs = tk_row.get(tk, {}).get("clinical_score", "")
        if cs == 0.0 and not raw_cs:
            v2_scores[tk] = None
            continue

        v2, _, _ = compose_clinical_score_v2(
            cs,
            scores,
            config,
            z_readout_curve=z_rc.get(tk, 0.0),
            z_readout_density=z_rd.get(tk, 0.0),
            z_momentum=z_mom.get(tk, 0.0),
            z_design=z_des.get(tk, 0.0),
            z_endpoint=z_ep.get(tk, 0.0),
            z_competition=scores["competitive_intensity_z"],
        )
        v2_scores[tk] = v2

    # Step 4: Z-score clinical_score_v2 cross-sectionally
    v2_for_z = {tk: v for tk, v in v2_scores.items() if v is not None}
    v2_z = z_score_dict(v2_for_z)

    # Step 5: Write back to rows
    for row in rows:
        tk = row.get("ticker", "")
        v2 = v2_scores.get(tk)
        row["clinical_score_v2"] = f"{v2:.4f}" if v2 is not None else ""
        row["clinical_score_v2_z"] = f"{v2_z.get(tk, 0.0):.6f}"

    return rows


def process_date(
    src_root: Path,
    dst_root: Path,
    date: str,
    config: CalendarAlphaConfig,
    ruleset: DecisionRuleset,
) -> bool:
    """Recompose + rerank one snapshot date. Returns True on success."""
    src_dir = src_root / date
    rankings_path = src_dir / "rankings.csv"
    if not rankings_path.exists():
        return False

    # Read
    with open(rankings_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return False

    # Recompose clinical_score_v2 with single-component weights
    rows = recompose_snapshot(rows, config)

    # Rerank through decision engine
    rows = rerank(rows, ruleset)

    # Write (use fieldnames from reranked rows — rerank may add columns)
    dst_dir = dst_root / date
    dst_dir.mkdir(parents=True, exist_ok=True)
    out_fieldnames = list(rows[0].keys()) if rows else []

    with open(dst_dir / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Copy metadata
    meta_src = src_dir / "metadata.json"
    if meta_src.exists():
        shutil.copy2(meta_src, dst_dir / "metadata.json")

    return True


def load_dates(path: Path) -> List[str]:
    """Load dates from a manifest file."""
    text = path.read_text().strip()
    return sorted(line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description="Recompose calendar alpha v2 with a single component, then rerank.",
    )
    p.add_argument("--component", required=True, choices=sorted(COMPONENTS.keys()))
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--dates", type=Path, required=True, help="Date manifest file")
    p.add_argument(
        "--ruleset",
        type=Path,
        default=PROJECT_DIR
        / "production_data"
        / "decision_rulesets"
        / "v1.11.0_b91_clinical_quality_w05_candidate.json",
    )
    args = p.parse_args(argv)

    config = make_single_component_config(args.component)
    config_field = COMPONENTS[args.component][0]
    print(f"Component: {args.component}")
    print(f"Config: {config_field}={SOLO_WEIGHT}, all others=0")

    ruleset = DecisionRuleset.from_json(str(args.ruleset))

    dates = load_dates(args.dates)
    print(f"Dates: {len(dates)} from {args.dates}")

    n_ok = 0
    n_skip = 0
    for d in dates:
        ok = process_date(args.snapshot_root, args.out_root, d, config, ruleset)
        if ok:
            n_ok += 1
        else:
            n_skip += 1
            print(f"  SKIP {d} (no rankings.csv)")

    print(f"\nDone: {n_ok} recomposed, {n_skip} skipped")
    print(f"Output: {args.out_root}")


if __name__ == "__main__":
    main()
