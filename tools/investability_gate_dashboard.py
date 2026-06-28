#!/usr/bin/env python3
"""
investability_gate_dashboard.py — DEM investability gate monitor.

VALIDATION_INFRASTRUCTURE / INVESTABILITY_GATE_MONITOR / NO_MODEL_CHANGE /
NO_RANKER_CHANGE / NO_SELECTOR_CHANGE / NO_SIZING_CHANGE / NO_TRADING_CHANGE.

Reads the forward-validation ledgers (captures.jsonl + fills.jsonl) and produces
a one-page investability gate card: weekly forward bootstrap percentile,
net-of-cost excess, drawdown, hit/payoff, cohort (rank-depth) deltas,
data-quality status, and a pre-registered 20/40/52-window gate verdict.

This does NOT change the model, ranker, selector, sizing, cron, or trading.
It only measures the frozen candidate against pre-registered promotion gates.

Verdict ladder (pre-registered):
  RESEARCH_ONLY         — no live forward validation running
  PILOT_VALIDATION      — forward harness live, <20 completed windows
  PROVISIONAL_INVESTABLE— >=20 windows, net excess>0, bootstrap pctile>0.75
  INVESTABLE            — >=52 windows, net>0, pctile>0.90 (or emp p<=0.05)
  REJECT_OR_EXTEND      — >=20 windows but criteria failed

Usage:
    python3 tools/investability_gate_dashboard.py
    python3 tools/investability_gate_dashboard.py --cost-case stress --since 2026-06-01
"""

from __future__ import annotations

import argparse
import json
from datetime import date as ddate
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO_ROOT / "artifacts" / "forward_validation"
CAPTURES = ARTIFACTS / "captures.jsonl"
FILLS = ARTIFACTS / "fills.jsonl"
CANDIDATE = ARTIFACTS / "CANDIDATE.json"
OUT_DIR = REPO_ROOT / "artifacts" / "validation" / "investability"
OUT_MD = OUT_DIR / "INVESTABILITY_GATE_CARD.md"
OUT_JSON = OUT_DIR / "investability_gate_card.json"

# Round-trip cost drag deducted from each weekly window's excess. Base adds a
# nominal liquidity-slippage allowance; stress models thin biotech names.
COST_BPS = {"low": 25, "base": 40, "stress": 75}

# Pre-registered promotion gates (see docstring / model documentation).
GATES = {
    "provisional": {"min_windows": 20, "min_pctile": 0.75, "max_p": None, "net_excess_positive": True},
    "strong": {"min_windows": 40, "min_pctile": 0.85, "max_p": 0.10, "net_excess_positive": True},
    "investable": {"min_windows": 52, "min_pctile": 0.90, "max_p": 0.05, "net_excess_positive": True},
}


def week_key(d: str) -> str:
    y, w, _ = ddate.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def nonoverlapping_weekly(captures: list[dict], fills: dict[str, dict], since: str | None) -> list[dict]:
    """Earliest capture per ISO week with a completed 5d fill."""
    by_week: dict[str, dict] = {}
    for cap in sorted(captures, key=lambda c: c["date"]):
        d = cap["date"]
        if since and d < since:
            continue
        f = fills.get(d, {})
        if f.get("xs_5d") is None:
            continue
        wk = week_key(d)
        if wk not in by_week:
            coh = f.get("cohorts") or {}
            by_week[wk] = {
                "week": wk,
                "date": d,
                "top30_xs": f.get("xs_5d"),
                "top30_ret": f.get("basket_5d"),
                "xbi_ret": f.get("xbi_5d"),
                "bootstrap_pctile": f.get("control_bootstrap_pct_5d"),
                "data_quality": cap.get("data_quality"),
                "rank31_60_xs": (coh.get("rank31_60", {}).get("5d", {}) or {}).get("xs_return"),
                "top60_xs": (coh.get("top60", {}).get("5d", {}) or {}).get("xs_return"),
            }
    return list(by_week.values())


