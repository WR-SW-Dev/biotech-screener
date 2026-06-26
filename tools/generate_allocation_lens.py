#!/usr/bin/env python3
"""Generate daily biotech allocation lens artifact.

Reads existing pipeline outputs (rankings snapshot, ops_digest, catalyst_delta,
EES scorecard, Scientific Cartography) and produces an attention-routing artifact
for human review.

Classification: ALLOCATION_LENS_STEP_1_ATTENTION_ROUTING_NO_MODEL_CHANGE

Hard constraints:
  NO_FINAL_SCORE_CHANGE  NO_RANKER_CHANGE  NO_SELECTOR_CHANGE  NO_SIZING_CHANGE
  WRITE: artifacts/surveillance/ only
  READ: data/snapshots/, artifacts/catalyst_delta/, artifacts/ops_digest/,
        artifacts/readiness/, artifacts/scientific_cartography/

Usage:
    python3 tools/generate_allocation_lens.py --as-of-date 2026-06-26
    python3 tools/generate_allocation_lens.py --as-of-date 2026-06-26 \\
        --rankings data/snapshots/2026-06-26/rankings.csv \\
        --out-md artifacts/surveillance/2026-06-26_allocation_lens.md \\
        --out-json artifacts/surveillance/2026-06-26_allocation_lens.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"

GOVERNANCE_CLASSIFICATION = "ALLOCATION_LENS_STEP_1_ATTENTION_ROUTING_NO_MODEL_CHANGE"
ARTIFACT_SCHEMA = "allocation_lens_v1"

BUCKET_NAMES = [
    "near_term_binary_catalyst",
    "derisked_commercial",
    "expectation_gap_dislocation",
    "elite_manager_smid",
    "cash_poor_platform",
    "mechanism_theme_basket",
]

REVIEW_ACTIONS = frozenset(
    [
        "PROMOTE_TO_REVIEW",
        "MONITOR",
        "SUPPRESS",
        "REFRESH_EVIDENCE",
        "WAIT_FOR_CATALYST",
        "CHECK_EXPECTATION_GAP",
        "CHECK_FINANCING_RISK",
        "CHECK_MECHANISM_CLUSTER",
    ]
)

_FORBIDDEN_REVIEW_WORDS = frozenset(
    ["sell", "purchase", "place order", "execute order", "enter position", "exit position"]
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: object) -> float | None:
    if val in (None, "", "None", "nan"):
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(val: object) -> int | None:
    f = _safe_float(val)
    return int(f) if f is not None else None


def _parse_date(s: str) -> date | None:
    if not s or s in ("None", "nan"):
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _latest_file(directory: Path, pattern: str) -> Path | None:
    """Find the newest file matching pattern, preferring filename-parsed date over mtime."""
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        return None

    def _sort_key(p: Path) -> tuple:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        if m:
            return (1, m.group(1), p.name)
        return (0, str(p.stat().st_mtime), p.name)

    return sorted(candidates, key=_sort_key)[-1]


def _latest_dated_dir(base_dir: Path) -> Path | None:
    """Find the newest YYYY-MM-DD* subdirectory."""
    candidates = [d for d in base_dir.iterdir() if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", d.name)]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.name)


def _latest_snapshot_rankings(as_of_date: str | None = None) -> Path | None:
    """Resolve rankings.csv from data/snapshots/<date>/rankings.csv.

    If as_of_date given, tries exact date then walks back up to 7 days.
    Otherwise uses the lexicographically latest dated dir.
    """
    if not SNAPSHOTS_DIR.is_dir():
        return None
    if as_of_date:
        target = _parse_date(as_of_date)
        if target:
            for delta in range(8):
                d = target - timedelta(days=delta)
                p = SNAPSHOTS_DIR / d.strftime("%Y-%m-%d") / "rankings.csv"
                if p.exists():
                    return p
    latest_dir = _latest_dated_dir(SNAPSHOTS_DIR)
    if latest_dir:
        p = latest_dir / "rankings.csv"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_rankings(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def load_catalyst_delta(as_of_date: str, artifacts_dir: Path) -> dict | None:
    delta_dir = artifacts_dir / "catalyst_delta"
    if not delta_dir.is_dir():
        return None
    exact = delta_dir / f"{as_of_date}_delta.json"
    if exact.exists():
        return json.loads(exact.read_text())
    p = _latest_file(delta_dir, "*_delta.json")
    return json.loads(p.read_text()) if p else None


def load_ops_digest(as_of_date: str, artifacts_dir: Path) -> dict | None:
    digest_dir = artifacts_dir / "ops_digest"
    if not digest_dir.is_dir():
        return None
    exact = digest_dir / f"{as_of_date}_digest.json"
    if exact.exists():
        return json.loads(exact.read_text())
    p = _latest_file(digest_dir, "*_digest.json")
    return json.loads(p.read_text()) if p else None


def load_ees_scorecard(as_of_date: str, artifacts_dir: Path) -> dict | None:
    readiness_dir = artifacts_dir / "readiness"
    if not readiness_dir.is_dir():
        return None
    exact = readiness_dir / f"scorecard_{as_of_date}.json"
    if exact.exists():
        return json.loads(exact.read_text())
    p = _latest_file(readiness_dir, "scorecard_*.json")
    return json.loads(p.read_text()) if p else None


def load_cartography(artifacts_dir: Path) -> list[dict] | None:
    cart_dir = artifacts_dir / "scientific_cartography"
    if not cart_dir.is_dir():
        return None
    latest_dir = _latest_dated_dir(cart_dir)
    if not latest_dir:
        return None
    lf_path = latest_dir / "landscape_features.jsonl"
    if not lf_path.exists():
        return None
    records: list[dict] = []
    with lf_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------


def assign_bucket(row: dict) -> str:
    """Assign primary attention bucket to a ranked row.

    Buckets are mutually exclusive; assignment order encodes priority.
    Returns one of BUCKET_NAMES.
    """
    runway = row.get("runway_bucket", "")
    stage = row.get("stage_bucket", "")
    cat_days = _safe_float(row.get("catalyst_days"))
    cat_bucket = row.get("catalyst_bucket", "")
    coinvest_tag = row.get("coinvest_tag", "")
    ees_pctile = _safe_float(row.get("ees_v3_pctile"))
    market_cap_mm = _safe_float(row.get("market_cap_mm"))
    priced_move = row.get("priced_move_pct", "")
    tier_dev = row.get("tier_dev", "")

    # Cash-poor platform: financing risk overrides catalyst appeal
    if runway == "short" and stage != "late":
        return "cash_poor_platform"

    # Near-term binary: binary_now or hard catalyst within 60d
    if cat_bucket == "binary_now":
        return "near_term_binary_catalyst"
    if (
        cat_days is not None
        and cat_days <= 60
        and cat_bucket
        in (
            "less_binary",
            "core",
        )
    ):
        return "near_term_binary_catalyst"

    # Expectation gap: strong EES signal with priced-move data available
    if ees_pctile is not None and ees_pctile >= 65.0 and priced_move not in ("", "None", "nan"):
        return "expectation_gap_dislocation"

    # Elite manager SMID: high institutional conviction, not large-cap
    if coinvest_tag:
        try:
            n_elite = int(coinvest_tag.replace("elite_", ""))
            if n_elite >= 10 and market_cap_mm is not None and market_cap_mm < 3000:
                return "elite_manager_smid"
        except ValueError:
            pass

    # Derisked commercial: late-stage Tier A with adequate runway
    if stage == "late" and tier_dev == "A" and runway != "short":
        return "derisked_commercial"

    return "mechanism_theme_basket"


# ---------------------------------------------------------------------------
# Regime assessment
# ---------------------------------------------------------------------------


def assess_regime(
    ops_digest: dict | None,
    ees_scorecard: dict | None,
    rows: list[dict],
) -> dict:
    """Derive regime signals from available pipeline artifacts.

    XBI price, rates, M&A/IPO, and liquidity are not in the current pipeline;
    they are marked 'unavailable' and require manual input.
    """
    n_total = max(len(rows), 1)
    n_short_runway = sum(1 for r in rows if r.get("runway_bucket") == "short")
    pct_short = n_short_runway / n_total

    # Financing window
    if ees_scorecard:
        ees_verdict = ees_scorecard.get("verdict", "")
        if ees_verdict in ("BLOCK", "FAIL"):
            financing_window = "closed"
        elif pct_short > 0.12:
            financing_window = "selective"
        else:
            financing_window = "open"
    else:
        financing_window = "unavailable"

    # Catalyst tape
    catalyst_tape = "unavailable"
    if ops_digest:
        readiness = ops_digest.get("readiness") or {}
        verdict = readiness.get("verdict", "")
        if verdict == "GO":
            catalyst_tape = "rewarding"
        elif verdict in ("HOLD", "WARN"):
            catalyst_tape = "neutral"
        elif verdict in ("BLOCK", "FAIL"):
            catalyst_tape = "punishing"

    return {
        "biotech_beta": "unavailable — check XBI manually",
        "rates_pressure": "unavailable",
        "financing_window": financing_window,
        "ma_ipo_tone": "unavailable",
        "catalyst_tape": catalyst_tape,
        "liquidity": "unavailable",
        "daily_override": {"triggered": False, "reason": None},
    }


# ---------------------------------------------------------------------------
# Daily override triggers
# ---------------------------------------------------------------------------


def check_overrides(catalyst_delta: dict | None, regime: dict) -> dict:
    """Return an override dict if severe catalyst events detected."""
    if not catalyst_delta:
        return {"triggered": False, "reason": None}

    deltas = catalyst_delta.get("deltas") or []

    n_terminated_tier_a = sum(
        1 for d in deltas if "CTGOV_TRIAL_TERMINATED" in (d.get("codes") or []) and d.get("tier") == "A"
    )
    n_phase_changes_tier_a = sum(
        1 for d in deltas if "CTGOV_PHASE_CHANGED" in (d.get("codes") or []) and d.get("tier") == "A"
    )

    if n_terminated_tier_a >= 3:
        return {
            "triggered": True,
            "reason": f"≥3 Tier-A trial terminations today ({n_terminated_tier_a})",
        }
    if n_phase_changes_tier_a >= 10:
        return {
            "triggered": True,
            "reason": (f"≥10 Tier-A phase changes today ({n_phase_changes_tier_a})"),
        }
    return {"triggered": False, "reason": None}


# ---------------------------------------------------------------------------
# Bucket stances
# ---------------------------------------------------------------------------

BUCKET_STANCES_BASE: dict[str, dict] = {
    "near_term_binary_catalyst": {
        "stance": "overweight",
        "reason": "Near-term catalysts with expectation data command review priority",
        "primary_risk": "Event risk; binary outcomes move ±30–50%",
        "review_implication": "Increase review bandwidth",
    },
    "derisked_commercial": {
        "stance": "neutral",
        "reason": "Defensive ballast; lower binary event dependency",
        "primary_risk": "Lower upside relative to binary names",
        "review_implication": "Maintain review bandwidth",
    },
    "expectation_gap_dislocation": {
        "stance": "overweight",
        "reason": "EES signal flags market-vs-model disagreement; expectation gap present",
        "primary_risk": "EES signal may reflect data lag or model-market disagreement",
        "review_implication": "Increase review bandwidth; verify EES evidence quality",
    },
    "elite_manager_smid": {
        "stance": "neutral",
        "reason": "Institutional ownership support present; catalyst path required for upgrade",
        "primary_risk": "Crowding risk; exit impact in thin liquidity",
        "review_implication": "Maintain review bandwidth; monitor for catalyst pull-forward",
    },
    "cash_poor_platform": {
        "stance": "underweight",
        "reason": "Short runway in selective financing window increases dilution probability",
        "primary_risk": "Dilution; binary financing event",
        "review_implication": "Reduce review bandwidth unless new financing evidence appears",
    },
    "mechanism_theme_basket": {
        "stance": "neutral",
        "reason": "Diversified mechanism exposure; no dominant near-term catalyst",
        "primary_risk": "Correlation across similar mechanism lanes",
        "review_implication": "Monitor for catalyst emergence; check mechanism cluster density",
    },
}


def _compute_bucket_stances(regime: dict) -> list[dict]:
    results = []
    for bucket in BUCKET_NAMES:
        base = BUCKET_STANCES_BASE[bucket]
        stance = base["stance"]
        # Regime-driven stance adjustments
        if bucket == "cash_poor_platform" and regime.get("financing_window") == "closed":
            stance = "avoid"
        elif bucket == "near_term_binary_catalyst" and regime.get("catalyst_tape") == "punishing":
            stance = "neutral"
        results.append(
            {
                "bucket": bucket,
                "stance": stance,
                "reason": base["reason"],
                "primary_risk": base["primary_risk"],
                "review_implication": base["review_implication"],
            }
        )
    return results


# ---------------------------------------------------------------------------
# Review budget
# ---------------------------------------------------------------------------


def build_review_budget(
    top_rows: list[dict],
    bucket_assignments: dict[str, str],
    regime: dict,
) -> list[dict]:
    """Prioritize top names for human review with controlled-vocabulary actions."""
    _bucket_order = {
        "near_term_binary_catalyst": 0,
        "expectation_gap_dislocation": 1,
        "elite_manager_smid": 2,
        "derisked_commercial": 3,
        "mechanism_theme_basket": 4,
        "cash_poor_platform": 5,
    }

    def _rank_key(row: dict) -> tuple:
        bucket = bucket_assignments.get(row["ticker"], "mechanism_theme_basket")
        rank = _safe_int(row.get("actionable_rank")) or _safe_int(row.get("composite_rank")) or 9999
        return (_bucket_order.get(bucket, 4), rank)

    sorted_rows = sorted(top_rows, key=_rank_key)

    budget: list[dict] = []
    for i, row in enumerate(sorted_rows[:15]):
        ticker = row["ticker"]
        bucket = bucket_assignments.get(ticker, "mechanism_theme_basket")
        cat_days = _safe_int(row.get("catalyst_days"))
        runway = row.get("runway_bucket", "")
        ees_gate = row.get("ees_v3_gate", "")
        ees_pctile = _safe_float(row.get("ees_v3_pctile"))
        coinvest_tag = row.get("coinvest_tag", "")

        # Controlled-vocabulary action
        if bucket == "cash_poor_platform":
            action = "CHECK_FINANCING_RISK"
        elif bucket == "expectation_gap_dislocation":
            action = "CHECK_EXPECTATION_GAP"
        elif bucket == "near_term_binary_catalyst" and cat_days is not None and cat_days <= 14:
            action = "PROMOTE_TO_REVIEW"
        elif bucket == "near_term_binary_catalyst":
            action = "PROMOTE_TO_REVIEW"
        elif bucket == "elite_manager_smid":
            action = "MONITOR"
        else:
            action = "MONITOR"

        # Supporting signals (no buy/sell language)
        signals: list[str] = []
        if cat_days is not None:
            signals.append(f"catalyst_days={cat_days}")
        if ees_gate == "True" and ees_pctile is not None:
            signals.append(f"ees_pctile={ees_pctile:.1f}")
        if coinvest_tag:
            signals.append(f"coinvest={coinvest_tag}")
        if runway:
            signals.append(f"runway={runway}")

        # Why now
        why_parts: list[str] = []
        if cat_days is not None and cat_days <= 30:
            why_parts.append(f"catalyst in {cat_days}d")
        if bucket == "expectation_gap_dislocation":
            why_parts.append("EES gap signal present")
        if bucket == "cash_poor_platform":
            why_parts.append("short runway — dilution risk")
        if not why_parts:
            why_parts.append(f"{bucket} (rank {i + 1})")
        why_now = "; ".join(why_parts)

        # Model risk
        risk_parts: list[str] = []
        if runway == "short":
            risk_parts.append("financing risk")
        if ees_gate == "False":
            risk_parts.append("EES gate blocked")
        model_risk = "; ".join(risk_parts) if risk_parts else "standard"

        budget.append(
            {
                "priority": i + 1,
                "ticker": ticker,
                "bucket": bucket,
                "why_now": why_now,
                "supporting_signals": signals,
                "model_risk": model_risk,
                "action": action,
            }
        )
    return budget


# ---------------------------------------------------------------------------
# Construction notes
# ---------------------------------------------------------------------------


def build_construction_notes(
    top_rows: list[dict],
    cartography: list[dict] | None,
) -> dict:
    # Stage concentration
    stages = Counter(r.get("stage_bucket", "unknown") for r in top_rows)
    stage_note = "; ".join(f"{s}={n}" for s, n in stages.most_common(4))

    # Catalyst-date cluster: densest 14-day window
    dates: list[date] = []
    for r in top_rows:
        raw = r.get("next_catalyst_date") or r.get("catalyst_date_lower") or ""
        d = _parse_date(raw)
        if d:
            dates.append(d)
    if dates:
        dates_sorted = sorted(dates)
        max_cluster = max(sum(1 for x in dates_sorted if d <= x <= d + timedelta(days=14)) for d in dates_sorted)
        catalyst_date_note = f"{max_cluster} catalysts cluster within 14d window " f"(of {len(dates)} with known dates)"
    else:
        catalyst_date_note = "no catalyst dates available"

    # Financing risk
    n_short = sum(1 for r in top_rows if r.get("runway_bucket") == "short")
    financing_note = f"{n_short}/{len(top_rows)} names have short runway"

    # Mechanism and crowding from cartography
    tickers_in_top = {r["ticker"] for r in top_rows}
    if cartography:
        top_cart = [c for c in cartography if c.get("ticker") in tickers_in_top]
        mechs = Counter(c.get("mechanism_class", "unknown") for c in top_cart if c.get("mechanism_class"))
        mech_note = "; ".join(f"{m}={n}" for m, n in mechs.most_common(3)) if mechs else "no mechanism data"
        high_crowd = [c for c in top_cart if (_safe_float(c.get("mechanism_crowding_score")) or 0) > 0.7]
        crowding_note = f"{len(high_crowd)} names with mechanism_crowding_score >0.7"
    else:
        mech_note = "cartography unavailable"
        crowding_note = "cartography unavailable"

    return {
        "mechanism_concentration": mech_note,
        "stage_concentration": stage_note,
        "catalyst_date_concentration": catalyst_date_note,
        "financing_risk_concentration": financing_note,
        "crowding": crowding_note,
        "liquidity": "see execution_capacity_score in rankings for per-name detail",
    }


# ---------------------------------------------------------------------------
# What would change our mind
# ---------------------------------------------------------------------------


def build_change_conditions(regime: dict, rows: list[dict]) -> dict:
    n_short = sum(1 for r in rows if r.get("runway_bucket") == "short")
    return {
        "upgrade_conditions": [
            "XBI confirms risk-on regime (XBI +2.5% vs SPY, sustained ≥3 sessions)",
            ("Financing window improves: short-runway names secure capital " "or EES BLOCK removed"),
            ("Catalyst tape turns rewarding: ≥2 Tier-A binary catalysts " "with positive outcomes"),
            ("Elite manager accumulation confirms " "(fresh 13F delta ≥+5 Tier-1 managers)"),
        ],
        "downgrade_conditions": [
            "XBI risk-off signal (XBI −2.5% vs SPY, sustained ≥3 sessions)",
            f"Short-runway count increases materially from current {n_short} names",
            ("Catalyst tape turns punishing: ≥2 Tier-A binary catalyst " "failures in same week"),
            "EES scorecard verdict moves to BLOCK",
            ("Mechanism lane becomes overcrowded " "(mechanism_crowding_score >0.85 for top bucket)"),
        ],
        "evidence_needed": [
            "XBI and IBB price data for beta/regime classification (not yet in pipeline)",
            ("Options surface summary for implied-move expectation gap " "confirmation"),
            "IPO/M&A tone feed (not yet in pipeline)",
            ("Insider net buy coverage " "(currently main coverage gap in expectation layer)"),
        ],
    }


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------


def generate_lens(
    as_of_date: str,
    rankings: list[dict],
    catalyst_delta: dict | None,
    ops_digest: dict | None,
    ees_scorecard: dict | None,
    cartography: list[dict] | None,
    warnings: list[str],
) -> dict:
    """Build the allocation lens data structure from pipeline artifacts.

    Does not mutate the input rankings list.
    """

    def _rank_key(r: dict) -> int:
        return _safe_int(r.get("actionable_rank")) or _safe_int(r.get("composite_rank")) or 9999

    top_rows = sorted(rankings, key=_rank_key)[:30]

    regime = assess_regime(ops_digest, ees_scorecard, rankings)
    override = check_overrides(catalyst_delta, regime)
    regime["daily_override"] = override

    bucket_assignments = {r["ticker"]: assign_bucket(r) for r in top_rows}
    bucket_population = dict(Counter(bucket_assignments.values()))

    bucket_weights = _compute_bucket_stances(regime)
    review_budget = build_review_budget(top_rows, bucket_assignments, regime)
    construction_notes = build_construction_notes(top_rows, cartography)
    change_conditions = build_change_conditions(regime, rankings)

    return {
        "schema": ARTIFACT_SCHEMA,
        "governance_classification": GOVERNANCE_CLASSIFICATION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_ranked": len(rankings),
        "n_top": len(top_rows),
        "warnings": list(warnings),
        "regime": {"weekly_baseline_date": as_of_date, **regime},
        "bucket_population": bucket_population,
        "bucket_weights": bucket_weights,
        "review_budget": review_budget,
        "construction_notes": construction_notes,
        "what_would_change_our_mind": change_conditions,
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

_STANCE_SYMBOL = {
    "overweight": "▲",
    "neutral": "◆",
    "underweight": "▼",
    "avoid": "✗",
}


def render_md(lens: dict) -> str:
    now = lens.get("generated_at", "")[:16].replace("T", " ")
    as_of = lens.get("as_of_date", "")
    warnings = lens.get("warnings") or []
    regime = lens.get("regime") or {}
    override = regime.get("daily_override") or {}

    lines: list[str] = [
        f"# Biotech Allocation Lens — {as_of}",
        f"*Generated: {now} UTC*",
        f"*Classification: {lens.get('governance_classification', '')}*",
        "",
    ]

    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # --- Regime ---
    lines += [
        "## 1. Regime Baseline",
        "",
        "| Signal | Value |",
        "|---|---|",
        f"| Biotech beta | {regime.get('biotech_beta', '?')} |",
        f"| Rates / duration pressure | {regime.get('rates_pressure', '?')} |",
        f"| Financing window | {regime.get('financing_window', '?')} |",
        f"| M&A / IPO tone | {regime.get('ma_ipo_tone', '?')} |",
        f"| Catalyst tape | {regime.get('catalyst_tape', '?')} |",
        f"| Liquidity | {regime.get('liquidity', '?')} |",
        "",
    ]
    triggered = override.get("triggered", False)
    reason = override.get("reason") or "none"
    lines += [
        f"**Daily override:** {'⚠ TRIGGERED' if triggered else 'not triggered'}",
        f"*Trigger:* {reason}",
        "",
    ]

    # --- Bucket weights ---
    lines += [
        "## 2. Tactical Bucket Weights",
        "",
        "| Bucket | Stance | Reason | Risk | Review |",
        "|---|:---:|---|---|---|",
    ]
    for bw in lens.get("bucket_weights") or []:
        sym = _STANCE_SYMBOL.get(bw["stance"], "")
        lines.append(
            f"| {bw['bucket']} | {sym} {bw['stance']} | {bw['reason']} "
            f"| {bw['primary_risk']} | {bw['review_implication']} |"
        )
    lines.append("")

    # --- Review budget ---
    bucket_pop = lens.get("bucket_population") or {}
    lines += [
        "## 3. Review Budget Allocation",
        f"*(Top {lens.get('n_top', 0)} of {lens.get('n_ranked', 0)} ranked names)*",
        "",
    ]
    lines.append("**Bucket population:**")
    for b in BUCKET_NAMES:
        n = bucket_pop.get(b, 0)
        if n:
            lines.append(f"- {b}: {n}")
    lines.append("")
    lines += [
        "| Priority | Ticker | Bucket | Why Now | Signals | Risk | Action |",
        "|---:|---|---|---|---|---|---|",
    ]
    for item in lens.get("review_budget") or []:
        signals_str = ", ".join(item.get("supporting_signals") or [])
        lines.append(
            f"| {item['priority']} | {item['ticker']} | {item['bucket']} "
            f"| {item['why_now']} | {signals_str} | {item['model_risk']} "
            f"| {item['action']} |"
        )
    lines.append("")

    # --- Construction notes ---
    cn = lens.get("construction_notes") or {}
    lines += [
        "## 4. Portfolio Construction Notes",
        "",
        f"- **Mechanism concentration:** {cn.get('mechanism_concentration', '?')}",
        f"- **Stage concentration:** {cn.get('stage_concentration', '?')}",
        f"- **Catalyst-date concentration:** {cn.get('catalyst_date_concentration', '?')}",
        f"- **Financing-risk concentration:** {cn.get('financing_risk_concentration', '?')}",
        f"- **Crowding:** {cn.get('crowding', '?')}",
        f"- **Liquidity:** {cn.get('liquidity', '?')}",
        "",
    ]

    # --- What would change our mind ---
    ww = lens.get("what_would_change_our_mind") or {}
    lines += ["## 5. What Would Change Our Mind?", ""]
    lines.append("**Upgrade conditions:**")
    for c in ww.get("upgrade_conditions") or []:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("**Downgrade conditions:**")
    for c in ww.get("downgrade_conditions") or []:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("**Evidence needed:**")
    for c in ww.get("evidence_needed") or []:
        lines.append(f"- {c}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-check / improvement loop
# ---------------------------------------------------------------------------

_SELFCHECK_SCHEMA = "allocation_lens_selfcheck_v1"

_SELFCHECK_SEVERITY_RANK = {"CLEAN": 0, "MINOR": 1, "MAJOR": 2}


def run_selfcheck(lens: dict) -> dict:
    """Inspect a generated lens for known quality issues.

    Returns a structured improvement-notes dict. Called automatically by the
    cron wrapper after every run so issues accumulate in the weekly review.
    """
    notes: list[dict] = []
    worst = 0

    def _flag(check: str, severity: str, detail: str, improvement: str = "") -> None:
        nonlocal worst
        worst = max(worst, _SELFCHECK_SEVERITY_RANK.get(severity, 0))
        entry: dict = {"check": check, "severity": severity, "detail": detail}
        if improvement:
            entry["improvement"] = improvement
        notes.append(entry)

    # 1. Missing optional inputs
    warnings = lens.get("warnings") or []
    if warnings:
        _flag("missing_inputs", "MINOR", "; ".join(warnings))

    # 2. Daily override triggered (unusual — surfaces for weekly review)
    override = (lens.get("regime") or {}).get("daily_override") or {}
    if override.get("triggered"):
        _flag(
            "override_triggered",
            "MAJOR",
            override.get("reason", "unknown trigger"),
            "Review whether bucket stances should shift in response.",
        )

    # 3. Regime signals unavailable (≥3 means XBI + rates + M&A all missing)
    regime = lens.get("regime") or {}
    unavail = [k for k, v in regime.items() if isinstance(v, str) and "unavailable" in v.lower()]
    if len(unavail) >= 3:
        _flag(
            "regime_signals_unavailable",
            "MINOR",
            f"{len(unavail)} signals unavailable: {unavail}",
            "Wire XBI price, rates, M&A/IPO feed into pipeline for richer regime assessment.",
        )

    # 4. Catalyst-date concentration (≥6 names in same 14d window)
    cat_conc = (lens.get("construction_notes") or {}).get("catalyst_date_concentration", "")
    m = re.search(r"(\d+) catalysts cluster", cat_conc)
    if m and int(m.group(1)) >= 6:
        _flag(
            "catalyst_concentration_high",
            "MAJOR",
            cat_conc,
            "Diversify catalyst windows in review budget; consider explicit date-spread constraint.",
        )

    # 5. Financing risk >20% of top names
    fin_conc = (lens.get("construction_notes") or {}).get("financing_risk_concentration", "")
    fm = re.match(r"(\d+)/(\d+)", fin_conc)
    if fm and int(fm.group(2)) > 0:
        pct = int(fm.group(1)) / int(fm.group(2))
        if pct > 0.20:
            _flag(
                "financing_risk_concentration_high",
                "MAJOR",
                f"{fin_conc} ({pct:.0%})",
                "Tighten cash_poor_platform underweight stance or lower short-runway inclusion threshold.",
            )

    # 6. Mechanism data unavailable (cartography not loaded)
    mech = (lens.get("construction_notes") or {}).get("mechanism_concentration", "")
    if "unavailable" in mech:
        _flag(
            "mechanism_data_unavailable",
            "MINOR",
            "Scientific Cartography not loaded",
            "Ensure cartography run completes before allocation lens fires (cron ordering).",
        )

    # 7. EES-blocked names surfaced in review budget
    budget = lens.get("review_budget") or []
    ees_blocked = sum(1 for item in budget if "EES gate blocked" in (item.get("model_risk") or ""))
    if ees_blocked > 0:
        _flag(
            "ees_gate_blocked_in_review_budget",
            "MINOR",
            f"{ees_blocked} review budget names have EES gate blocked",
            "Consider SUPPRESS action for EES-blocked names unless catalyst is imminent.",
        )

    # 8. Near-term binary names with short runway (double risk)
    double_risk = [
        item["ticker"]
        for item in budget
        if item.get("bucket") == "near_term_binary_catalyst" and "financing risk" in (item.get("model_risk") or "")
    ]
    if double_risk:
        _flag(
            "binary_catalyst_plus_short_runway",
            "MINOR",
            f"{len(double_risk)} near-term binary names also have short runway: {double_risk}",
            "Flag these names for enhanced financing-risk review before catalyst date.",
        )

    severity_label = {0: "CLEAN", 1: "MINOR", 2: "MAJOR"}
    return {
        "schema": _SELFCHECK_SCHEMA,
        "as_of_date": lens.get("as_of_date"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall_severity": severity_label[worst],
        "n_issues": len(notes),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate biotech allocation lens artifact")
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--rankings",
        type=Path,
        default=None,
        help="Path to rankings.csv (default: auto-detect from data/snapshots/)",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Markdown output path (default: artifacts/surveillance/<date>_allocation_lens.md)",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="JSON output path (default: artifacts/surveillance/<date>_allocation_lens.json)",
    )
    parser.add_argument(
        "--selfcheck",
        action="store_true",
        default=True,
        help="Run self-check and write sidecar JSON (default: on)",
    )
    parser.add_argument(
        "--no-selfcheck",
        dest="selfcheck",
        action="store_false",
        help="Skip self-check",
    )
    args = parser.parse_args()

    warnings: list[str] = []
    as_of_date = args.as_of_date

    # Resolve rankings path
    rankings_path: Path | None = args.rankings
    if rankings_path is None:
        rankings_path = _latest_snapshot_rankings(as_of_date)
    if rankings_path is None or not rankings_path.exists():
        print(
            f"ERROR: rankings.csv not found for {as_of_date}. " "Pass --rankings explicitly.",
            file=sys.stderr,
        )
        return 2

    # Load required input
    rankings = load_rankings(rankings_path)

    # Load optional inputs (graceful degradation)
    catalyst_delta = load_catalyst_delta(as_of_date, ARTIFACTS_DIR)
    if catalyst_delta is None:
        warnings.append("catalyst_delta: not found — override triggers unavailable")

    ops_digest = load_ops_digest(as_of_date, ARTIFACTS_DIR)
    if ops_digest is None:
        warnings.append("ops_digest: not found — catalyst tape unavailable")

    ees_scorecard = load_ees_scorecard(as_of_date, ARTIFACTS_DIR)
    if ees_scorecard is None:
        warnings.append("ees_scorecard: not found — financing window unavailable")

    cartography = load_cartography(ARTIFACTS_DIR)
    if cartography is None:
        warnings.append("scientific_cartography: not found — mechanism notes unavailable")

    # Generate
    lens = generate_lens(
        as_of_date=as_of_date,
        rankings=rankings,
        catalyst_delta=catalyst_delta,
        ops_digest=ops_digest,
        ees_scorecard=ees_scorecard,
        cartography=cartography,
        warnings=warnings,
    )

    # Resolve output paths
    surveillance_dir = ARTIFACTS_DIR / "surveillance"
    surveillance_dir.mkdir(parents=True, exist_ok=True)

    out_md = args.out_md or surveillance_dir / f"{as_of_date}_allocation_lens.md"
    out_json = args.out_json or surveillance_dir / f"{as_of_date}_allocation_lens.json"

    out_md.write_text(render_md(lens))
    out_json.write_text(json.dumps(lens, indent=2))

    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")

    if args.selfcheck:
        check = run_selfcheck(lens)
        out_check = surveillance_dir / f"{as_of_date}_allocation_lens_selfcheck.json"
        out_check.write_text(json.dumps(check, indent=2))
        severity = check["overall_severity"]
        n = check["n_issues"]
        print(f"Selfcheck: {severity} ({n} issue{'s' if n != 1 else ''})")
        if severity == "MAJOR":
            for note in check["notes"]:
                if note["severity"] == "MAJOR":
                    print(f"  MAJOR: {note['check']} — {note['detail']}", file=sys.stderr)

    if warnings:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
