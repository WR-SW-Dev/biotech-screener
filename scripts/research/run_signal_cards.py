#!/usr/bin/env python3
"""Spec 049 Phase 2 — Univariate signal cards.

For every numeric signal in the research panel, compute four evaluation
passes and write a signal card (JSON + Markdown).

Pass A — Gate utility:     does the signal separate winners from losers?
Pass B — Selector utility: does sorting by this signal improve top-K quality?
Pass C — Ranker utility:   does it improve ordering inside the actual top-K?
Pass D — Regime stability: do the above effects survive regime splits?

Usage:
    python3 scripts/research/run_signal_cards.py
    python3 scripts/research/run_signal_cards.py --signals inst_delta_z,clinical_score_v2_z
    python3 scripts/research/run_signal_cards.py --top-n 30 --horizons 20,63
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"

SCHEMA_VERSION = "signal_card.v1"

# Cost model (from ranker_evaluation_harness.py)
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000  # decimal per month

# Import role taxonomy from panel builder
from build_signal_research_panel import _build_role_map

# ── Helpers ───────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    """Spearman rank correlation between two numeric lists."""
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

    rx = _rank(x)
    ry = _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def _safe_mean(vals: List[float]) -> Optional[float]:
    return statistics.mean(vals) if vals else None


def _safe_stdev(vals: List[float]) -> Optional[float]:
    return statistics.stdev(vals) if len(vals) >= 2 else None


def _safe_ir(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    return m / s if s > 1e-9 else None


def _safe_tstat(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s < 1e-9:
        return None
    return m / (s / len(vals) ** 0.5)


def _hit_rate(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(1 for v in vals if v > 0) / len(vals)


# ── Data loading ──────────────────────────────────────────────────────


def load_panel() -> List[Dict[str, str]]:
    """Load the research panel CSV."""
    with open(PANEL_CSV) as f:
        return list(csv.DictReader(f))


def group_by_snapshot(panel: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """Group panel rows by snapshot_date."""
    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


def find_numeric_signals(panel: List[Dict[str, str]], min_nonzero_pct: float = 5.0) -> List[str]:
    """Identify columns with enough numeric, non-zero variation to test."""
    # Skip metadata / label columns
    skip = {
        "snapshot_date",
        "ticker",
        "company_name",
        "actionable_rank",
        "eligible",
        "in_top_20",
        "in_top_30",
        "regime_20d",
        "regime_63d",
        "eligible_ew_ret_20d",
        "eligible_ew_ret_63d",
    }
    skip.update(k for k in panel[0].keys() if k.startswith("fwd_") or k.startswith("xbi_"))

    n_sample = min(500, len(panel))
    sample = panel[:n_sample]
    candidates = []

    for col in panel[0].keys():
        if col in skip:
            continue
        n_numeric = 0
        n_nonzero = 0
        vals_seen = set()
        for row in sample:
            v = _sf(row.get(col), default=None)
            if v is not None:
                n_numeric += 1
                if v != 0.0:
                    n_nonzero += 1
                vals_seen.add(v)

        pct_numeric = n_numeric / n_sample * 100
        pct_nonzero = n_nonzero / n_sample * 100
        n_unique = len(vals_seen)

        # Need: reasonably numeric, some variance, some nonzero
        if pct_numeric >= 20 and n_unique >= 3 and pct_nonzero >= min_nonzero_pct:
            candidates.append(col)

    return sorted(candidates)


# ── Pass A: Gate utility ──────────────────────────────────────────────


def pass_a_gate(
    snapshots: Dict[str, List[Dict[str, str]]],
    signal: str,
    horizons: List[int],
) -> Dict[str, Any]:
    """Does this signal separate winners from losers?

    Split eligible names into above-median vs below-median on signal,
    compare forward excess returns.
    """
    results: Dict[str, Any] = {"pass": "A_gate", "horizons": {}}

    for h in horizons:
        fwd_col = f"fwd_excess_xbi_{h}d"
        above_excess: List[float] = []
        below_excess: List[float] = []
        n_periods = 0

        for snap_date, rows in snapshots.items():
            # Eligible names with both signal and forward return
            eligible = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sig_val = _sf(r.get(signal), default=None)
                fwd_val = _sf(r.get(fwd_col), default=None)
                if sig_val is not None and fwd_val is not None:
                    eligible.append((sig_val, fwd_val))

            if len(eligible) < 10:
                continue

            n_periods += 1
            # Median split
            sig_vals = sorted(e[0] for e in eligible)
            median = sig_vals[len(sig_vals) // 2]

            above = [fwd for sig, fwd in eligible if sig > median]
            below = [fwd for sig, fwd in eligible if sig <= median]

            if above:
                above_excess.append(statistics.mean(above))
            if below:
                below_excess.append(statistics.mean(below))

        above_mean = _safe_mean(above_excess)
        below_mean = _safe_mean(below_excess)
        spread = (above_mean - below_mean) if (above_mean is not None and below_mean is not None) else None

        results["horizons"][str(h)] = {
            "above_median_mean_excess": _r(above_mean),
            "below_median_mean_excess": _r(below_mean),
            "spread_pp": _r(spread * 100 if spread is not None else None),
            "n_periods": n_periods,
            "above_hit_rate": _r(_hit_rate(above_excess)),
            "below_hit_rate": _r(_hit_rate(below_excess)),
        }

    return results


# ── Pass B: Selector utility ─────────────────────────────────────────


def pass_b_selector(
    snapshots: Dict[str, List[Dict[str, str]]],
    signal: str,
    horizons: List[int],
    top_ns: List[int],
) -> Dict[str, Any]:
    """Does sorting eligible names by this signal improve top-K quality?

    Compare: signal-sorted top-K EW vs baseline (actionable_rank) top-K EW.
    """
    results: Dict[str, Any] = {"pass": "B_selector", "top_ns": {}}

    for top_n in top_ns:
        results["top_ns"][str(top_n)] = {"horizons": {}}

        for h in horizons:
            fwd_col = f"fwd_excess_xbi_{h}d"
            baseline_excess: List[float] = []
            signal_excess: List[float] = []
            improvement: List[float] = []
            ic_vals: List[float] = []
            n_periods = 0

            for snap_date, rows in snapshots.items():
                # Eligible names with forward returns
                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fwd_val = _sf(r.get(fwd_col), default=None)
                    rank_val = _sf(r.get("actionable_rank"), default=None)
                    sig_val = _sf(r.get(signal), default=None)
                    if fwd_val is not None and rank_val is not None:
                        eligible.append(
                            {
                                "fwd": fwd_val,
                                "rank": rank_val,
                                "sig": sig_val,
                            }
                        )

                if len(eligible) < top_n:
                    continue

                # Baseline: top-K by actionable_rank
                by_rank = sorted(eligible, key=lambda x: x["rank"])
                baseline_topk = by_rank[:top_n]
                baseline_ret = statistics.mean(e["fwd"] for e in baseline_topk)
                baseline_excess.append(baseline_ret)

                # Signal-sorted: top-K by signal (higher is better by default)
                with_signal = [e for e in eligible if e["sig"] is not None]
                if len(with_signal) < top_n:
                    continue

                n_periods += 1
                by_signal = sorted(with_signal, key=lambda x: -x["sig"])
                signal_topk = by_signal[:top_n]
                signal_ret = statistics.mean(e["fwd"] for e in signal_topk)
                signal_excess.append(signal_ret)

                delta = signal_ret - baseline_ret
                improvement.append(delta)

                # Full-universe IC: signal vs forward return (all eligible)
                ic = spearman_ic(
                    [e["sig"] for e in with_signal],
                    [e["fwd"] for e in with_signal],
                )
                if ic is not None:
                    ic_vals.append(ic)

            results["top_ns"][str(top_n)]["horizons"][str(h)] = {
                "baseline_mean_excess_pp": _r(_pp(_safe_mean(baseline_excess))),
                "signal_mean_excess_pp": _r(_pp(_safe_mean(signal_excess))),
                "improvement_pp": _r(_pp(_safe_mean(improvement))),
                "improvement_hit_rate": _r(_hit_rate(improvement)),
                "improvement_ir": _r(_safe_ir([v * 100 for v in improvement] if improvement else [])),
                "improvement_tstat": _r(_safe_tstat([v * 100 for v in improvement] if improvement else [])),
                "universe_ic_mean": _r(_safe_mean(ic_vals)),
                "universe_ic_tstat": _r(_safe_tstat(ic_vals)),
                "universe_ic_hit_rate": _r(_hit_rate(ic_vals)),
                "n_periods": n_periods,
            }

    return results


# ── Pass C: Ranker utility ───────────────────────────────────────────


def pass_c_ranker(
    snapshots: Dict[str, List[Dict[str, str]]],
    signal: str,
    horizons: List[int],
    top_ns: List[int],
) -> Dict[str, Any]:
    """Does this signal improve ordering INSIDE the actual top-K?

    Within names that are already in the DEM top-K (by actionable_rank),
    compute IC, RW vs EW, and quintile spreads.
    """
    results: Dict[str, Any] = {"pass": "C_ranker", "top_ns": {}}

    for top_n in top_ns:
        results["top_ns"][str(top_n)] = {"horizons": {}}

        for h in horizons:
            fwd_col = f"fwd_ret_{h}d"
            ic_vals: List[float] = []
            ew_rets: List[float] = []
            rw_rets: List[float] = []
            rw_minus_ew: List[float] = []
            top_q_rets: List[float] = []
            bot_q_rets: List[float] = []
            n_periods = 0
            coverage_vals: List[float] = []

            for snap_date, rows in snapshots.items():
                # Names in actual top-K
                topk = []
                for r in rows:
                    rank_val = _sf(r.get("actionable_rank"), default=None)
                    if rank_val is None or rank_val > top_n:
                        continue
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fwd_val = _sf(r.get(fwd_col), default=None)
                    sig_val = _sf(r.get(signal), default=None)
                    if fwd_val is not None:
                        topk.append({"fwd": fwd_val, "sig": sig_val, "rank": rank_val})

                if len(topk) < 5:
                    continue

                # Coverage
                with_signal = [t for t in topk if t["sig"] is not None]
                cov = len(with_signal) / len(topk)
                coverage_vals.append(cov)

                if len(with_signal) < 5:
                    continue

                n_periods += 1

                # EW return (all top-K with returns)
                ew = statistics.mean(t["fwd"] for t in topk)
                ew_rets.append(ew)

                # IC within top-K
                ic = spearman_ic(
                    [t["sig"] for t in with_signal],
                    [t["fwd"] for t in with_signal],
                )
                if ic is not None:
                    ic_vals.append(ic)

                # Rank-weighted return
                sorted_by_sig = sorted(with_signal, key=lambda x: -x["sig"])
                n_s = len(sorted_by_sig)
                weights = [(n_s - i) for i in range(n_s)]
                w_sum = sum(weights)
                rw = sum(weights[i] * sorted_by_sig[i]["fwd"] for i in range(n_s)) / w_sum
                rw_rets.append(rw)
                rw_minus_ew.append(rw - ew)

                # Quintile spread
                q_size = max(1, n_s // 5)
                top_q = sorted_by_sig[:q_size]
                bot_q = sorted_by_sig[-q_size:]
                top_q_rets.append(statistics.mean(t["fwd"] for t in top_q))
                bot_q_rets.append(statistics.mean(t["fwd"] for t in bot_q))

            # Net of costs
            rw_ew_gross = _safe_mean(rw_minus_ew)
            rw_ew_net = (rw_ew_gross - MONTHLY_COST_DRAG) if rw_ew_gross is not None else None

            results["top_ns"][str(top_n)]["horizons"][str(h)] = {
                "ic_mean": _r(_safe_mean(ic_vals)),
                "ic_tstat": _r(_safe_tstat(ic_vals)),
                "ic_hit_rate": _r(_hit_rate(ic_vals)),
                "ic_n": len(ic_vals),
                "ew_mean_ret_pp": _r(_pp(_safe_mean(ew_rets))),
                "rw_mean_ret_pp": _r(_pp(_safe_mean(rw_rets))),
                "rw_minus_ew_gross_pp": _r(_pp(rw_ew_gross)),
                "rw_minus_ew_net_pp": _r(_pp(rw_ew_net)),
                "rw_minus_ew_cum_gross_pp": _r(_pp(sum(rw_minus_ew)) if rw_minus_ew else None),
                "rw_minus_ew_cum_net_pp": _r(
                    _pp(sum(rw_minus_ew) - MONTHLY_COST_DRAG * len(rw_minus_ew)) if rw_minus_ew else None
                ),
                "quintile_top_mean_pp": _r(_pp(_safe_mean(top_q_rets))),
                "quintile_bot_mean_pp": _r(_pp(_safe_mean(bot_q_rets))),
                "quintile_spread_pp": _r(
                    _pp(_safe_mean(top_q_rets)) - _pp(_safe_mean(bot_q_rets))
                    if _safe_mean(top_q_rets) is not None and _safe_mean(bot_q_rets) is not None
                    else None
                ),
                "signal_coverage_mean": _r(_safe_mean(coverage_vals)),
                "n_periods": n_periods,
            }

    return results


# ── Pass D: Regime stability ─────────────────────────────────────────


def pass_d_regime(
    snapshots: Dict[str, List[Dict[str, str]]],
    signal: str,
    horizons: List[int],
    top_n: int,
) -> Dict[str, Any]:
    """Regime-split the ranker metrics (IC and RW-EW) at 63d horizon."""
    results: Dict[str, Any] = {"pass": "D_regime", "regimes": {}}

    for regime_label in ["bear", "neutral", "bull"]:
        regime_ic: List[float] = []
        regime_rw_ew: List[float] = []
        regime_excess: List[float] = []
        n_periods = 0

        for snap_date, rows in snapshots.items():
            # Check regime for this snapshot
            sample_regime = None
            for r in rows:
                sample_regime = r.get("regime_63d")
                if sample_regime:
                    break
            if sample_regime != regime_label:
                continue

            # Within-top-K ranker metrics (same as Pass C but filtered by regime)
            topk = []
            for r in rows:
                rank_val = _sf(r.get("actionable_rank"), default=None)
                if rank_val is None or rank_val > top_n:
                    continue
                if _sf(r.get("eligible")) != 1.0:
                    continue
                fwd_val = _sf(r.get("fwd_ret_63d"), default=None)
                sig_val = _sf(r.get(signal), default=None)
                if fwd_val is not None:
                    topk.append({"fwd": fwd_val, "sig": sig_val})

            with_signal = [t for t in topk if t["sig"] is not None]
            if len(with_signal) < 5:
                continue

            n_periods += 1

            # IC
            ic = spearman_ic(
                [t["sig"] for t in with_signal],
                [t["fwd"] for t in with_signal],
            )
            if ic is not None:
                regime_ic.append(ic)

            # RW - EW
            ew = statistics.mean(t["fwd"] for t in topk) if topk else 0
            sorted_by_sig = sorted(with_signal, key=lambda x: -x["sig"])
            n_s = len(sorted_by_sig)
            weights = [(n_s - i) for i in range(n_s)]
            w_sum = sum(weights)
            rw = sum(weights[i] * sorted_by_sig[i]["fwd"] for i in range(n_s)) / w_sum
            regime_rw_ew.append(rw - ew)

            # Excess vs XBI
            fwd_xbi_vals = [
                _sf(r.get("fwd_excess_xbi_63d"), default=None)
                for r in rows
                if _sf(r.get("actionable_rank"), default=999) <= top_n and _sf(r.get("eligible")) == 1.0
            ]
            fwd_xbi_clean = [v for v in fwd_xbi_vals if v is not None]
            if fwd_xbi_clean:
                regime_excess.append(statistics.mean(fwd_xbi_clean))

        results["regimes"][regime_label] = {
            "n_periods": n_periods,
            "ic_mean": _r(_safe_mean(regime_ic)),
            "ic_hit_rate": _r(_hit_rate(regime_ic)),
            "rw_minus_ew_mean_pp": _r(_pp(_safe_mean(regime_rw_ew))),
            "top_k_excess_xbi_pp": _r(_pp(_safe_mean(regime_excess))),
        }

    return results


# ── Formatting helpers ────────────────────────────────────────────────


def _r(v, digits=4):
    """Round for JSON output."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, digits)