def _stats(xs: list[float]):
    n = len(xs)
    if n == 0:
        return None
    mean = sum(xs) / n
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x < 0]
    payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {
        "n": n,
        "mean": mean,
        "cum": sum(xs),
        "hit_rate": len(wins) / n,
        "payoff_ratio": payoff,
        "avg_win": (sum(wins) / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
    }


def _rel_drawdown(rows: list[dict]) -> float | None:
    """Max drawdown of cumulative net-excess path (relative to XBI)."""
    if not rows:
        return None
    v = 1.0
    peak = 1.0
    dd = 0.0
    for r in rows:
        v *= 1 + (r.get("net_xs") or 0.0)
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    return dd


def evaluate_gate(
    n_windows: int, net_excess_cum: float | None, mean_pctile: float | None, emp_p: float | None, harness_live: bool
) -> tuple[str, list[str]]:
    """Pure gate-ladder verdict. Returns (verdict, reasons)."""
    if not harness_live:
        return "RESEARCH_ONLY", ["no forward-validation harness / candidate registered"]
    if n_windows < GATES["provisional"]["min_windows"]:
        return "PILOT_VALIDATION", [
            f"{n_windows}/{GATES['provisional']['min_windows']} windows toward provisional gate"
        ]

    def meets(g):
        ok = n_windows >= g["min_windows"]
        if g["net_excess_positive"]:
            ok = ok and (net_excess_cum is not None and net_excess_cum > 0)
        if g["min_pctile"] is not None:
            ok = ok and (mean_pctile is not None and mean_pctile >= g["min_pctile"])
        if g["max_p"] is not None:
            ok = ok and (emp_p is not None and emp_p <= g["max_p"])
        return ok

    if meets(GATES["investable"]):
        return "INVESTABLE", ["all 52-window investable criteria met"]
    if meets(GATES["strong"]):
        return "PROVISIONAL_INVESTABLE", ["40-window strong gate met; below 52-window investable gate"]
    if meets(GATES["provisional"]):
        return "PROVISIONAL_INVESTABLE", ["20-window provisional gate met"]
    # >=20 windows but criteria failed
    why = []
    if net_excess_cum is not None and net_excess_cum <= 0:
        why.append(f"net excess not positive ({net_excess_cum:+.2%})")
    if mean_pctile is not None and mean_pctile < GATES["provisional"]["min_pctile"]:
        why.append(f"bootstrap pctile {mean_pctile:.0%} < 75%")
    return "REJECT_OR_EXTEND", why or ["provisional criteria not met"]


def build_card(captures, fills_map, candidate, cost_case, since) -> dict:
    cost = COST_BPS[cost_case] / 1e4
    rows = nonoverlapping_weekly(captures, fills_map, since)
    for r in rows:
        r["net_xs"] = (r["top30_xs"] - cost) if r["top30_xs"] is not None else None
    n = len(rows)
    gross = _stats([r["top30_xs"] for r in rows if r["top30_xs"] is not None])
    net = _stats([r["net_xs"] for r in rows if r["net_xs"] is not None])
    pcts = [r["bootstrap_pctile"] for r in rows if r["bootstrap_pctile"] is not None]
    mean_pctile = sum(pcts) / len(pcts) if pcts else None
    emp_p = (1 - mean_pctile) if mean_pctile is not None else None
    dq_exceptions = sum(1 for r in rows if r.get("data_quality") not in (None, "PASS"))
    r31 = [r["rank31_60_xs"] for r in rows if r.get("rank31_60_xs") is not None]
    rank_depth_delta = (net["mean"] - sum(r31) / len(r31)) if (r31 and net) else None
    harness_live = bool(candidate) and candidate.get("status") == "active"

    verdict, reasons = evaluate_gate(n, net["cum"] if net else None, mean_pctile, emp_p, harness_live)
    tier = {
        "RESEARCH_ONLY": "Research-valid",
        "PILOT_VALIDATION": "Pilot-investable candidate",
        "PROVISIONAL_INVESTABLE": "Provisionally investable",
        "INVESTABLE": "Fully investable",
        "REJECT_OR_EXTEND": "Reject / extend",
    }[verdict]

    return {
        "schema": "investability_gate_card.v1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "classification": "VALIDATION_INFRASTRUCTURE / INVESTABILITY_GATE_MONITOR / NO_MODEL_CHANGE",
        "candidate": {
            "model_hash": candidate.get("model_hash"),
            "ruleset_hash": candidate.get("ruleset_hash"),
            "registered": candidate.get("registered"),
            "status": candidate.get("status"),
        },
        "cost_case": cost_case,
        "cost_bps_per_window": COST_BPS[cost_case],
        "windows_completed": n,
        "gross_excess": gross,
        "net_excess": net,
        "bootstrap": {"mean_percentile": mean_pctile, "empirical_p_value": emp_p, "n_windows_with_pctile": len(pcts)},
        "relative_drawdown": _rel_drawdown(rows),
        "rank_depth_replacement_delta": rank_depth_delta,
        "data_quality_exceptions": dq_exceptions,
        "pending_metrics": {
            "ees_guarded_shadow_delta": "PENDING — requires per-name forward returns + EES flags in capture ledger",
            "repeat_offender_count": "PENDING — requires per-name forward returns across windows",
            "capacity_estimate": "PENDING — requires ADV/liquidity wiring",
            "live_execution_slippage": "PENDING — from live account execution audit, not alpha proof",
        },
        "verdict": verdict,
        "tier": tier,
        "verdict_reasons": reasons,
        "gates": GATES,
        "governance": {
            "model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "trading_change": False,
            "cron_change": False,
        },
        "windows": rows,
    }


def render_md(c: dict) -> str:
    def pct(v):
        return f"{v:+.2%}" if isinstance(v, (int, float)) else "—"

    def p0(v):
        return f"{v:.0%}" if isinstance(v, (int, float)) else "—"

    g = c["gross_excess"] or {}
    net = c["net_excess"] or {}
    bs = c["bootstrap"]
    L = [
        "# DEM Investability Gate Card",
        "",
        f"**Generated:** {c['generated'][:16]}Z  ",
        f"**Candidate:** model `{c['candidate']['model_hash']}` · ruleset `{c['candidate']['ruleset_hash']}` · registered {c['candidate']['registered']} ({c['candidate']['status']})  ",
        f"**Cost case:** {c['cost_case']} ({c['cost_bps_per_window']} bps/window)  ",
        f"**Classification:** `{c['classification']}`",
        "",
        f"## VERDICT: `{c['verdict']}`  —  *{c['tier']}*",
        "",
        "Reasons: " + "; ".join(c["verdict_reasons"]),
        "",
        "## Forward windows (non-overlapping weekly 5d)",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Windows completed | **{c['windows_completed']}** |",
        f"| Top-30 gross excess (mean / cum) | {pct(g.get('mean'))} / {pct(g.get('cum'))} |",
        f"| Top-30 **net** excess (mean / cum) | {pct(net.get('mean'))} / {pct(net.get('cum'))} |",
        f"| Bootstrap percentile (mean) | {p0(bs['mean_percentile'])} |",
        (
            f"| Empirical p-value | {bs['empirical_p_value']:.3f} |"
            if isinstance(bs["empirical_p_value"], (int, float))
            else "| Empirical p-value | — |"
        ),
        f"| Hit rate (net) | {p0(net.get('hit_rate'))} |",
        f"| Payoff ratio | {net.get('payoff_ratio'):.2f}x |" if net.get("payoff_ratio") else "| Payoff ratio | — |",
        f"| Relative drawdown | {pct(c['relative_drawdown'])} |",
        f"| Rank-31–60 replacement delta | {pct(c['rank_depth_replacement_delta'])} |",
        f"| Data-quality exceptions | {c['data_quality_exceptions']} |",
        "",
        "## Pending guards (forward-data / ledger-extension gated)",
        "",
    ]
    for k, v in c["pending_metrics"].items():
        L.append(f"- **{k}**: {v}")
    L += [
        "",
        "## Pre-registered promotion ladder",
        "",
        "| Gate | Windows | Bootstrap pctile | Emp p | Net excess |",
        "|---|---:|---:|---:|---|",
        "| Provisional | ≥20 | >75% | — | >0 |",
        "| Strong | ≥40 | >85% | ≤0.10 | >0 |",
        "| Investable | ≥52 | >90% | ≤0.05 | >0 (net of costs) |",
        "",
        "_Measurement only. The model is frozen; this card does not change ranker, selector, "
        "sizing, cron, or trading. Investability requires the gates to clear on forward, "
        "out-of-sample, net-of-cost windows — not in-sample evidence._",
    ]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="DEM investability gate dashboard")
    ap.add_argument("--cost-case", choices=list(COST_BPS), default="base")
    ap.add_argument("--since", help="Only windows from YYYY-MM-DD onward")
    args = ap.parse_args()

    captures = load_jsonl(CAPTURES)
    fills = {f["capture_date"]: f for f in load_jsonl(FILLS)}
    candidate = json.loads(CANDIDATE.read_text()) if CANDIDATE.exists() else {}

    card = build_card(captures, fills, candidate, args.cost_case, args.since)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(card, indent=2) + "\n")
    md = render_md(card)
    OUT_MD.write_text(md)
    print(md)
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
