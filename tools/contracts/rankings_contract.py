#!/usr/bin/env python3
"""Value-level data contract for rankings.csv and July 8 IC-gate inputs.

This is a *value-level* contract: it validates the actual contents of a
rankings.csv (nulls, positivity, cohort size, duplicates, forward-pair
sufficiency, price freshness/variance). Column-set / schema-drift ownership
stays with tests/test_contract_output_schemas.py (authoritative SNAPSHOT_COLUMNS)
— this module deliberately does NOT re-validate the column list.

Plain pandas + pytest only; no new dependency, no schema library. Pure
validators return structured results and never raise on data issues — the
caller (pytest or the read-only CLI preflight) decides hard-fail vs warn.

CLI preflight (writes nothing):

    python3 tools/contracts/rankings_contract.py \\
      --base data/snapshots/2026-06-18 \\
      --forward data/snapshots/2026-07-08 \\
      --expect-cohort 60 \\
      --gate-fields final_score catalyst_decay_w catalyst_score coinvest_score_z financial_score

Exit codes:
    0  PASS (warnings allowed)
    2  hard contract FAILURE (schema/cohort violations)
    3  UNOBSERVABLE (missing/insufficient forward data — gate cannot run;
       NOT represented as a measured zero)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Defaults (cohort + gate parameters mirror the Spec 100 IC tool)
# ---------------------------------------------------------------------------

COHORT_RANK_MAX = 60
DEFAULT_EXPECT_COHORT = 60
MIN_IC_PAIRS = 5  # matches _spearman_ic minimum in measure_final_score_ic_spec100.py
DEFAULT_GATE_FIELDS = [
    "final_score",
    "composite_score",
    "close_price",
    "catalyst_decay_w",
    "catalyst_score",
    "coinvest_score_z",
    "financial_score",
]
DEFAULT_ZERO_RETURN_WARN_FRAC = 0.5
DEFAULT_FALLBACK_TOLERANCE_DAYS = 7
_EPS = 1e-12


@dataclass
class ContractResult:
    status: str  # "PASS" | "FAIL" | "UNOBSERVABLE"
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    observed_forward_date: Optional[str] = None
    requested_forward_date: Optional[str] = None
    forward_pairs: int = 0
    unobservable_reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def load_rankings(path) -> pd.DataFrame:
    """Load a rankings.csv as all-strings (per-check numeric coercion).

    `path` may be a snapshot directory (……/<date>/) or a direct csv path.
    """
    p = Path(path)
    csv_path = p / "rankings.csv" if p.is_dir() else p
    return pd.read_csv(csv_path, dtype=str, keep_default_na=False)


def cohort_frame(df: pd.DataFrame, rank_max: int = COHORT_RANK_MAX) -> pd.DataFrame:
    if "actionable_rank" not in df.columns:
        return df.iloc[0:0]
    r = _numeric(df["actionable_rank"])
    return df[r.notna() & (r <= rank_max)]


# ---------------------------------------------------------------------------
# Validators (pure)
# ---------------------------------------------------------------------------


def validate_rankings_schema(df: pd.DataFrame, gate_fields: List[str] = DEFAULT_GATE_FIELDS) -> List[str]:
    """Base required-field + identity checks (value-level, not column-set drift)."""
    v: List[str] = []
    if "ticker" not in df.columns:
        v.append("missing required column: ticker")
    else:
        tick = df["ticker"].astype(str).str.strip()
        n_empty = int((tick == "").sum())
        if n_empty:
            v.append(f"empty ticker values in {n_empty} rows")
        dups = sorted(tick[tick.duplicated()].unique().tolist())
        if dups:
            v.append(f"duplicate tickers (full frame): {dups[:10]}")

    if "actionable_rank" not in df.columns:
        v.append("missing required column: actionable_rank")
    else:
        present = df["actionable_rank"].astype(str).str.strip() != ""
        bad = present & _numeric(df["actionable_rank"]).isna()
        if bad.any():
            v.append(f"non-numeric actionable_rank in {int(bad.sum())} rows")

    for fld in gate_fields:
        if fld not in df.columns:
            v.append(f"missing required gate field: {fld}")
    return v


def validate_cohort(df: pd.DataFrame, expect_cohort: int = DEFAULT_EXPECT_COHORT) -> List[str]:
    """Cohort = actionable_rank <= 60. Hard-fail integrity checks."""
    v: List[str] = []
    coh = cohort_frame(df)
    n = len(coh)
    if n == 0:
        v.append("cohort (actionable_rank<=60) is empty")
        return v
    if n != expect_cohort:
        v.append(f"cohort size {n} != expected {expect_cohort}")

    if "final_score" in coh.columns:
        fs = _numeric(coh["final_score"])
        if fs.isna().any():
            v.append(f"null/non-numeric final_score in {int(fs.isna().sum())} cohort rows")
    if "close_price" in coh.columns:
        cp = _numeric(coh["close_price"])
        if cp.isna().any():
            v.append(f"null/non-numeric close_price in {int(cp.isna().sum())} cohort rows")
        if (cp <= 0).any():
            v.append(f"close_price <= 0 in {int((cp <= 0).sum())} cohort rows")

    tick = coh["ticker"].astype(str).str.strip()
    if tick.duplicated().any():
        v.append("duplicate tickers within cohort")
    return v


def _cohort_returns(base_df: pd.DataFrame, fwd_df: pd.DataFrame) -> pd.Series:
    """Forward returns for cohort tickers with positive base+forward close."""
    base_coh = cohort_frame(base_df)
    b = pd.DataFrame(
        {
            "ticker": base_coh["ticker"].astype(str).str.strip(),
            "bp": _numeric(base_coh["close_price"]) if "close_price" in base_coh.columns else float("nan"),
        }
    )
    f = pd.DataFrame(
        {
            "ticker": fwd_df["ticker"].astype(str).str.strip(),
            "fp": _numeric(fwd_df["close_price"]) if "close_price" in fwd_df.columns else float("nan"),
        }
    )
    m = b.merge(f, on="ticker", how="left")
    valid = m[(m["bp"] > 0) & (m["fp"] > 0) & m["bp"].notna() & m["fp"].notna()]
    return (valid["fp"] - valid["bp"]) / valid["bp"]


def validate_forward_pair(
    base_df: pd.DataFrame,
    fwd_df: Optional[pd.DataFrame],
    observed_forward_date: Optional[str],
    min_pairs: int = MIN_IC_PAIRS,
) -> Tuple[str, int, Optional[str]]:
    """Returns (status, n_pairs, reason).

    status is "OK" or "UNOBSERVABLE". Missing/short forward data is UNOBSERVABLE
    — never a measured zero. This is a gate-cannot-run state, not a data defect.
    """
    if fwd_df is None or observed_forward_date is None:
        return ("UNOBSERVABLE", 0, "no forward snapshot provided")
    rets = _cohort_returns(base_df, fwd_df)
    n = int(rets.notna().sum())
    if n < min_pairs:
        return ("UNOBSERVABLE", n, f"only {n} valid forward pairs (< {min_pairs}); cannot compute IC")
    return ("OK", n, None)


def check_freshness(
    base_df: pd.DataFrame,
    fwd_df: Optional[pd.DataFrame],
    observed_forward_date: Optional[str] = None,
    requested_forward_date: Optional[str] = None,
    fallback_tolerance_days: int = DEFAULT_FALLBACK_TOLERANCE_DAYS,
    zero_warn_frac: float = DEFAULT_ZERO_RETURN_WARN_FRAC,
) -> List[str]:
    """Soft warnings (never hard-fail): stale/frozen prices, zero variance, fallback gap."""
    w: List[str] = []
    if fwd_df is not None and observed_forward_date is not None:
        rets = _cohort_returns(base_df, fwd_df).dropna()
        if len(rets) > 0:
            if (rets.abs() < _EPS).all():
                w.append("forward prices identical to base for all cohort pairs (stale/frozen feed?)")
            elif float(rets.var(ddof=0)) < _EPS:
                w.append("forward returns have ~zero variance")
            zero_frac = float((rets.abs() < _EPS).mean())
            if zero_frac > zero_warn_frac:
                w.append(f"{zero_frac:.0%} of forward returns are zero (> {zero_warn_frac:.0%} threshold)")

    if requested_forward_date and observed_forward_date and observed_forward_date != requested_forward_date:
        try:
            delta = (
                datetime.strptime(observed_forward_date, "%Y-%m-%d")
                - datetime.strptime(requested_forward_date, "%Y-%m-%d")
            ).days
            if delta > fallback_tolerance_days:
                w.append(f"forward fallback +{delta}d exceeds tolerance {fallback_tolerance_days}d")
        except ValueError:
            pass
    return w


def run_contract(
    base_df: pd.DataFrame,
    fwd_df: Optional[pd.DataFrame] = None,
    observed_forward_date: Optional[str] = None,
    requested_forward_date: Optional[str] = None,
    expect_cohort: int = DEFAULT_EXPECT_COHORT,
    gate_fields: List[str] = DEFAULT_GATE_FIELDS,
    fallback_tolerance_days: int = DEFAULT_FALLBACK_TOLERANCE_DAYS,
) -> ContractResult:
    """Orchestrate the full contract. Precedence:

    - schema/cohort violations  -> FAIL (always dominates)
    - else forward UNOBSERVABLE  -> UNOBSERVABLE (gate cannot run)
    - else                        -> PASS (warnings allowed)
    """
    base_violations = validate_rankings_schema(base_df, gate_fields) + validate_cohort(base_df, expect_cohort)
    fwd_status, n_pairs, fwd_reason = validate_forward_pair(base_df, fwd_df, observed_forward_date)
    warnings = check_freshness(base_df, fwd_df, observed_forward_date, requested_forward_date, fallback_tolerance_days)

    if base_violations:
        status = "FAIL"
    elif fwd_status == "UNOBSERVABLE":
        status = "UNOBSERVABLE"
    else:
        status = "PASS"

    return ContractResult(
        status=status,
        violations=base_violations,
        warnings=warnings,
        observed_forward_date=observed_forward_date,
        requested_forward_date=requested_forward_date,
        forward_pairs=n_pairs,
        unobservable_reason=fwd_reason if status == "UNOBSERVABLE" else None,
    )


# ---------------------------------------------------------------------------
# Read-only CLI preflight
# ---------------------------------------------------------------------------


def _snapshot_date(path) -> Optional[str]:
    """Best-effort snapshot date from a directory basename (YYYY-MM-DD)."""
    name = Path(path).name
    try:
        datetime.strptime(name[:10], "%Y-%m-%d")
        return name[:10]
    except ValueError:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only value-level contract for rankings.csv / IC gate inputs")
    parser.add_argument("--base", required=True, help="Base snapshot dir or rankings.csv path")
    parser.add_argument("--forward", default=None, help="Forward snapshot dir or rankings.csv path (optional)")
    parser.add_argument("--expect-cohort", type=int, default=DEFAULT_EXPECT_COHORT)
    parser.add_argument("--gate-fields", nargs="*", default=DEFAULT_GATE_FIELDS)
    parser.add_argument("--requested-forward-date", default=None, help="Expected forward date for fallback-gap warning")
    parser.add_argument("--fallback-tolerance-days", type=int, default=DEFAULT_FALLBACK_TOLERANCE_DAYS)
    args = parser.parse_args(argv)

    def _resolve_csv(path):
        p = Path(path)
        return p / "rankings.csv" if p.is_dir() else p

    base_csv = _resolve_csv(args.base)
    if not base_csv.exists():
        print(f"STATUS: FAIL\n  VIOLATION: base rankings.csv not found at {base_csv}")
        return 2
    base_df = load_rankings(args.base)

    # Forward is optional and may be requested-but-missing (partial/absent
    # snapshot). A missing forward file must degrade to UNOBSERVABLE, not crash.
    fwd_df = None
    observed = None
    if args.forward:
        fwd_csv = _resolve_csv(args.forward)
        if fwd_csv.exists():
            fwd_df = load_rankings(args.forward)
            observed = _snapshot_date(args.forward)
        else:
            print(f"  note: forward rankings.csv not found at {fwd_csv} -> forward UNOBSERVABLE")

    result = run_contract(
        base_df,
        fwd_df=fwd_df,
        observed_forward_date=observed,
        requested_forward_date=args.requested_forward_date,
        expect_cohort=args.expect_cohort,
        gate_fields=args.gate_fields,
        fallback_tolerance_days=args.fallback_tolerance_days,
    )

    print(f"STATUS: {result.status}")
    print(f"  base: {args.base}")
    print(
        f"  forward: {args.forward or '(none)'}  observed={result.observed_forward_date}  pairs={result.forward_pairs}"
    )
    if result.unobservable_reason:
        print(f"  UNOBSERVABLE reason: {result.unobservable_reason}")
    for vmsg in result.violations:
        print(f"  VIOLATION: {vmsg}")
    for wmsg in result.warnings:
        print(f"  WARN: {wmsg}")

    return {"PASS": 0, "FAIL": 2, "UNOBSERVABLE": 3}[result.status]


if __name__ == "__main__":
    sys.exit(main())