def _pp(v):
    """Convert decimal to percentage points."""
    if v is None:
        return None
    return v * 100


# ── Verdict logic ─────────────────────────────────────────────────────


def compute_verdict(card: Dict[str, Any]) -> str:
    """Assign REJECT / HOLD / SHADOW / PROMOTE based on evidence."""
    role = card.get("role", "other")

    # Check selector metrics (Pass B)
    pass_b = card.get("pass_b", {})
    best_improvement = None
    best_tstat = None
    for tn, tn_data in pass_b.get("top_ns", {}).items():
        for h, h_data in tn_data.get("horizons", {}).items():
            imp = h_data.get("improvement_pp")
            ts = h_data.get("improvement_tstat")
            if imp is not None:
                if best_improvement is None or imp > best_improvement:
                    best_improvement = imp
            if ts is not None:
                if best_tstat is None or abs(ts) > abs(best_tstat):
                    best_tstat = ts

    # Check ranker metrics (Pass C)
    pass_c = card.get("pass_c", {})
    best_ic = None
    best_rw_net = None
    for tn, tn_data in pass_c.get("top_ns", {}).items():
        for h, h_data in tn_data.get("horizons", {}).items():
            ic = h_data.get("ic_mean")
            rw_net = h_data.get("rw_minus_ew_net_pp")
            if ic is not None:
                if best_ic is None or ic > best_ic:
                    best_ic = ic
            if rw_net is not None:
                if best_rw_net is None or rw_net > best_rw_net:
                    best_rw_net = rw_net

    # Check regime stability (Pass D)
    pass_d = card.get("pass_d", {})
    regime_ics = []
    for reg, reg_data in pass_d.get("regimes", {}).items():
        ic = reg_data.get("ic_mean")
        if ic is not None:
            regime_ics.append(ic)

    regime_stable = len(regime_ics) >= 2 and all(ic > -0.05 for ic in regime_ics)

    # Coverage check
    coverage = card.get("coverage_pct", 0)

    # Decision logic
    if coverage < 10:
        return "REJECT"

    if role in ("gate",):
        # Gates evaluated mainly on Pass A spread
        pass_a = card.get("pass_a", {})
        has_spread = False
        for h, h_data in pass_a.get("horizons", {}).items():
            spread = h_data.get("spread_pp")
            if spread is not None and abs(spread) > 0.5:
                has_spread = True
        return "SHADOW" if has_spread else "HOLD"

    if role in ("selector",):
        if best_improvement is not None and best_improvement > 0.2:
            if best_tstat is not None and abs(best_tstat) >= 2.0:
                return "PROMOTE"
            elif best_tstat is not None and abs(best_tstat) >= 1.0:
                return "SHADOW"
            else:
                return "HOLD"
        elif best_improvement is not None and best_improvement > 0:
            return "HOLD"
        else:
            return "REJECT"

    if role in ("ranker",):
        if best_ic is not None and best_ic > 0:
            if best_rw_net is not None and best_rw_net > 0:
                if regime_stable:
                    return "PROMOTE"
                return "SHADOW"
            return "HOLD"
        return "REJECT"

    # composite / modifier / other
    if best_ic is not None and best_ic > 0 and best_rw_net is not None and best_rw_net > 0:
        return "SHADOW"
    if best_improvement is not None and best_improvement > 0:
        return "HOLD"
    return "REJECT"


