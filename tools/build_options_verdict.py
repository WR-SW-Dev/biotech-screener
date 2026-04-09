#!/usr/bin/env python3
"""Options verdict — fused multi-lens alert aggregation.

Reads the 4 options monitoring lenses and produces one ticker-level verdict
with new/ongoing/resolved state transitions.

Lenses:
  1. options_watch (post-packet) — 8 alert codes, surface-level
  2. options_watch (pre-open) — stricter subset of the above
  3. surface_delta — overnight IV/RR/skew shifts
  4. price_action_watch — stock + options anomalies (15 alert codes)

Escalation: 2+ lenses agree on a ticker → HIGH.
            1 lens HIGH on near-catalyst name → HIGH.
            1 lens alone → MEDIUM.
            No alerts → ticker not in output.

Read-only — does not affect rankings, scoring, or execution.

Output:
    artifacts/options_verdict/{date}_verdict.json
    artifacts/options_verdict/{date}_verdict.md

Usage:
    python tools/build_options_verdict.py --as-of-date 2026-03-31
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("options_verdict")

SCHEMA_VERSION = "options_verdict.v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Lens loaders — extract per-ticker alert sets from each artifact
# ---------------------------------------------------------------------------

# Options-relevant alert codes from price_action_watch
_PAW_OPTIONS_CODES = {
    "IV_RAMP_HIGH",
    "IV_CRUSH",
    "OPTIONS_SURFACE_MOVE_HIGH",
    "SKEW_EXTREME",
    "STOCK_DOWN_IV_UP",
    "STOCK_UP_IV_DOWN",
    "QUIET_BEFORE_CATALYST",
    "REACTION_MISMATCH",
}


def _load_options_watch(
    artifacts_dir: Path,
    date: str,
    mode: str = "post",
) -> Dict[str, Dict[str, Any]]:
    """Load options_watch artifact. Returns {ticker: {flags, priority_score, ...}}."""
    suffix = "_watch.json" if mode == "post" else "_premarket_watch.json"
    data = _load_json(artifacts_dir / "options_watch" / f"{date}{suffix}")
    if not data:
        return {}
    result = {}
    for row in data.get("rows", []):
        t = row.get("ticker")
        if t:
            result[t] = {
                "flags": set(row.get("flags", [])),
                "priority_score": row.get("priority_score", 0),
                "catalyst_days": row.get("catalyst_days"),
                "is_hard_catalyst": row.get("is_hard_catalyst", False),
                "tier": row.get("tier", ""),
            }
    return result


def _load_surface_delta(
    snapshots_dir: Path,
    date: str,
) -> Dict[str, Dict[str, Any]]:
    """Load surface_delta artifact. Returns {ticker: {flags, severity, ...}}."""
    data = _load_json(snapshots_dir / date / "surface_delta.json")
    if not data:
        return {}
    result = {}
    for row in data.get("deltas", []):
        t = row.get("ticker")
        if t:
            result[t] = {
                "flags": set(row.get("flags", [])),
                "severity": row.get("severity", "info"),
                "n_flags": row.get("n_flags", 0),
                "atm_iv_change": row.get("atm_iv_change"),
                "rr_25d_change": row.get("rr_25d_change"),
            }
    return result


def _load_price_action(
    artifacts_dir: Path,
    date: str,
) -> Dict[str, Dict[str, Any]]:
    """Load price_action_watch, filtering to options-relevant alerts only."""
    data = _load_json(artifacts_dir / "price_action_watch" / f"{date}_watch.json")
    if not data:
        return {}
    result = {}
    for row in data.get("rows", []):
        t = row.get("ticker")
        if not t:
            continue
        options_alerts = [a for a in row.get("alerts", []) if a in _PAW_OPTIONS_CODES]
        if options_alerts:
            result[t] = {
                "flags": set(options_alerts),
                "all_alerts": row.get("alerts", []),
                "return_1d_pct": row.get("return_1d_pct"),
                "move_intensity": row.get("move_intensity"),
            }
    return result


# ---------------------------------------------------------------------------
# Fusion logic
# ---------------------------------------------------------------------------


def _classify_fused_severity(
    n_lenses: int,
    any_high_priority: bool,
    near_catalyst: bool,
) -> str:
    """Classify fused severity from lens agreement count."""
    if n_lenses >= 2:
        return "HIGH"
    if any_high_priority and near_catalyst:
        return "HIGH"
    return "MEDIUM"


def fuse_verdicts(
    options_post: Dict[str, Dict],
    options_pre: Dict[str, Dict],
    surface_delta: Dict[str, Dict],
    price_action: Dict[str, Dict],
    *,
    prior_verdicts: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, Any]]:
    """Fuse 4 lenses into per-ticker verdicts with state transitions.

    Returns list of verdict dicts sorted by severity then ticker.
    """
    # Collect all tickers that appear in any lens
    all_tickers: Set[str] = set()
    all_tickers.update(options_post.keys())
    all_tickers.update(options_pre.keys())
    all_tickers.update(surface_delta.keys())
    all_tickers.update(price_action.keys())

    prior = prior_verdicts or {}
    verdicts = []

    for ticker in sorted(all_tickers):
        lenses_active = []
        all_flags: Set[str] = set()
        context: Dict[str, Any] = {}

        # Lens 1: options_watch post-packet
        ow_post = options_post.get(ticker)
        if ow_post and ow_post["flags"]:
            lenses_active.append("options_watch_post")
            all_flags.update(ow_post["flags"])
            context.update({k: v for k, v in ow_post.items() if k != "flags"})

        # Lens 2: options_watch pre-open
        ow_pre = options_pre.get(ticker)
        if ow_pre and ow_pre["flags"]:
            lenses_active.append("options_watch_pre")
            all_flags.update(ow_pre["flags"])

        # Lens 3: surface delta
        sd = surface_delta.get(ticker)
        if sd and sd["flags"] and sd.get("severity") in ("watch", "alert"):
            lenses_active.append("surface_delta")
            all_flags.update(sd["flags"])
            if sd.get("atm_iv_change") is not None:
                context["atm_iv_change_overnight"] = sd["atm_iv_change"]

        # Lens 4: price action (options-relevant only)
        pa = price_action.get(ticker)
        if pa and pa["flags"]:
            lenses_active.append("price_action")
            all_flags.update(pa["flags"])
            if pa.get("return_1d_pct") is not None:
                context["return_1d_pct"] = pa["return_1d_pct"]

        if not lenses_active:
            continue

        # Determine severity
        any_high = any(
            f in all_flags
            for f in {
                "IV_RAMP_HIGH",
                "SURFACE_MOVE_HIGH",
                "EVENT_PREMIUM",
                "EXTREME_SKEW",
                "QUIET_BEFORE_CATALYST",
                "REACTION_MISMATCH",
            }
        )
        cat_days = context.get("catalyst_days")
        near_catalyst = cat_days is not None and cat_days <= 14

        severity = _classify_fused_severity(
            len(lenses_active),
            any_high,
            near_catalyst,
        )

        # State transition
        was_active = ticker in prior
        state = "ongoing" if was_active else "new"

        verdicts.append(
            {
                "ticker": ticker,
                "severity": severity,
                "n_lenses": len(lenses_active),
                "lenses": lenses_active,
                "flags": sorted(all_flags),
                "near_catalyst": near_catalyst,
                "catalyst_days": cat_days,
                "tier": context.get("tier", ""),
                "state": state,
                **{k: v for k, v in context.items() if k not in ("flags", "tier")},
            }
        )

    # Add resolved tickers (were active yesterday, not today)
    for ticker, prev in prior.items():
        if ticker not in all_tickers:
            verdicts.append(
                {
                    "ticker": ticker,
                    "severity": "RESOLVED",
                    "n_lenses": 0,
                    "lenses": [],
                    "flags": [],
                    "near_catalyst": False,
                    "catalyst_days": prev.get("catalyst_days"),
                    "tier": prev.get("tier", ""),
                    "state": "resolved",
                }
            )

    # Sort: HIGH first, then MEDIUM, then RESOLVED
    sev_order = {"HIGH": 0, "MEDIUM": 1, "RESOLVED": 2}
    verdicts.sort(key=lambda v: (sev_order.get(v["severity"], 9), v["ticker"]))

    return verdicts


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_options_verdict(
    as_of_date: str,
    *,
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
    artifacts_dir: Path = REPO_ROOT / "artifacts",
) -> Dict[str, Any]:
    """Build fused options verdict artifact."""
    # Load all 4 lenses
    options_post = _load_options_watch(artifacts_dir, as_of_date, "post")
    options_pre = _load_options_watch(artifacts_dir, as_of_date, "pre")
    surface_delta = _load_surface_delta(snapshots_dir, as_of_date)
    price_action = _load_price_action(artifacts_dir, as_of_date)

    logger.info(
        "Lenses loaded: options_post=%d, options_pre=%d, surface_delta=%d, price_action=%d",
        len(options_post),
        len(options_pre),
        len(surface_delta),
        len(price_action),
    )

    # Load prior verdict for state transitions
    out_dir = artifacts_dir / "options_verdict"
    out_dir.mkdir(parents=True, exist_ok=True)

    prior_verdicts: Dict[str, Dict] = {}
    prior_dates = sorted(
        f.stem.split("_")[0] for f in out_dir.glob("*_verdict.json") if f.stem.split("_")[0] < as_of_date
    )
    if prior_dates:
        prior_data = _load_json(out_dir / f"{prior_dates[-1]}_verdict.json")
        if prior_data:
            for v in prior_data.get("verdicts", []):
                if v.get("state") != "resolved":
                    prior_verdicts[v["ticker"]] = v

    # Fuse
    verdicts = fuse_verdicts(
        options_post,
        options_pre,
        surface_delta,
        price_action,
        prior_verdicts=prior_verdicts,
    )

    n_high = sum(1 for v in verdicts if v["severity"] == "HIGH")
    n_medium = sum(1 for v in verdicts if v["severity"] == "MEDIUM")
    n_resolved = sum(1 for v in verdicts if v["severity"] == "RESOLVED")
    n_new = sum(1 for v in verdicts if v["state"] == "new")

    artifact = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_tickers": len([v for v in verdicts if v["severity"] != "RESOLVED"]),
        "n_high": n_high,
        "n_medium": n_medium,
        "n_resolved": n_resolved,
        "n_new": n_new,
        "lens_counts": {
            "options_watch_post": len(options_post),
            "options_watch_pre": len(options_pre),
            "surface_delta": len(surface_delta),
            "price_action": len(price_action),
        },
        "verdicts": verdicts,
    }

    # Write artifacts
    json_path = out_dir / f"{as_of_date}_verdict.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, sort_keys=True, default=str)
    logger.info("Wrote %s", json_path)

    md_path = out_dir / f"{as_of_date}_verdict.md"
    md_path.write_text(_format_md(artifact), encoding="utf-8")
    logger.info("Wrote %s", md_path)

    return artifact


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _format_md(d: Dict[str, Any]) -> str:
    lines = [f"# Options Verdict — {d['as_of_date']}", ""]
    lines.append(
        f"**{d['n_tickers']} active** "
        f"(H={d['n_high']} M={d['n_medium']}) | "
        f"{d['n_new']} new | {d['n_resolved']} resolved"
    )
    lines.append("")

    verdicts = d.get("verdicts", [])

    for sev in ("HIGH", "MEDIUM"):
        sev_v = [v for v in verdicts if v["severity"] == sev]
        if not sev_v:
            continue
        lines.append(f"## {sev}")
        lines.append("")
        lines.append("| Ticker | Tier | Cat | Lenses | State | Flags |")
        lines.append("|--------|------|-----|--------|-------|-------|")
        for v in sev_v:
            cat = v.get("catalyst_days", "-")
            lenses = ",".join(
                l.replace("options_watch_", "ow_").replace("surface_delta", "sd").replace("price_action", "pa")
                for l in v["lenses"]
            )
            flags = ", ".join(v["flags"][:4])
            if len(v["flags"]) > 4:
                flags += f" +{len(v['flags']) - 4}"
            lines.append(f"| {v['ticker']} | {v.get('tier', '?')} | {cat} | {lenses} | {v['state']} | {flags} |")
        lines.append("")

    resolved = [v for v in verdicts if v["severity"] == "RESOLVED"]
    if resolved:
        lines.append(f"## RESOLVED ({len(resolved)})")
        lines.append("")
        lines.append(", ".join(v["ticker"] for v in resolved))
        lines.append("")

    lc = d.get("lens_counts", {})
    lines.append(
        f"*Lenses: ow_post={lc.get('options_watch_post', 0)} "
        f"ow_pre={lc.get('options_watch_pre', 0)} "
        f"sd={lc.get('surface_delta', 0)} "
        f"pa={lc.get('price_action', 0)}*"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Options verdict — fused multi-lens alert aggregation")
    parser.add_argument(
        "--as-of-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--snapshots-dir", type=Path, default=REPO_ROOT / "data" / "snapshots")
    parser.add_argument("--artifacts-dir", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()

    result = build_options_verdict(
        args.as_of_date,
        snapshots_dir=args.snapshots_dir,
        artifacts_dir=args.artifacts_dir,
    )

    logger.info(
        "Verdict: %d active (H=%d M=%d), %d new, %d resolved",
        result["n_tickers"],
        result["n_high"],
        result["n_medium"],
        result["n_new"],
        result["n_resolved"],
    )


if __name__ == "__main__":
    main()
