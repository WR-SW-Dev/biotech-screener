#!/usr/bin/env python3
"""Spec 054 — Trial Execution / Timeline-Delta Signal Study.

Tests whether trial execution quality (timeline adherence, update cadence,
pipeline velocity) predicts future biotech stock returns, and whether it
is incremental to the B6 institutional selector (coinvest + inst_delta).

Static execution features are computed from trial_records.json as-of each
snapshot date (PIT-safe). Delta features from AACT snapshot pairs are
included where available but have limited history (2026 only).

Tracks:
  A — Univariate signal cards for all execution signals
  B — Selector and ranker bundle tests vs institutional baseline
  C — Diagnostic / overlay use cases
  D — Robustness slices (regime, year, mcap, catalyst proximity)
  E — Incrementality vs institutional signals

Usage:
    python3 scripts/research/execution_delta_study.py
    python3 scripts/research/execution_delta_study.py --track A
    python3 scripts/research/execution_delta_study.py --track B
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
TRIAL_RECORDS = PROJECT_ROOT / "production_data" / "trial_records.json"
AACT_DELTAS_DIR = PROJECT_ROOT / "artifacts" / "aact_deltas"
OUTPUT_DIR = PROJECT_ROOT / "output" / "execution_delta_study"

SCHEMA_VERSION = "execution_delta_study.v1"

# Cost model (same as options study)
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000

HORIZONS = [20, 63]
TOP_NS = [20, 30]

# Active statuses for execution analysis
ACTIVE_STATUSES = frozenset(
    {
        "RECRUITING",
        "ACTIVE_NOT_RECRUITING",
        "ENROLLING_BY_INVITATION",
        "NOT_YET_RECRUITING",
    }
)
COMPLETED_STATUSES = frozenset({"COMPLETED"})
NEGATIVE_STATUSES = frozenset(
    {
        "TERMINATED",
        "WITHDRAWN",
        "SUSPENDED",
        "NO_LONGER_AVAILABLE",
    }
)

PHASE_RANK = {
    "PHASE1": 1,
    "Phase 1": 1,
    "EARLY_PHASE1": 0.5,
    "PHASE2": 2,
    "Phase 2": 2,
    "PHASE3": 3,
    "Phase 3": 3,
    "PHASE4": 4,
    "Phase 4": 4,
}

# Static execution signals to test
STATIC_SIGNALS = [
    "exec_pcd_overdue_ratio",
    "exec_pcd_overdue_months_avg",
    "exec_update_recency_days",
    "exec_update_silence_flag",
    "exec_pipeline_velocity",
    "exec_termination_rate",
    "exec_late_stage_density",
    "exec_results_posting_rate",
    "exec_active_trial_count",
    "exec_pipeline_breadth",
    "exec_phase_advancement_score",
]

# Direction: True = higher is better, False = lower is better
SIGNAL_DIRECTION = {
    "exec_pcd_overdue_ratio": False,
    "exec_pcd_overdue_months_avg": False,
    "exec_update_recency_days": False,
    "exec_update_silence_flag": False,
    "exec_pipeline_velocity": True,
    "exec_termination_rate": False,
    "exec_late_stage_density": True,
    "exec_results_posting_rate": True,
    "exec_active_trial_count": True,
    "exec_pipeline_breadth": True,
    "exec_phase_advancement_score": True,
    # Delta signals
    "aact_execution_score": True,
}

# Incumbent selector signals (B6 baseline)
INCUMBENT_SELECTOR = {
    "coinvest_score_z": (0.65, True),
    "inst_delta_z": (0.35, True),
}

# ── Helpers ──────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_stdev(vals):
    return statistics.stdev(vals) if len(vals) >= 2 else None


def _safe_ir(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / s if s > 1e-9 else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def _hit_rate(vals):
    return sum(1 for v in vals if v > 0) / len(vals) if vals else None


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _pp(v):
    return v * 100 if v is not None else None


def _fmt(v, d=2):
    return f"{v:.{d}f}" if v is not None else "---"


def spearman_ic(x, y):
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def zscore_vals(vals):
    if len(vals) < 3:
        return vals
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s < 1e-9:
        return [0.0] * len(vals)
    return [(v - m) / s for v in vals]


def winsorize(vals, pct=0.025):
    if len(vals) < 10:
        return vals
    s = sorted(vals)
    lo = s[max(0, int(len(s) * pct))]
    hi = s[min(len(s) - 1, int(len(s) * (1 - pct)))]
    return [max(lo, min(hi, v)) for v in vals]


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ── Trial Data Loading ───────────────────────────────────────────────


def load_trial_records():
    """Load trial records and index by ticker."""
    print("Loading trial records...")
    with open(TRIAL_RECORDS) as f:
        trials = json.load(f)
    print(f"  {len(trials):,} trials")

    by_ticker = defaultdict(list)
    for t in trials:
        ticker = t.get("ticker")
        if ticker:
            by_ticker[ticker].append(t)
    print(f"  {len(by_ticker)} tickers with trials")
    return dict(by_ticker)


def load_aact_deltas():
    """Load AACT delta artifacts and index by (date, ticker)."""
    deltas = {}
    if not AACT_DELTAS_DIR.exists():
        print("  No AACT delta artifacts found")
        return deltas
    for path in sorted(AACT_DELTAS_DIR.glob("aact_deltas_*.json")):
        data = json.loads(path.read_text())
        as_of = data.get("as_of_date", "")
        for t in data.get("tickers", []):
            ticker = t.get("ticker", "")
            if ticker:
                deltas[(as_of, ticker)] = t
    print(f"  Loaded AACT deltas: {len(deltas)} ticker-date pairs")
    return deltas


# ── Compute Static Execution Features ────────────────────────────────


def compute_execution_features(
    ticker_trials: dict[str, list[dict]],
    aact_deltas: dict[tuple, dict],
    panel: list[dict],
) -> list[dict]:
    """Compute static execution features for each panel row.

    For each (ticker, snapshot_date), evaluates the trial portfolio as-of
    that date using PIT-safe date boundaries.
    """
    print("Computing static execution features...")
    n_computed = 0
    n_skipped = 0

    for row in panel:
        ticker = row.get("ticker", "")
        snap_date_str = row.get("snapshot_date", "")
        snap_date = _parse_date(snap_date_str)

        trials = ticker_trials.get(ticker, [])
        if not trials or not snap_date:
            n_skipped += 1
            for sig in STATIC_SIGNALS:
                row[sig] = ""
            row["aact_execution_score"] = row.get("aact_execution_score", "")
            continue

        # PIT filter: only trials posted before snapshot date
        pit_trials = []
        for t in trials:
            lup = _parse_date(t.get("last_update_posted"))
            fp = _parse_date(t.get("first_posted"))
            # Use last_update_posted as PIT boundary; fall back to first_posted
            pit_date = lup or fp
            if pit_date and pit_date < snap_date:
                pit_trials.append(t)

        if not pit_trials:
            n_skipped += 1
            for sig in STATIC_SIGNALS:
                row[sig] = ""
            continue

        # Classify trials by status
        active = [t for t in pit_trials if t.get("status", "") in ACTIVE_STATUSES]
        completed = [t for t in pit_trials if t.get("status", "") in COMPLETED_STATUSES]
        negative = [t for t in pit_trials if t.get("status", "") in NEGATIVE_STATUSES]
        started = active + completed + negative  # all trials with a definitive status

        # --- PCD overdue ratio ---
        n_overdue = 0
        overdue_months = []
        for t in active:
            pcd = _parse_date(t.get("primary_completion_date"))
            if pcd and pcd < snap_date:
                n_overdue += 1
                months = (snap_date - pcd).days / 30.44
                overdue_months.append(months)

        row["exec_pcd_overdue_ratio"] = n_overdue / len(active) if active else ""
        row["exec_pcd_overdue_months_avg"] = (
            statistics.mean(overdue_months) if overdue_months else (0.0 if active else "")
        )

        # --- Update recency ---
        recency_days = []
        for t in active:
            lup = _parse_date(t.get("last_update_posted"))
            if lup:
                days = (snap_date - lup).days
                if days >= 0:
                    recency_days.append(days)

        row["exec_update_recency_days"] = statistics.mean(recency_days) if recency_days else ""
        row["exec_update_silence_flag"] = (1.0 if any(d > 180 for d in recency_days) else 0.0) if recency_days else ""

        # --- Pipeline velocity ---
        if started:
            row["exec_pipeline_velocity"] = (len(active) + len(completed)) / len(started)
        else:
            row["exec_pipeline_velocity"] = ""

        # --- Termination rate ---
        if started:
            row["exec_termination_rate"] = len(negative) / len(started)
        else:
            row["exec_termination_rate"] = ""

        # --- Late-stage density ---
        if active:
            late = sum(1 for t in active if PHASE_RANK.get(t.get("phase", ""), 0) >= 2)
            row["exec_late_stage_density"] = late / len(active)
        else:
            row["exec_late_stage_density"] = ""

        # --- Results posting rate ---
        if completed:
            with_results = sum(
                1
                for t in completed
                if t.get("results_first_posted")
                and _parse_date(t["results_first_posted"])
                and _parse_date(t["results_first_posted"]) < snap_date
            )
            row["exec_results_posting_rate"] = with_results / len(completed)
        else:
            row["exec_results_posting_rate"] = ""

        # --- Active trial count ---
        row["exec_active_trial_count"] = len(active) if active else 0

        # --- Pipeline breadth (unique indications) ---
        indications = set()
        for t in active:
            for c in t.get("conditions") or []:
                if c and c.lower() not in ("healthy volunteers", "healthy"):
                    indications.add(c.lower())
        row["exec_pipeline_breadth"] = len(indications)

        # --- Phase advancement score ---
        phase_score = sum(PHASE_RANK.get(t.get("phase", ""), 0) for t in active)
        row["exec_phase_advancement_score"] = phase_score

        # --- AACT delta score (from precomputed deltas, if available) ---
        # Find nearest delta on or before snapshot date
        delta_key = None
        for delta_date in sorted(set(k[0] for k in aact_deltas if k[1] == ticker), reverse=True):
            if delta_date <= snap_date_str:
                delta_key = (delta_date, ticker)
                break

        if delta_key and delta_key in aact_deltas:
            d = aact_deltas[delta_key]
            # Only use if existing value is empty
            if not row.get("aact_execution_score") or row["aact_execution_score"] == "":
                row["aact_execution_score"] = d.get("execution_score", "")

        n_computed += 1

    print(f"  Computed: {n_computed}, Skipped: {n_skipped}")
    return panel


# ── Data Loading ─────────────────────────────────────────────────────


def load_panel():
    print("Loading research panel...")
    with open(PANEL_CSV) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")
    return panel


def group_by_snapshot(panel):
    groups = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


# ── Track A: Univariate Signal Cards ─────────────────────────────────


def run_track_a(panel, snapshots):
    """Track A: Univariate signal evaluation for all execution signals."""
    print("\n" + "=" * 70)
    print("TRACK A — UNIVARIATE EXECUTION SIGNAL CARDS")
    print("=" * 70)

    all_signals = STATIC_SIGNALS + ["aact_execution_score"]
    results = []

    for sig_idx, signal in enumerate(all_signals):
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        print(
            f"  [{sig_idx + 1}/{len(all_signals)}] {signal} " f"({'higher' if higher_better else 'lower'}=better)...",
            end=" ",
        )

        card = {
            "signal": signal,
            "higher_is_better": higher_better,
            "coverage": {},
            "gate": {},
            "selector": {},
            "ranker": {},
            "regime": {},
        }

        # Coverage
        n_total = len(panel)
        n_present = sum(1 for r in panel if r.get(signal) is not None and r.get(signal) != "")
        n_eligible_present = sum(
            1 for r in panel if _sf(r.get("eligible")) == 1.0 and r.get(signal) is not None and r.get(signal) != ""
        )
        n_eligible = sum(1 for r in panel if _sf(r.get("eligible")) == 1.0)
        n_nonzero = sum(
            1 for r in panel if r.get(signal) is not None and r.get(signal) != "" and abs(_sf(r.get(signal), 0)) > 1e-9
        )
        card["coverage"] = {
            "total_pct": _r(n_present / n_total * 100) if n_total else 0,
            "eligible_pct": _r(n_eligible_present / n_eligible * 100) if n_eligible else 0,
            "nonzero_pct": _r(n_nonzero / n_total * 100) if n_total else 0,
            "n_present": n_present,
            "n_eligible_present": n_eligible_present,
        }

        if n_eligible_present < 50:
            card["verdict"] = "NO_GO"
            card["verdict_reason"] = f"insufficient coverage ({n_eligible_present} eligible rows)"
            results.append(card)
            print(f"SKIP (coverage={n_eligible_present})")
            continue

        # Gate + Selector + Ranker per horizon
        for h in HORIZONS:
            fwd_col = f"fwd_excess_xbi_{h}d"

            gate_spreads = []
            sel_improvements = []
            sel_baseline_rets = []
            sel_bundle_rets = []
            ranker_ics = []
            rw_minus_ew = []

            for snap_date, rows in sorted(snapshots.items()):
                eligible_with_signal = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get(fwd_col), None)
                    rank = _sf(r.get("actionable_rank"), None)
                    if sv is not None and fwd is not None and rank is not None:
                        eligible_with_signal.append(
                            {
                                "ticker": r.get("ticker", ""),
                                "signal": sv,
                                "fwd": fwd,
                                "rank": rank,
                            }
                        )

                if len(eligible_with_signal) < 10:
                    continue

                # Gate: median split
                sig_vals = [e["signal"] for e in eligible_with_signal]
                med = statistics.median(sig_vals)
                above = [e["fwd"] for e in eligible_with_signal if e["signal"] > med]
                below = [e["fwd"] for e in eligible_with_signal if e["signal"] <= med]
                if above and below:
                    spread = statistics.mean(above) - statistics.mean(below)
                    if not higher_better:
                        spread = -spread
                    gate_spreads.append(spread)

                # Selector: top-30 by signal vs top-30 by rank
                for top_n in [30]:
                    if len(eligible_with_signal) < top_n:
                        continue

                    by_rank = sorted(eligible_with_signal, key=lambda x: x["rank"])
                    baseline_ret = statistics.mean(e["fwd"] for e in by_rank[:top_n])

                    if higher_better:
                        by_signal = sorted(eligible_with_signal, key=lambda x: -x["signal"])
                    else:
                        by_signal = sorted(eligible_with_signal, key=lambda x: x["signal"])
                    bundle_ret = statistics.mean(e["fwd"] for e in by_signal[:top_n])

                    sel_improvements.append(bundle_ret - baseline_ret)
                    sel_baseline_rets.append(baseline_ret)
                    sel_bundle_rets.append(bundle_ret)

                # Ranker: IC within top-30
                top30 = sorted(eligible_with_signal, key=lambda x: x["rank"])[:30]
                if len(top30) >= 10:
                    sigs = [e["signal"] for e in top30]
                    fwds = [e["fwd"] for e in top30]
                    if not higher_better:
                        sigs = [-s for s in sigs]
                    ic = spearman_ic(sigs, fwds)
                    if ic is not None:
                        ranker_ics.append(ic)

                    # RW vs EW
                    z_sigs = zscore_vals(sigs)
                    ew = statistics.mean(e["fwd"] for e in top30)
                    n_s = len(top30)
                    weights = [(n_s - i) for i in range(n_s)]
                    w_sum = sum(weights)
                    ranked = sorted(
                        zip(z_sigs, top30),
                        key=lambda x: -x[0],
                    )
                    rw = sum(weights[i] * ranked[i][1]["fwd"] for i in range(n_s)) / w_sum
                    rw_minus_ew.append(rw - ew)

            card["gate"][str(h)] = {
                "spread_pp": _r(_pp(_safe_mean(gate_spreads))),
                "spread_tstat": _r(_safe_tstat([v * 100 for v in gate_spreads])),
                "spread_hit_rate": _r(_hit_rate(gate_spreads)),
                "n_periods": len(gate_spreads),
            }

            card["selector"][str(h)] = {
                "baseline_pp": _r(_pp(_safe_mean(sel_baseline_rets))),
                "signal_pp": _r(_pp(_safe_mean(sel_bundle_rets))),
                "improvement_pp": _r(_pp(_safe_mean(sel_improvements))),
                "improvement_tstat": _r(_safe_tstat([v * 100 for v in sel_improvements])),
                "improvement_ir": _r(_safe_ir([v * 100 for v in sel_improvements])),
                "hit_rate": _r(_hit_rate(sel_improvements)),
                "n_periods": len(sel_improvements),
            }

            rw_ew_gross = _safe_mean(rw_minus_ew)
            rw_ew_net = (rw_ew_gross - MONTHLY_COST_DRAG) if rw_ew_gross is not None else None
            card["ranker"][str(h)] = {
                "ic_mean": _r(_safe_mean(ranker_ics)),
                "ic_tstat": _r(_safe_tstat(ranker_ics)),
                "ic_hit_rate": _r(_hit_rate(ranker_ics)),
                "rw_minus_ew_gross_pp": _r(_pp(rw_ew_gross)),
                "rw_minus_ew_net_pp": _r(_pp(rw_ew_net)),
                "n_periods": len(ranker_ics),
            }

        # Regime slices at 63d
        card["regime"] = {}
        for regime_label in ["bear", "neutral", "bull"]:
            regime_spreads = []
            for snap_date, rows in sorted(snapshots.items()):
                sample_regime = None
                for r in rows:
                    sample_regime = r.get("regime_63d")
                    if sample_regime:
                        break
                if sample_regime != regime_label:
                    continue

                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    if sv is not None and fwd is not None:
                        eligible.append({"signal": sv, "fwd": fwd})

                if len(eligible) < 10:
                    continue

                sig_vals = [e["signal"] for e in eligible]
                med = statistics.median(sig_vals)
                above = [e["fwd"] for e in eligible if e["signal"] > med]
                below = [e["fwd"] for e in eligible if e["signal"] <= med]
                if above and below:
                    spread = statistics.mean(above) - statistics.mean(below)
                    if not higher_better:
                        spread = -spread
                    regime_spreads.append(spread)

            card["regime"][regime_label] = {
                "spread_pp": _r(_pp(_safe_mean(regime_spreads))),
                "spread_tstat": _r(_safe_tstat([v * 100 for v in regime_spreads])),
                "n_periods": len(regime_spreads),
            }

        # Correlation with incumbent signals
        coinvest_corr = []
        inst_corr = []
        for snap_date, rows in sorted(snapshots.items()):
            sigs, cvs, ivs = [], [], []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal), None)
                cv = _sf(r.get("coinvest_score_z"), None)
                iv = _sf(r.get("inst_delta_z"), None)
                if sv is not None and cv is not None:
                    sigs.append(sv)
                    cvs.append(cv)
                if sv is not None and iv is not None:
                    ivs.append(iv)
            if len(sigs) >= 10:
                ic = spearman_ic(sigs, cvs)
                if ic is not None:
                    coinvest_corr.append(ic)
            if len(ivs) >= 10:
                ic = spearman_ic(
                    [
                        _sf(r.get(signal), 0)
                        for r in rows
                        if _sf(r.get("eligible")) == 1.0
                        and _sf(r.get(signal), None) is not None
                        and _sf(r.get("inst_delta_z"), None) is not None
                    ],
                    [
                        _sf(r.get("inst_delta_z"), 0)
                        for r in rows
                        if _sf(r.get("eligible")) == 1.0
                        and _sf(r.get(signal), None) is not None
                        and _sf(r.get("inst_delta_z"), None) is not None
                    ],
                )
                if ic is not None:
                    inst_corr.append(ic)

        card["correlations"] = {
            "coinvest_corr": _r(_safe_mean(coinvest_corr)),
            "inst_delta_corr": _r(_safe_mean(inst_corr)),
        }

        # Verdict
        sel_63 = card["selector"].get("63", {})
        rnk_63 = card["ranker"].get("63", {})
        sel_t = sel_63.get("improvement_tstat") or 0
        sel_pp = sel_63.get("improvement_pp") or 0
        rnk_ic_t = rnk_63.get("ic_tstat") or 0
        rnk_ic = rnk_63.get("ic_mean") or 0
        cov_pct = card["coverage"].get("eligible_pct", 0)

        if cov_pct < 40:
            card["verdict"] = "NO_GO"
            card["verdict_reason"] = f"coverage {cov_pct:.0f}% < 40%"
        elif sel_t >= 1.6 and sel_pp > 0 and cov_pct >= 40:
            card["verdict"] = "PROMOTE_CANDIDATE"
            card["verdict_reason"] = (
                f"selector Δ={sel_pp:+.2f}pp t={sel_t:.2f}, " f"ranker IC={rnk_ic:+.3f} t={rnk_ic_t:.2f}"
            )
        elif (sel_t >= 1.0 and sel_pp > 0) or (rnk_ic_t >= 1.6 and rnk_ic > 0):
            card["verdict"] = "SHADOW"
            card["verdict_reason"] = (
                f"selector Δ={sel_pp:+.2f}pp t={sel_t:.2f}, " f"ranker IC={rnk_ic:+.3f} t={rnk_ic_t:.2f}"
            )
        elif sel_pp > 0 or rnk_ic > 0:
            card["verdict"] = "HOLD"
            card["verdict_reason"] = "positive but weak"
        else:
            card["verdict"] = "NO_GO"
            card["verdict_reason"] = f"selector Δ={sel_pp:+.2f}pp, ranker IC={rnk_ic:+.3f}"

        s63 = card["selector"].get("63", {})
        print(
            f"Δ={s63.get('improvement_pp', '?'):+.2f}pp "
            f"t={s63.get('improvement_tstat', 0):.2f} "
            f"IC={rnk_ic:+.3f} → {card['verdict']}"
        )

        results.append(card)

    return results


# ── Track B: Bundle Tests ────────────────────────────────────────────


SELECTOR_BUNDLES = {
    "S0_incumbent_B6": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    "S1_incumbent_plus_pipeline_velocity": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_pipeline_velocity": (0.20, True),
    },
    "S2_incumbent_plus_overdue_ratio": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_pcd_overdue_ratio": (0.20, False),
    },
    "S3_incumbent_plus_update_recency": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_update_recency_days": (0.20, False),
    },
    "S4_incumbent_plus_late_stage": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_late_stage_density": (0.20, True),
    },
    "S5_incumbent_plus_phase_advancement": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_phase_advancement_score": (0.20, True),
    },
    "S6_incumbent_plus_termination_rate": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_termination_rate": (0.20, False),
    },
    "S7_incumbent_plus_results_posting": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "exec_results_posting_rate": (0.20, True),
    },
    "S8_incumbent_plus_exec_composite": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.25, True),
        "exec_pipeline_velocity": (0.10, True),
        "exec_pcd_overdue_ratio": (0.10, False),
        "exec_update_recency_days": (0.05, False),
    },
    "S9_incumbent_plus_aact_score": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "aact_execution_score": (0.20, True),
    },
    "S10_execution_only": {
        "exec_pipeline_velocity": (0.25, True),
        "exec_pcd_overdue_ratio": (0.25, False),
        "exec_late_stage_density": (0.25, True),
        "exec_phase_advancement_score": (0.25, True),
    },
    "S11_incumbent_light_exec": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.25, True),
        "exec_pipeline_velocity": (0.08, True),
        "exec_late_stage_density": (0.08, True),
        "exec_termination_rate": (0.05, False),
        "exec_update_recency_days": (0.04, False),
    },
}

RANKER_BUNDLES = {
    "R0_coinvest_inst_baseline": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    "R1_pipeline_velocity_only": {
        "exec_pipeline_velocity": (1.0, True),
    },
    "R2_overdue_ratio_only": {
        "exec_pcd_overdue_ratio": (1.0, False),
    },
    "R3_update_recency_only": {
        "exec_update_recency_days": (1.0, False),
    },
    "R4_late_stage_only": {
        "exec_late_stage_density": (1.0, True),
    },
    "R5_phase_advancement_only": {
        "exec_phase_advancement_score": (1.0, True),
    },
    "R6_termination_rate_only": {
        "exec_termination_rate": (1.0, False),
    },
    "R7_results_posting_only": {
        "exec_results_posting_rate": (1.0, True),
    },
    "R8_exec_compact": {
        "exec_pipeline_velocity": (0.30, True),
        "exec_pcd_overdue_ratio": (0.30, False),
        "exec_late_stage_density": (0.20, True),
        "exec_update_recency_days": (0.20, False),
    },
    "R9_aact_score_only": {
        "aact_execution_score": (1.0, True),
    },
    "R10_coinvest_plus_exec": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.20, True),
        "exec_pipeline_velocity": (0.15, True),
        "exec_pcd_overdue_ratio": (0.15, False),
    },
    "R11_breadth_only": {
        "exec_pipeline_breadth": (1.0, True),
    },
    "R12_active_count_only": {
        "exec_active_trial_count": (1.0, True),
    },
}


def compute_bundle_score_snap(rows, bundle):
    """Compute weighted bundle score for eligible names in one snapshot."""
    z_maps = {}
    for signal, (_, _) in bundle.items():
        vals, tickers = [], []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            v = _sf(r.get(signal), None)
            if v is not None:
                vals.append(v)
                tickers.append(r.get("ticker", ""))
        if len(vals) < 3:
            z_maps[signal] = {}
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
        if s < 1e-9:
            s = 1.0
        z_maps[signal] = {tickers[i]: (vals[i] - m) / s for i in range(len(tickers))}

    scores = {}
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        ticker = r.get("ticker", "")
        total, total_w = 0.0, 0.0
        for signal, (weight, higher_better) in bundle.items():
            z = z_maps.get(signal, {}).get(ticker)
            if z is not None:
                if not higher_better:
                    z = -z
                total += weight * z
                total_w += weight
        scores[ticker] = total / total_w if total_w > 0 else 0.0
    return scores


def run_selector_bundles(snapshots):
    """Test selector bundles."""
    print("\n" + "=" * 70)
    print("TRACK B.1 — SELECTOR BUNDLE TESTS")
    print("=" * 70)

    results = []
    for bname, bundle in SELECTOR_BUNDLES.items():
        sigs = ", ".join(f"{s}({w:.0%})" for s, (w, _) in bundle.items())
        print(f"  {bname}: {sigs}")

        result = {
            "bundle_name": bname,
            "signals": {s: {"weight": w, "higher_is_better": h} for s, (w, h) in bundle.items()},
        }

        for top_n in TOP_NS:
            result[f"top_{top_n}"] = {}
            for h in HORIZONS:
                fwd_col = f"fwd_excess_xbi_{h}d"
                improvements = []
                baseline_rets = []
                bundle_rets = []
                turnovers = []
                prev_tickers = set()

                for snap_date, rows in sorted(snapshots.items()):
                    eligible = []
                    for r in rows:
                        if _sf(r.get("eligible")) != 1.0:
                            continue
                        fwd = _sf(r.get(fwd_col), None)
                        rank = _sf(r.get("actionable_rank"), None)
                        if fwd is not None and rank is not None:
                            eligible.append(
                                {
                                    "ticker": r.get("ticker", ""),
                                    "rank": rank,
                                    "fwd": fwd,
                                }
                            )
                    if len(eligible) < top_n:
                        continue

                    by_rank = sorted(eligible, key=lambda x: x["rank"])
                    baseline_ret = statistics.mean(e["fwd"] for e in by_rank[:top_n])

                    scores = compute_bundle_score_snap(rows, bundle)
                    for e in eligible:
                        e["score"] = scores.get(e["ticker"], 0.0)
                    by_score = sorted(eligible, key=lambda x: -x["score"])
                    bundle_ret = statistics.mean(e["fwd"] for e in by_score[:top_n])

                    improvements.append(bundle_ret - baseline_ret)
                    baseline_rets.append(baseline_ret)
                    bundle_rets.append(bundle_ret)

                    curr = {e["ticker"] for e in by_score[:top_n]}
                    if prev_tickers:
                        turnovers.append(1.0 - len(curr & prev_tickers) / top_n)
                    prev_tickers = curr

                result[f"top_{top_n}"][str(h)] = {
                    "baseline_pp": _r(_pp(_safe_mean(baseline_rets))),
                    "bundle_pp": _r(_pp(_safe_mean(bundle_rets))),
                    "improvement_pp": _r(_pp(_safe_mean(improvements))),
                    "improvement_cum_pp": _r(_pp(sum(improvements)) if improvements else None),
                    "improvement_tstat": _r(_safe_tstat([v * 100 for v in improvements])),
                    "improvement_ir": _r(_safe_ir([v * 100 for v in improvements])),
                    "hit_rate": _r(_hit_rate(improvements)),
                    "turnover": _r(_safe_mean(turnovers)),
                    "n_periods": len(improvements),
                }

        # Regime splits at 63d top-30
        result["regime"] = {}
        for regime_label in ["bear", "neutral", "bull"]:
            regime_imp = []
            for snap_date, rows in sorted(snapshots.items()):
                sample_regime = None
                for r in rows:
                    sample_regime = r.get("regime_63d")
                    if sample_regime:
                        break
                if sample_regime != regime_label:
                    continue

                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    rank = _sf(r.get("actionable_rank"), None)
                    if fwd is not None and rank is not None:
                        eligible.append(
                            {
                                "ticker": r.get("ticker", ""),
                                "rank": rank,
                                "fwd": fwd,
                            }
                        )
                if len(eligible) < 30:
                    continue

                by_rank = sorted(eligible, key=lambda x: x["rank"])[:30]
                baseline_ret = statistics.mean(e["fwd"] for e in by_rank)
                scores = compute_bundle_score_snap(rows, bundle)
                for e in eligible:
                    e["score"] = scores.get(e["ticker"], 0.0)
                by_score = sorted(eligible, key=lambda x: -x["score"])[:30]
                regime_imp.append(statistics.mean(e["fwd"] for e in by_score) - baseline_ret)

            result["regime"][regime_label] = {
                "improvement_pp": _r(_pp(_safe_mean(regime_imp))),
                "hit_rate": _r(_hit_rate(regime_imp)),
                "n_periods": len(regime_imp),
            }

        h63 = result["top_30"]["63"]
        imp = h63.get("improvement_pp") or 0
        ts = h63.get("improvement_tstat") or 0
        print(f"    -> top-30 63d: {imp:+.2f}pp t={ts:.2f}")

        results.append(result)

    return results


def run_ranker_bundles(snapshots):
    """Test ranker bundles."""
    print("\n" + "=" * 70)
    print("TRACK B.2 — RANKER BUNDLE TESTS")
    print("=" * 70)

    results = []
    for bname, bundle in RANKER_BUNDLES.items():
        sigs = ", ".join(f"{s}({w:.0%})" for s, (w, _) in bundle.items())
        print(f"  {bname}: {sigs}")

        result = {
            "bundle_name": bname,
            "signals": {s: {"weight": w, "higher_is_better": h} for s, (w, h) in bundle.items()},
        }

        for top_n in TOP_NS:
            result[f"top_{top_n}"] = {}
            for h in HORIZONS:
                fwd_col = f"fwd_ret_{h}d"

                ic_vals = []
                rw_ew = []
                cov_vals = []

                for snap_date, rows in sorted(snapshots.items()):
                    topk = []
                    for r in rows:
                        rank = _sf(r.get("actionable_rank"), None)
                        if rank is None or rank > top_n:
                            continue
                        if _sf(r.get("eligible")) != 1.0:
                            continue
                        fwd = _sf(r.get(fwd_col), None)
                        if fwd is None:
                            continue
                        entry = {
                            "ticker": r.get("ticker", ""),
                            "fwd": fwd,
                        }
                        for sig in bundle:
                            entry[sig] = _sf(r.get(sig), None)
                        topk.append(entry)

                    with_all = [t for t in topk if all(t.get(s) is not None for s in bundle)]
                    cov_vals.append(len(with_all) / len(topk) if topk else 0)
                    if len(with_all) < 5:
                        continue

                    # Z-score within top-K
                    z_maps = {}
                    for sig in bundle:
                        vals = [t[sig] for t in with_all]
                        tks = [t["ticker"] for t in with_all]
                        if len(vals) >= 3:
                            m, s = statistics.mean(vals), statistics.stdev(vals)
                            if s < 1e-9:
                                s = 1.0
                            z_maps[sig] = {tks[i]: (vals[i] - m) / s for i in range(len(tks))}
                        else:
                            z_maps[sig] = {}

                    scores = {}
                    for t in with_all:
                        tk = t["ticker"]
                        total, total_w = 0.0, 0.0
                        for sig, (w, hb) in bundle.items():
                            z = z_maps.get(sig, {}).get(tk)
                            if z is not None:
                                if not hb:
                                    z = -z
                                total += w * z
                                total_w += w
                        scores[tk] = total / total_w if total_w > 0 else 0.0

                    ic = spearman_ic(
                        [scores[t["ticker"]] for t in with_all],
                        [t["fwd"] for t in with_all],
                    )
                    if ic is not None:
                        ic_vals.append(ic)

                    ew = statistics.mean(t["fwd"] for t in topk)
                    by_score = sorted(
                        with_all,
                        key=lambda x: -scores[x["ticker"]],
                    )
                    n_s = len(by_score)
                    weights = [(n_s - i) for i in range(n_s)]
                    w_sum = sum(weights)
                    rw = sum(weights[i] * by_score[i]["fwd"] for i in range(n_s)) / w_sum
                    rw_ew.append(rw - ew)

                rw_ew_gross = _safe_mean(rw_ew)
                rw_ew_net = (rw_ew_gross - MONTHLY_COST_DRAG) if rw_ew_gross is not None else None

                result[f"top_{top_n}"][str(h)] = {
                    "ic_mean": _r(_safe_mean(ic_vals)),
                    "ic_tstat": _r(_safe_tstat(ic_vals)),
                    "ic_hit_rate": _r(_hit_rate(ic_vals)),
                    "rw_minus_ew_gross_pp": _r(_pp(rw_ew_gross)),
                    "rw_minus_ew_net_pp": _r(_pp(rw_ew_net)),
                    "coverage": _r(_safe_mean(cov_vals)),
                    "n_periods": len(ic_vals),
                }

        h63 = result["top_30"]["63"]
        ic = h63.get("ic_mean") or 0
        rw_net = h63.get("rw_minus_ew_net_pp") or 0
        print(f"    -> top-30 63d: IC={ic:+.3f} RW-EW net={rw_net:+.2f}pp")

        results.append(result)

    return results


# ── Track C: Diagnostic / Overlay Tests ──────────────────────────────


def run_track_c(panel, snapshots):
    """Track C: test execution signals as diagnostic/overlay."""
    print("\n" + "=" * 70)
    print("TRACK C — DIAGNOSTIC / OVERLAY USE CASES")
    print("=" * 70)

    results = {}

    # C1: Near-catalyst tiebreaker — among catalyst_days <= 30
    print("  C1: Near-catalyst tiebreaker...")
    c1_signals = [
        "exec_pipeline_velocity",
        "exec_pcd_overdue_ratio",
        "exec_update_recency_days",
        "exec_late_stage_density",
        "exec_phase_advancement_score",
    ]
    c1_results = {}
    for sig in c1_signals:
        higher_better = SIGNAL_DIRECTION.get(sig, True)
        ics = []
        for snap_date, rows in sorted(snapshots.items()):
            near_cat = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                cat_days = _sf(r.get("catalyst_days"), None)
                if cat_days is None or cat_days > 30:
                    continue
                sv = _sf(r.get(sig), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                if sv is not None and fwd is not None:
                    near_cat.append({"signal": sv, "fwd": fwd})

            if len(near_cat) >= 8:
                sigs = [e["signal"] for e in near_cat]
                fwds = [e["fwd"] for e in near_cat]
                if not higher_better:
                    sigs = [-s for s in sigs]
                ic = spearman_ic(sigs, fwds)
                if ic is not None:
                    ics.append(ic)

        c1_results[sig] = {
            "ic_mean": _r(_safe_mean(ics)),
            "ic_tstat": _r(_safe_tstat(ics)),
            "n_periods": len(ics),
        }
        print(f"    {sig}: IC={_safe_mean(ics) or 0:+.3f} " f"t={_safe_tstat(ics) or 0:.2f} ({len(ics)} periods)")

    results["near_catalyst_tiebreaker"] = c1_results

    # C2: Phase-gated utility (Phase 2+ vs Phase 1)
    print("  C2: Phase-gated utility...")
    c2_results = {}
    for phase_gate, gate_fn in [
        ("phase2plus", lambda r: _sf(r.get("lead_program_phase"), 0) >= 2),
        ("phase1", lambda r: 0 < _sf(r.get("lead_program_phase"), 0) < 2),
    ]:
        phase_ics = {}
        for sig in [
            "exec_pipeline_velocity",
            "exec_pcd_overdue_ratio",
            "exec_late_stage_density",
        ]:
            higher_better = SIGNAL_DIRECTION.get(sig, True)
            ics = []
            for snap_date, rows in sorted(snapshots.items()):
                gated = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    if not gate_fn(r):
                        continue
                    sv = _sf(r.get(sig), None)
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    if sv is not None and fwd is not None:
                        gated.append({"signal": sv, "fwd": fwd})

                if len(gated) >= 8:
                    sigs = [e["signal"] for e in gated]
                    fwds = [e["fwd"] for e in gated]
                    if not higher_better:
                        sigs = [-s for s in sigs]
                    ic = spearman_ic(sigs, fwds)
                    if ic is not None:
                        ics.append(ic)

            phase_ics[sig] = {
                "ic_mean": _r(_safe_mean(ics)),
                "ic_tstat": _r(_safe_tstat(ics)),
                "n_periods": len(ics),
            }
        c2_results[phase_gate] = phase_ics
        print(f"    {phase_gate}: " + ", ".join(f"{s}={v['ic_mean'] or 0:+.3f}" for s, v in phase_ics.items()))

    results["phase_gated"] = c2_results

    # C3: Single-asset risk interaction
    print("  C3: Single-asset risk interaction...")
    c3_ics = {}
    for sig in [
        "exec_pipeline_velocity",
        "exec_pipeline_breadth",
        "exec_active_trial_count",
    ]:
        higher_better = SIGNAL_DIRECTION.get(sig, True)
        ics = []
        for snap_date, rows in sorted(snapshots.items()):
            single_asset = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sar = r.get("single_asset_risk", "")
                if sar not in ("1", "1.0", "True", "true"):
                    continue
                sv = _sf(r.get(sig), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                if sv is not None and fwd is not None:
                    single_asset.append({"signal": sv, "fwd": fwd})

            if len(single_asset) >= 8:
                sigs = [e["signal"] for e in single_asset]
                fwds = [e["fwd"] for e in single_asset]
                if not higher_better:
                    sigs = [-s for s in sigs]
                ic = spearman_ic(sigs, fwds)
                if ic is not None:
                    ics.append(ic)

        c3_ics[sig] = {
            "ic_mean": _r(_safe_mean(ics)),
            "ic_tstat": _r(_safe_tstat(ics)),
            "n_periods": len(ics),
        }
        print(f"    {sig}: IC={_safe_mean(ics) or 0:+.3f} " f"t={_safe_tstat(ics) or 0:.2f}")

    results["single_asset_risk"] = c3_ics

    return results


# ── Track D: Robustness ──────────────────────────────────────────────


def run_track_d(panel, snapshots, track_a_results):
    """Track D: Robustness slices for top execution signals."""
    print("\n" + "=" * 70)
    print("TRACK D — ROBUSTNESS SLICES")
    print("=" * 70)

    # Pick signals with verdict PROMOTE_CANDIDATE or SHADOW
    test_signals = [c["signal"] for c in track_a_results if c.get("verdict") in ("PROMOTE_CANDIDATE", "SHADOW", "HOLD")]
    if not test_signals:
        test_signals = [
            "exec_pipeline_velocity",
            "exec_pcd_overdue_ratio",
            "exec_late_stage_density",
        ]
        print("  No PROMOTE/SHADOW signals, testing default set")

    print(f"  Testing {len(test_signals)} signals: {test_signals}")

    results = {}

    for signal in test_signals:
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        sig_result = {"signal": signal, "yearly": {}, "mcap": {}, "catalyst": {}}

        # Year-by-year
        yearly_snaps = defaultdict(list)
        for snap_date, rows in snapshots.items():
            year = snap_date[:4]
            yearly_snaps[year].append((snap_date, rows))

        for year, snap_list in sorted(yearly_snaps.items()):
            improvements = []
            for snap_date, rows in snap_list:
                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    rank = _sf(r.get("actionable_rank"), None)
                    if sv is not None and fwd is not None and rank is not None:
                        eligible.append(
                            {
                                "signal": sv,
                                "fwd": fwd,
                                "rank": rank,
                            }
                        )
                if len(eligible) < 30:
                    continue

                by_rank = sorted(eligible, key=lambda x: x["rank"])[:30]
                baseline_ret = statistics.mean(e["fwd"] for e in by_rank)

                if higher_better:
                    by_signal = sorted(eligible, key=lambda x: -x["signal"])
                else:
                    by_signal = sorted(eligible, key=lambda x: x["signal"])
                bundle_ret = statistics.mean(e["fwd"] for e in by_signal[:30])
                improvements.append(bundle_ret - baseline_ret)

            sig_result["yearly"][year] = {
                "improvement_pp": _r(_pp(_safe_mean(improvements))),
                "n_periods": len(improvements),
            }

        # Market cap slices
        for mcap_bucket in ["micro", "small", "mid"]:
            mc_improvements = []
            for snap_date, rows in sorted(snapshots.items()):
                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    if r.get("market_cap_bucket", "") != mcap_bucket:
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    if sv is not None and fwd is not None:
                        eligible.append({"signal": sv, "fwd": fwd})

                if len(eligible) >= 8:
                    sig_vals = [e["signal"] for e in eligible]
                    med = statistics.median(sig_vals)
                    above = [e["fwd"] for e in eligible if e["signal"] > med]
                    below = [e["fwd"] for e in eligible if e["signal"] <= med]
                    if above and below:
                        spread = statistics.mean(above) - statistics.mean(below)
                        if not higher_better:
                            spread = -spread
                        mc_improvements.append(spread)

            sig_result["mcap"][mcap_bucket] = {
                "spread_pp": _r(_pp(_safe_mean(mc_improvements))),
                "n_periods": len(mc_improvements),
            }

        # Catalyst proximity slices
        for cat_label, cat_fn in [
            ("near", lambda r: (_sf(r.get("catalyst_days"), 999) <= 60)),
            ("far", lambda r: (_sf(r.get("catalyst_days"), 999) > 60)),
        ]:
            cat_improvements = []
            for snap_date, rows in sorted(snapshots.items()):
                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    if not cat_fn(r):
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    if sv is not None and fwd is not None:
                        eligible.append({"signal": sv, "fwd": fwd})

                if len(eligible) >= 8:
                    sig_vals = [e["signal"] for e in eligible]
                    med = statistics.median(sig_vals)
                    above = [e["fwd"] for e in eligible if e["signal"] > med]
                    below = [e["fwd"] for e in eligible if e["signal"] <= med]
                    if above and below:
                        spread = statistics.mean(above) - statistics.mean(below)
                        if not higher_better:
                            spread = -spread
                        cat_improvements.append(spread)

            sig_result["catalyst"][cat_label] = {
                "spread_pp": _r(_pp(_safe_mean(cat_improvements))),
                "n_periods": len(cat_improvements),
            }

        results[signal] = sig_result

        yearly_str = " ".join(f"{y}:{v.get('improvement_pp', '?')}" for y, v in sig_result["yearly"].items())
        print(f"    {signal}: yearly=[{yearly_str}]")

    return results


# ── Track E: Incrementality ──────────────────────────────────────────


def run_track_e(panel, snapshots):
    """Track E: Is execution incremental to institutional signals?"""
    print("\n" + "=" * 70)
    print("TRACK E — INCREMENTALITY VS INSTITUTIONAL")
    print("=" * 70)

    test_signals = [
        "exec_pipeline_velocity",
        "exec_pcd_overdue_ratio",
        "exec_late_stage_density",
        "exec_update_recency_days",
        "exec_phase_advancement_score",
        "exec_termination_rate",
        "aact_execution_score",
    ]

    results = {}

    for signal in test_signals:
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        print(f"  {signal}...")

        # Partial IC: within coinvest quintiles
        quintile_ics = []
        raw_ics = []

        for snap_date, rows in sorted(snapshots.items()):
            data = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal), None)
                cv = _sf(r.get("coinvest_score_z"), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                if sv is not None and cv is not None and fwd is not None:
                    data.append((sv, fwd, cv))

            if len(data) < 20:
                continue

            sigs = [d[0] for d in data]
            fwds = [d[1] for d in data]
            cvs = [d[2] for d in data]

            if not higher_better:
                sigs = [-s for s in sigs]

            # Raw IC
            ic_raw = spearman_ic(sigs, fwds)
            if ic_raw is not None:
                raw_ics.append(ic_raw)

            # IC within coinvest quintiles (partial)
            n = len(data)
            q_size = max(4, n // 5)
            indexed = sorted(range(n), key=lambda i: cvs[i])
            partial_ics = []
            for q in range(5):
                start = q * q_size
                end = min(start + q_size, n) if q < 4 else n
                q_idx = indexed[start:end]
                if len(q_idx) >= 5:
                    q_sigs = [sigs[i] for i in q_idx]
                    q_fwds = [fwds[i] for i in q_idx]
                    q_ic = spearman_ic(q_sigs, q_fwds)
                    if q_ic is not None:
                        partial_ics.append(q_ic)

            if partial_ics:
                quintile_ics.append(statistics.mean(partial_ics))

        results[signal] = {
            "raw_ic": _r(_safe_mean(raw_ics)),
            "raw_ic_tstat": _r(_safe_tstat(raw_ics)),
            "partial_ic_within_coinvest_quintiles": _r(_safe_mean(quintile_ics)),
            "partial_ic_tstat": _r(_safe_tstat(quintile_ics)),
            "n_periods": len(raw_ics),
            "incremental": (
                "YES"
                if (_safe_tstat(quintile_ics) or 0) >= 1.6
                else "WEAK" if (_safe_tstat(quintile_ics) or 0) >= 1.0 else "NO"
            ),
        }

        raw = _safe_mean(raw_ics) or 0
        partial = _safe_mean(quintile_ics) or 0
        print(f"    raw IC={raw:+.3f} partial IC={partial:+.3f} " f"→ {results[signal]['incremental']}")

    return results


# ── Output Writers ───────────────────────────────────────────────────


def write_signal_ranking_table(track_a_results, path):
    """Write markdown table ranking all signals."""
    lines = [
        "# Spec 054 — Execution Signal Ranking Table",
        "",
        "| Signal | Cov% | Sel Δpp | Sel t | Rnk IC | Rnk IC t | " "CoinvCorr | Verdict |",
        "|--------|------|---------|-------|--------|----------|" "----------|---------|",
    ]

    sorted_results = sorted(
        track_a_results,
        key=lambda c: (c["selector"].get("63", {}).get("improvement_pp") or -999),
        reverse=True,
    )

    for c in sorted_results:
        s63 = c["selector"].get("63", {})
        r63 = c["ranker"].get("63", {})
        corr = c.get("correlations", {})
        lines.append(
            f"| `{c['signal']}` "
            f"| {c['coverage'].get('eligible_pct', 0):.0f} "
            f"| {_fmt(s63.get('improvement_pp'))} "
            f"| {_fmt(s63.get('improvement_tstat'))} "
            f"| {_fmt(r63.get('ic_mean'), 3)} "
            f"| {_fmt(r63.get('ic_tstat'))} "
            f"| {_fmt(corr.get('coinvest_corr'), 3)} "
            f"| {c.get('verdict', '?')} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))


def write_selector_bundle_table(sel_results, path):
    """Write markdown selector bundle comparison."""
    lines = [
        "# Spec 054 — Selector Bundle Comparison",
        "",
        "## Top-30 at 63d horizon",
        "",
        "| Bundle | Δ pp | t-stat | IR | Hit% | Turnover |",
        "|--------|------|--------|-----|------|----------|",
    ]

    sorted_63 = sorted(
        sel_results,
        key=lambda x: x["top_30"]["63"].get("improvement_pp") or -999,
        reverse=True,
    )
    for r in sorted_63:
        h = r["top_30"]["63"]
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('improvement_pp'))} "
            f"| {_fmt(h.get('improvement_tstat'))} "
            f"| {_fmt(h.get('improvement_ir'))} "
            f"| {_fmt(h.get('hit_rate'))} "
            f"| {_fmt(h.get('turnover'))} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))


def write_ranker_bundle_table(rnk_results, path):
    """Write markdown ranker bundle comparison."""
    lines = [
        "# Spec 054 — Ranker Bundle Comparison",
        "",
        "## Top-30 at 63d horizon",
        "",
        "| Bundle | IC | IC t | RW-EW net | Coverage |",
        "|--------|-----|------|----------|----------|",
    ]

    sorted_63 = sorted(
        rnk_results,
        key=lambda x: x["top_30"]["63"].get("ic_mean") or -999,
        reverse=True,
    )
    for r in sorted_63:
        h = r["top_30"]["63"]
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('ic_mean'), 3)} "
            f"| {_fmt(h.get('ic_tstat'))} "
            f"| {_fmt(h.get('rw_minus_ew_net_pp'))} "
            f"| {_fmt(h.get('coverage'))} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))


def write_master_results(track_a, sel_bundles, rnk_bundles, track_c, track_d, track_e, path):
    """Write master results JSON."""
    master = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track_a_univariate": track_a,
        "track_b_selector_bundles": sel_bundles,
        "track_b_ranker_bundles": rnk_bundles,
        "track_c_diagnostics": track_c,
        "track_d_robustness": track_d,
        "track_e_incrementality": track_e,
    }
    with open(path, "w") as f:
        json.dump(master, f, indent=2, default=str)


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Spec 054 — Execution-Timeline Delta Study")
    parser.add_argument(
        "--track",
        default="ALL",
        help="Track to run: A, B, C, D, E, or ALL",
    )
    args = parser.parse_args()

    # Load data
    panel = load_panel()
    ticker_trials = load_trial_records()
    aact_deltas = load_aact_deltas()

    # Compute execution features
    panel = compute_execution_features(ticker_trials, aact_deltas, panel)
    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tracks = args.track.upper().split(",") if args.track != "ALL" else ["A", "B", "C", "D", "E"]

    track_a_results = None
    sel_bundles = None
    rnk_bundles = None
    track_c_results = None
    track_d_results = None
    track_e_results = None

    if "A" in tracks:
        track_a_results = run_track_a(panel, snapshots)
        write_signal_ranking_table(
            track_a_results,
            OUTPUT_DIR / "signal_ranking_table.md",
        )
        print(f"\n  Signal ranking table: " f"{OUTPUT_DIR / 'signal_ranking_table.md'}")

    if "B" in tracks:
        sel_bundles = run_selector_bundles(snapshots)
        write_selector_bundle_table(
            sel_bundles,
            OUTPUT_DIR / "selector_bundle_comparison.md",
        )
        print(f"\n  Selector bundle table: " f"{OUTPUT_DIR / 'selector_bundle_comparison.md'}")

        rnk_bundles = run_ranker_bundles(snapshots)
        write_ranker_bundle_table(
            rnk_bundles,
            OUTPUT_DIR / "ranker_bundle_comparison.md",
        )
        print(f"\n  Ranker bundle table: " f"{OUTPUT_DIR / 'ranker_bundle_comparison.md'}")

    if "C" in tracks:
        track_c_results = run_track_c(panel, snapshots)

    if "D" in tracks:
        if track_a_results is None:
            print("  Track D requires Track A. Running A first...")
            track_a_results = run_track_a(panel, snapshots)
        track_d_results = run_track_d(panel, snapshots, track_a_results)

    if "E" in tracks:
        track_e_results = run_track_e(panel, snapshots)

    # Write master results
    write_master_results(
        track_a_results or [],
        sel_bundles or [],
        rnk_bundles or [],
        track_c_results or {},
        track_d_results or {},
        track_e_results or {},
        OUTPUT_DIR / "master_results.json",
    )
    print(f"\nMaster results: {OUTPUT_DIR / 'master_results.json'}")

    # Print final summary
    print(f"\n{'=' * 70}")
    print("STUDY COMPLETE")
    print(f"{'=' * 70}")

    if track_a_results:
        verdicts = defaultdict(int)
        for c in track_a_results:
            verdicts[c["verdict"]] += 1
        print(f"\nTrack A verdicts: {dict(verdicts)}")
        promote = [c for c in track_a_results if c["verdict"] == "PROMOTE_CANDIDATE"]
        shadow = [c for c in track_a_results if c["verdict"] == "SHADOW"]
        if promote:
            print(f"  PROMOTE candidates: " f"{[c['signal'] for c in promote]}")
        if shadow:
            print(f"  SHADOW: {[c['signal'] for c in shadow]}")

    if sel_bundles:
        best = max(
            sel_bundles,
            key=lambda x: x["top_30"]["63"].get("improvement_pp") or -999,
        )
        h = best["top_30"]["63"]
        print(
            f"\nBest selector bundle: {best['bundle_name']} "
            f"({h.get('improvement_pp', '?')}pp, "
            f"t={h.get('improvement_tstat', '?')})"
        )
        inc = next(
            (b for b in sel_bundles if b["bundle_name"] == "S0_incumbent_B6"),
            None,
        )
        if inc:
            ih = inc["top_30"]["63"]
            print(f"  Incumbent (B6): {ih.get('improvement_pp', '?')}pp")

    if rnk_bundles:
        best_r = max(
            rnk_bundles,
            key=lambda x: x["top_30"]["63"].get("ic_mean") or -999,
        )
        hr = best_r["top_30"]["63"]
        print(
            f"\nBest ranker bundle: {best_r['bundle_name']} "
            f"(IC={hr.get('ic_mean', '?')}, "
            f"RW-EW net={hr.get('rw_minus_ew_net_pp', '?')}pp)"
        )

    if track_e_results:
        incremental = [s for s, v in track_e_results.items() if v.get("incremental") in ("YES", "WEAK")]
        if incremental:
            print(f"\nIncremental to institutional: {incremental}")
        else:
            print("\nNo execution signal is incremental to institutional.")

    print(f"\nAll artifacts in: {OUTPUT_DIR}")
    print("Done.")


if __name__ == "__main__":
    main()