def describe_failure(card: Dict[str, Any]) -> str:
    """One-line failure mode summary."""
    verdict = card.get("decision", "")
    coverage = card.get("coverage_pct", 0)

    if coverage < 10:
        return f"Coverage too low ({coverage:.0f}%)"

    if verdict == "REJECT":
        parts = []
        # Check selector
        pass_b = card.get("pass_b", {})
        for tn, tn_data in pass_b.get("top_ns", {}).items():
            for h, h_data in tn_data.get("horizons", {}).items():
                imp = h_data.get("improvement_pp")
                if imp is not None and imp <= 0:
                    parts.append(f"selector improvement ≤ 0 at h{h}")
        # Check ranker
        pass_c = card.get("pass_c", {})
        for tn, tn_data in pass_c.get("top_ns", {}).items():
            for h, h_data in tn_data.get("horizons", {}).items():
                ic = h_data.get("ic_mean")
                if ic is not None and ic <= 0:
                    parts.append(f"IC ≤ 0 at h{h} top-{tn}")
        return "; ".join(parts[:3]) if parts else "No positive evidence"

    return ""


# ── Card generation ───────────────────────────────────────────────────


def generate_card(
    signal: str,
    snapshots: Dict[str, List[Dict[str, str]]],
    horizons: List[int],
    top_ns: List[int],
    role_map: Dict[str, str],
    panel: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Generate a complete signal card."""
    role = role_map.get(signal, "other")

    # Coverage
    n_total = len(panel)
    n_present = sum(1 for r in panel if r.get(signal, "") not in ("", None))
    n_numeric = 0
    n_nonzero = 0
    for r in panel:
        v = _sf(r.get(signal), default=None)
        if v is not None:
            n_numeric += 1
            if v != 0.0:
                n_nonzero += 1

    coverage_pct = n_present / n_total * 100 if n_total else 0
    numeric_pct = n_numeric / n_total * 100 if n_total else 0
    nonzero_pct = n_nonzero / n_total * 100 if n_total else 0

    card: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "signal_name": signal,
        "role": role,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": n_total,
        "n_snapshots": len(snapshots),
        "coverage_pct": round(coverage_pct, 1),
        "numeric_pct": round(numeric_pct, 1),
        "nonzero_pct": round(nonzero_pct, 1),
    }

    # Run passes
    card["pass_a"] = pass_a_gate(snapshots, signal, horizons)
    card["pass_b"] = pass_b_selector(snapshots, signal, horizons, top_ns)
    card["pass_c"] = pass_c_ranker(snapshots, signal, horizons, top_ns)
    card["pass_d"] = pass_d_regime(snapshots, signal, horizons, top_n=top_ns[-1])

    # Verdict
    card["decision"] = compute_verdict(card)
    card["failure_mode"] = describe_failure(card)

    return card


def write_card_md(card: Dict[str, Any], path: Path) -> None:
    """Write human-readable signal card markdown."""
    sig = card["signal_name"]
    lines = [
        f"# Signal Card: `{sig}`\n",
        f"**Role:** {card['role']}  ",
        f"**Decision:** {card['decision']}  ",
        f"**Generated:** {card['generated_at'][:10]}\n",
        "## Coverage\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Present | {card['coverage_pct']}% |",
        f"| Numeric | {card['numeric_pct']}% |",
        f"| Nonzero | {card['nonzero_pct']}% |",
        f"| Rows | {card['n_rows']:,} |",
        f"| Snapshots | {card['n_snapshots']} |\n",
    ]

    # Pass A
    lines.append("## Pass A — Gate utility\n")
    lines.append("| Horizon | Above med. (pp) | Below med. (pp) | Spread (pp) | N |")
    lines.append("|---------|----------------|----------------|-------------|---|")
    for h, hd in card["pass_a"]["horizons"].items():
        lines.append(
            f"| {h}d | {_fmt(hd['above_median_mean_excess'])} "
            f"| {_fmt(hd['below_median_mean_excess'])} "
            f"| {_fmt(hd['spread_pp'])} | {hd['n_periods']} |"
        )

    # Pass B
    lines.append("\n## Pass B — Selector utility\n")
    for tn, tn_data in card["pass_b"]["top_ns"].items():
        lines.append(f"### Top-{tn}\n")
        lines.append("| Horizon | Baseline (pp) | Signal (pp) | Δ (pp) | Δ hit% | Δ t-stat | Univ IC | N |")
        lines.append("|---------|--------------|------------|--------|--------|----------|---------|---|")
        for h, hd in tn_data["horizons"].items():
            lines.append(
                f"| {h}d | {_fmt(hd['baseline_mean_excess_pp'])} "
                f"| {_fmt(hd['signal_mean_excess_pp'])} "
                f"| {_fmt(hd['improvement_pp'])} "
                f"| {_fmt_pct(hd['improvement_hit_rate'])} "
                f"| {_fmt(hd['improvement_tstat'])} "
                f"| {_fmt(hd['universe_ic_mean'])} "
                f"| {hd['n_periods']} |"
            )

    # Pass C
    lines.append("\n## Pass C — Ranker utility (within top-K)\n")
    for tn, tn_data in card["pass_c"]["top_ns"].items():
        lines.append(f"### Top-{tn}\n")
        lines.append("| Horizon | IC | IC t | IC hit% | RW−EW gross (pp) | RW−EW net (pp) | Q spread (pp) | Cov | N |")
        lines.append("|---------|-----|------|---------|-----------------|---------------|--------------|-----|---|")
        for h, hd in tn_data["horizons"].items():
            lines.append(
                f"| {h}d | {_fmt(hd['ic_mean'])} "
                f"| {_fmt(hd['ic_tstat'])} "
                f"| {_fmt_pct(hd['ic_hit_rate'])} "
                f"| {_fmt(hd['rw_minus_ew_gross_pp'])} "
                f"| {_fmt(hd['rw_minus_ew_net_pp'])} "
                f"| {_fmt(hd.get('quintile_spread_pp'))} "
                f"| {_fmt_pct(hd.get('signal_coverage_mean'))} "
                f"| {hd['n_periods']} |"
            )

    # Pass D
    lines.append("\n## Pass D — Regime stability (63d, top-30)\n")
    lines.append("| Regime | IC | RW−EW (pp) | Excess XBI (pp) | N |")
    lines.append("|--------|-----|-----------|----------------|---|")
    for reg, rd in card["pass_d"]["regimes"].items():
        lines.append(
            f"| {reg} | {_fmt(rd['ic_mean'])} "
            f"| {_fmt(rd['rw_minus_ew_mean_pp'])} "
            f"| {_fmt(rd['top_k_excess_xbi_pp'])} "
            f"| {rd['n_periods']} |"
        )

    if card["failure_mode"]:
        lines.append("\n## Failure mode\n")
        lines.append(card["failure_mode"])

    lines.append("")
    path.write_text("\n".join(lines))


def _fmt(v, digits=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v*100:.0f}%" if isinstance(v, float) and v <= 1.0 else f"{v:.0f}%"


# ── Manifest ──────────────────────────────────────────────────────────


def write_manifest(cards: List[Dict[str, Any]], path: Path) -> None:
    """Write signal_manifest.json — role + verdict for every tested signal."""
    manifest = {
        "schema": "signal_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_signals": len(cards),
        "signals": {},
    }
    for c in cards:
        manifest["signals"][c["signal_name"]] = {
            "role": c["role"],
            "decision": c["decision"],
            "coverage_pct": c["coverage_pct"],
            "failure_mode": c["failure_mode"],
        }

    # Summary counts
    verdicts = defaultdict(int)
    for c in cards:
        verdicts[c["decision"]] += 1
    manifest["verdict_summary"] = dict(verdicts)

    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)


def write_summary_md(cards: List[Dict[str, Any]], path: Path) -> None:
    """Write a single-page summary of all signal cards."""
    lines = [
        "# Signal Card Summary — Spec 049 Phase 2\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Signals tested: {len(cards)}\n",
    ]

    # Verdict summary
    verdicts = defaultdict(list)
    for c in cards:
        verdicts[c["decision"]].append(c["signal_name"])

    lines.append("## Verdict summary\n")
    for v in ["PROMOTE", "SHADOW", "HOLD", "REJECT"]:
        names = verdicts.get(v, [])
        lines.append(f"**{v}** ({len(names)}): {', '.join(f'`{n}`' for n in names[:15])}")
        if len(names) > 15:
            lines.append(f"  ... and {len(names) - 15} more")
        lines.append("")

    # Top signals table
    lines.append("## Top signals by selector improvement (63d, top-30)\n")
    lines.append("| Signal | Role | Verdict | Cov% | Δ top-30 (pp) | t-stat | IC (top-30) | RW−EW net (pp) |")
    lines.append("|--------|------|---------|------|--------------|--------|-------------|---------------|")

    # Extract key metrics for sorting
    ranked = []
    for c in cards:
        imp_63 = None
        ts_63 = None
        ic_30_63 = None
        rw_net_30_63 = None

        pb = c.get("pass_b", {}).get("top_ns", {}).get("30", {}).get("horizons", {}).get("63", {})
        imp_63 = pb.get("improvement_pp")
        ts_63 = pb.get("improvement_tstat")

        pc = c.get("pass_c", {}).get("top_ns", {}).get("30", {}).get("horizons", {}).get("63", {})
        ic_30_63 = pc.get("ic_mean")
        rw_net_30_63 = pc.get("rw_minus_ew_net_pp")

        ranked.append((c, imp_63, ts_63, ic_30_63, rw_net_30_63))

    ranked.sort(key=lambda x: x[1] if x[1] is not None else -999, reverse=True)

    for c, imp, ts, ic, rw in ranked[:40]:
        lines.append(
            f"| `{c['signal_name']}` | {c['role']} | {c['decision']} "
            f"| {c['coverage_pct']:.0f} | {_fmt(imp)} | {_fmt(ts)} "
            f"| {_fmt(ic)} | {_fmt(rw)} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Run univariate signal cards (Spec 049)")
    parser.add_argument("--signals", default=None, help="Comma-separated signal names (default: auto-detect)")
    parser.add_argument("--top-n", default="20,30", help="Top-N values (comma-separated)")
    parser.add_argument("--horizons", default="20,63", help="Horizons in trading days (comma-separated)")
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    top_ns = [int(n) for n in args.top_n.split(",")]

    print("Loading research panel...")
    panel = load_panel()
    print(f"  {len(panel):,} rows")

    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots")

    role_map = _build_role_map()

    if args.signals:
        signals = [s.strip() for s in args.signals.split(",")]
    else:
        print("Auto-detecting numeric signals...")
        signals = find_numeric_signals(panel)
        print(f"  {len(signals)} testable signals found")

    print(f"\nRunning {len(signals)} signal cards (horizons={horizons}, top_ns={top_ns})...")
    cards: List[Dict[str, Any]] = []

    for i, signal in enumerate(signals):
        if i % 10 == 0:
            print(f"  [{i+1}/{len(signals)}] {signal}...")

        card = generate_card(signal, snapshots, horizons, top_ns, role_map, panel)
        cards.append(card)

        # Write individual card
        card_dir = OUTPUT_DIR / signal
        card_dir.mkdir(parents=True, exist_ok=True)
        with open(card_dir / "signal_card.json", "w") as f:
            json.dump(card, f, indent=2, default=str)
        write_card_md(card, card_dir / "signal_card.md")

    # Write manifest + summary
    write_manifest(cards, OUTPUT_DIR / "signal_manifest.json")
    write_summary_md(cards, OUTPUT_DIR / "signal_cards_summary.md")

    # Print verdict summary
    verdicts = defaultdict(list)
    for c in cards:
        verdicts[c["decision"]].append(c["signal_name"])

    print(f"\n{'='*60}")
    print("SIGNAL CARD RESULTS")
    print(f"{'='*60}")
    for v in ["PROMOTE", "SHADOW", "HOLD", "REJECT"]:
        names = verdicts.get(v, [])
        print(f"\n  {v} ({len(names)}):")
        for n in names:
            print(f"    - {n}")

    print("\nOutputs:")
    print("  Cards:    output/signals/<signal_name>/signal_card.json + .md")
    print("  Manifest: output/signals/signal_manifest.json")
    print("  Summary:  output/signals/signal_cards_summary.md")
    print("\nDone.")


if __name__ == "__main__":
    main()
