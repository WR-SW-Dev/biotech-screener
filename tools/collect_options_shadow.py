#!/usr/bin/env python3
"""Options shadow layer — two-source merge (Tastytrade + Robinhood MCP).

Merges Tastytrade IV/term-structure metrics with Robinhood contract-level
quote data into a single normalised options shadow artifact.

Classification: OPTIONS_SHADOW_LAYER_NO_MODEL_CHANGE

Hard constraints (enforced by construction):
  NO_MODEL_CHANGE, NO_RANKER_CHANGE, NO_SELECTOR_CHANGE,
  NO_SIZING_CHANGE, NO_BACKTEST_PRICE_SOURCE_CHANGE,
  NO_PRODUCTION_WIRING, NO_TRADING_ACTION, SHADOW_ONLY

Sources:
  Tastytrade  — daily pipeline IV level + term structure (primary)
  Robinhood   — contract-level greeks, OI, volume, bid/ask, quote quality

Usage:
    python tools/collect_options_shadow.py --as-of-date 2026-06-27 --tickers ARWR,RVMD,NRIX,PRAX
    python tools/collect_options_shadow.py --as-of-date 2026-06-27 --tickers ARWR --rh-cache-file /tmp/rh.json
    python tools/collect_options_shadow.py --as-of-date 2026-06-27 --tickers ARWR --dry-run

RH cache file schema (written by Robinhood MCP session):
{
  "schema": "rh_quotes_cache.v1",
  "as_of_date": "YYYY-MM-DD",
  "fetched_at": "<ISO>",
  "tickers": {
    "ARWR": {
      "underlying_price": 79.04,
      "nearest_expiry": "2026-07-17",
      "atm_strike": 80.0,
      "call": {"implied_volatility": 0.573, "delta": 0.496, "gamma": 0.038,
               "theta": -0.110, "vega": 0.073, "open_interest": 526,
               "volume": 105, "bid": 2.65, "ask": 5.00, "mark": 3.83},
      "put":  {"implied_volatility": 0.615, "delta": -0.500, "gamma": 0.035,
               "theta": -0.110, "vega": 0.073, "open_interest": 441,
               "volume": 5,   "bid": 3.90, "ask": 6.00, "mark": 4.95}
    }
  }
}

Output:
    artifacts/options_shadow/{date}_options_shadow.json
    artifacts/options_shadow/{date}_options_shadow.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("collect_options_shadow")

ARTIFACT_DIR = REPO_ROOT / "artifacts" / "options_shadow"
SCHEMA_VERSION = "options_shadow_v1"
CLASSIFICATION = "OPTIONS_SHADOW_LAYER_NO_MODEL_CHANGE"

GOVERNANCE = {
    "model_change": False,
    "ranker_change": False,
    "selector_change": False,
    "sizing_change": False,
    "backtest_price_source_change": False,
    "production_wiring": False,
}

# ---------------------------------------------------------------------------
# Pure helper functions (importable by tests)
# ---------------------------------------------------------------------------


def _is_broken(side: Optional[Dict[str, Any]]) -> bool:
    """Return True if a contract side quote is broken (bid is 0 or absent)."""
    if side is None:
        return True
    bid = side.get("bid")
    if bid is None:
        return True
    try:
        return float(bid) == 0.0
    except (TypeError, ValueError):
        return True


def _spread_pct(side: Optional[Dict[str, Any]]) -> float:
    """Return (ask - bid) / mark. Returns 1.0 when mark <= 0 or side is None."""
    if side is None:
        return 1.0
    try:
        bid = float(side.get("bid") or 0)
        ask = float(side.get("ask") or 0)
        mark = float(side.get("mark") or 0)
        if mark <= 0:
            return 1.0
        return (ask - bid) / mark
    except (TypeError, ValueError):
        return 1.0


def _classify_signal(
    tt: Optional[Dict[str, Any]],
    rh: Optional[Dict[str, Any]],
) -> str:
    """Classify ticker-level usability based on TT + RH data.

    Parameters
    ----------
    tt  : Tastytrade diagnostics dict for one symbol (or None / empty).
    rh  : Robinhood cache dict for one symbol (or None if absent).

    Returns
    -------
    One of: HIGH_CONFIDENCE_SIGNAL, CONTRACT_VALIDATED, IV_SIGNAL_ONLY,
            ILLIQUID, BROKEN_QUOTE, NO_CHAIN
    """
    # TT gate first
    if tt is None or str(tt.get("opt_has_data", "0")) != "1":
        return "NO_CHAIN"

    # No RH data at all
    if rh is None:
        return "IV_SIGNAL_ONLY"

    call = rh.get("call")
    put = rh.get("put")
    call_broken = _is_broken(call)
    put_broken = _is_broken(put)

    # Both sides broken
    if call_broken and put_broken:
        return "BROKEN_QUOTE"

    # At least one side broken
    if call_broken or put_broken:
        return "IV_SIGNAL_ONLY"

    # Both sides quoted — evaluate OI and spreads
    call_oi = int(call.get("open_interest") or 0)
    put_oi = int(put.get("open_interest") or 0)
    total_oi = call_oi + put_oi

    call_spread = _spread_pct(call)
    put_spread = _spread_pct(put)
    max_spread = max(call_spread, put_spread)

    if total_oi > 50 and max_spread < 0.30:
        return "HIGH_CONFIDENCE_SIGNAL"

    if total_oi > 10 and max_spread < 0.60:
        return "CONTRACT_VALIDATED"

    return "ILLIQUID"


def _iv_disagreement_pp(
    tt_iv: Optional[float],
    call_iv: Optional[float],
    put_iv: Optional[float],
    call_broken: bool,
    put_broken: bool,
) -> Optional[float]:
    """Compute |TT IV - RH IV| in percentage points.

    Uses call IV preferentially; falls back to put IV if call is broken.
    Returns None if both sides broken or TT IV unavailable.
    """
    if tt_iv is None:
        return None
    rh_iv = None
    if not call_broken and call_iv is not None:
        rh_iv = call_iv
    elif not put_broken and put_iv is not None:
        rh_iv = put_iv
    if rh_iv is None:
        return None
    return round((tt_iv - rh_iv) * 100, 1)


def _merge_ticker(
    symbol: str,
    tt: Optional[Dict[str, Any]],
    rh: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the merged per-ticker record for the shadow artifact."""
    signal_class = _classify_signal(tt, rh)

    # ---- IV block --------------------------------------------------------
    tt_iv = None
    if tt and str(tt.get("opt_has_data", "0")) == "1":
        try:
            tt_iv = float(tt["opt_atm_iv"])
        except (TypeError, ValueError, KeyError):
            pass

    call = rh.get("call") if rh else None
    put = rh.get("put") if rh else None
    call_broken = _is_broken(call)
    put_broken = _is_broken(put)

    rh_call_iv = None
    rh_put_iv = None
    if call and not call_broken:
        try:
            rh_call_iv = float(call.get("implied_volatility") or 0) or None
        except (TypeError, ValueError):
            pass
    if put and not put_broken:
        try:
            rh_put_iv = float(put.get("implied_volatility") or 0) or None
        except (TypeError, ValueError):
            pass

    disagreement = _iv_disagreement_pp(tt_iv, rh_call_iv, rh_put_iv, call_broken, put_broken)

    iv_block: Dict[str, Any] = {
        "tastytrade_iv": tt_iv,
        "robinhood_call_iv": rh_call_iv,
        "robinhood_put_iv": rh_put_iv,
        "iv_disagreement_pp": disagreement,
        "iv_type_tt": "surface_summary",
        "iv_type_rh": "contract_midpoint",
    }

    # ---- Term structure block -------------------------------------------
    term_block: Optional[Dict[str, Any]] = None
    if tt and str(tt.get("opt_has_data", "0")) == "1":
        front_iv = None
        back_iv = None
        term_slope = None
        try:
            front_iv = float(tt["opt_front_iv"]) if tt.get("opt_front_iv") not in ("", None) else None
        except (TypeError, ValueError):
            pass
        try:
            back_iv = float(tt["opt_back_iv"]) if tt.get("opt_back_iv") not in ("", None) else None
        except (TypeError, ValueError):
            pass
        try:
            term_slope = float(tt["opt_term_slope"]) if tt.get("opt_term_slope") not in ("", None) else None
        except (TypeError, ValueError):
            pass
        event_premium_raw = tt.get("opt_event_premium", "")
        event_premium = event_premium_raw == "YES"
        term_block = {
            "front_iv": front_iv,
            "back_iv": back_iv,
            "term_slope": term_slope,
            "event_premium": event_premium,
            "nearest_expiry": tt.get("opt_nearest_expiry") or None,
            "dte": tt.get("opt_dte") or None,
            "source": "tastytrade_metrics",
        }

    # ---- Contract block --------------------------------------------------
    contract_block: Optional[Dict[str, Any]] = None
    if rh:
        atm_strike = rh.get("atm_strike")
        expiry = rh.get("nearest_expiry")
        call_bid = float(call.get("bid") or 0) if call else None
        call_ask = float(call.get("ask") or 0) if call else None
        put_bid = float(put.get("bid") or 0) if put else None
        put_ask = float(put.get("ask") or 0) if put else None
        contract_block = {
            "atm_strike": atm_strike,
            "expiry": expiry,
            "call_bid": call_bid if not call_broken else None,
            "call_ask": call_ask if not call_broken else None,
            "call_spread_pct": round(_spread_pct(call), 3) if not call_broken else None,
            "put_bid": put_bid if not put_broken else None,
            "put_ask": put_ask if not put_broken else None,
            "put_spread_pct": round(_spread_pct(put), 3) if not put_broken else None,
            "call_broken": call_broken,
            "put_broken": put_broken,
            "source": "robinhood_mcp",
        }

    # ---- Greeks block ---------------------------------------------------
    greeks_block: Optional[Dict[str, Any]] = None
    if call and not call_broken:
        greeks_block = {
            "call_delta": call.get("delta"),
            "put_delta": put.get("delta") if put and not put_broken else None,
            "call_gamma": call.get("gamma"),
            "call_theta": call.get("theta"),
            "call_vega": call.get("vega"),
            "source": "robinhood_mcp",
        }

    # ---- Liquidity block ------------------------------------------------
    liquidity_block: Optional[Dict[str, Any]] = None
    if rh:
        call_oi = int(call.get("open_interest") or 0) if call else 0
        put_oi = int(put.get("open_interest") or 0) if put else 0
        call_vol = int(call.get("volume") or 0) if call else 0
        put_vol = int(put.get("volume") or 0) if put else 0
        liquidity_block = {
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_volume": call_vol,
            "put_volume": put_vol,
            "call_spread_pct": round(_spread_pct(call), 3) if not call_broken else None,
            "put_spread_pct": round(_spread_pct(put), 3) if not put_broken else None,
            "quality": signal_class,
            "source": "robinhood_mcp",
        }

    # ---- IV regime -------------------------------------------------------
    iv_regime = (tt.get("opt_iv_regime") or "") if tt else ""

    return {
        "iv": iv_block,
        "term_structure": term_block,
        "contract": contract_block,
        "greeks": greeks_block,
        "liquidity": liquidity_block,
        "iv_regime": iv_regime or None,
        "signal_class": signal_class,
        "model_use": "SHADOW_SIGNAL_ONLY",
    }


# ---------------------------------------------------------------------------
# Artifact builders
# ---------------------------------------------------------------------------


def _build_artifact(
    as_of_date: str,
    tickers: List[str],
    tt_data: Dict[str, Dict[str, Any]],
    rh_data: Dict[str, Dict[str, Any]],
    rh_source_used: bool,
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for sym in sorted(tickers):
        tt = tt_data.get(sym)
        rh = rh_data.get(sym)
        merged[sym] = _merge_ticker(sym, tt, rh)

    # Summary counts
    classes = [v["signal_class"] for v in merged.values()]
    event_premiums = sum(
        1 for v in merged.values() if v.get("term_structure") and v["term_structure"].get("event_premium")
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(merged, sort_keys=True, default=str).encode()
    content_hash = hashlib.sha256(payload).hexdigest()[:16]

    return {
        "schema": SCHEMA_VERSION,
        "classification": CLASSIFICATION,
        "as_of_date": as_of_date,
        "generated_at": generated_at,
        "content_hash": content_hash,
        "sources": {
            "iv_surface": "tastytrade_metrics",
            "term_structure": "tastytrade_metrics",
            "contract_quotes": "robinhood_mcp",
            "greeks": "robinhood_mcp",
            "liquidity": "robinhood_mcp",
        },
        "governance": dict(GOVERNANCE),
        "summary": {
            "n_tickers": len(tickers),
            "n_high_confidence": classes.count("HIGH_CONFIDENCE_SIGNAL"),
            "n_contract_validated": classes.count("CONTRACT_VALIDATED"),
            "n_iv_signal_only": classes.count("IV_SIGNAL_ONLY"),
            "n_illiquid": classes.count("ILLIQUID"),
            "n_broken_quote": classes.count("BROKEN_QUOTE"),
            "n_no_chain": classes.count("NO_CHAIN"),
            "n_event_premium": event_premiums,
            "tt_source_used": len(tt_data) > 0,
            "rh_source_used": rh_source_used,
        },
        "tickers": merged,
    }


def _pct(v: Optional[float]) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def _build_markdown(artifact: Dict[str, Any]) -> str:
    as_of = artifact["as_of_date"]
    generated = artifact["generated_at"]
    tickers = artifact["tickers"]
    gov = artifact["governance"]

    lines = [
        f"# Options Shadow Layer — {as_of}",
        "",
        f"Generated: {generated} | Classification: {CLASSIFICATION}",
        "Sources: Tastytrade (IV/term-structure) + Robinhood MCP (contracts/greeks/liquidity)",
        "",
        "## Signal Summary",
        "",
        "| Symbol | TT IV | RH Call IV | RH Put IV | IV Δ (pp) | Event Premium | OI (C/P) | Signal Class |",
        "|--------|-------|------------|-----------|-----------|---------------|-----------|--------------|",
    ]

    for sym, rec in sorted(tickers.items()):
        iv = rec.get("iv") or {}
        ts = rec.get("term_structure") or {}
        liq = rec.get("liquidity") or {}
        tt_iv = _pct(iv.get("tastytrade_iv"))
        rh_call = _pct(iv.get("robinhood_call_iv"))
        rh_put = _pct(iv.get("robinhood_put_iv"))
        delta_pp = iv.get("iv_disagreement_pp")
        delta_str = f"+{delta_pp}" if delta_pp and delta_pp > 0 else (str(delta_pp) if delta_pp is not None else "—")
        ep = "YES" if ts.get("event_premium") else "NO"
        call_oi = liq.get("call_oi", "—")
        put_oi = liq.get("put_oi", "—")
        oi_str = f"{call_oi}/{put_oi}" if liq else "—"
        sc = rec.get("signal_class", "—")
        lines.append(f"| {sym} | {tt_iv} | {rh_call} | {rh_put} | {delta_str} | {ep} | {oi_str} | {sc} |")

    # Event premium section
    lines += ["", "## Event Premium Flags", ""]
    ep_names = [
        sym for sym, rec in tickers.items() if rec.get("term_structure") and rec["term_structure"].get("event_premium")
    ]
    if ep_names:
        for sym in sorted(ep_names):
            ts = tickers[sym]["term_structure"]
            lines.append(
                f"- **{sym}**: front IV {_pct(ts.get('front_iv'))} vs back IV {_pct(ts.get('back_iv'))}"
                f" (slope {ts.get('term_slope', '—')})"
            )
    else:
        lines.append("None")

    # Quote quality issues
    lines += ["", "## Quote Quality Issues", ""]
    quality_issues = []
    for sym, rec in tickers.items():
        c = rec.get("contract") or {}
        liq = rec.get("liquidity") or {}
        if c.get("call_broken") or c.get("put_broken"):
            quality_issues.append(f"- **{sym}**: broken quote (call={c.get('call_broken')}, put={c.get('put_broken')})")
        elif rec.get("signal_class") in ("ILLIQUID", "NO_CHAIN"):
            call_oi = liq.get("call_oi", 0)
            put_oi = liq.get("put_oi", 0)
            quality_issues.append(f"- **{sym}**: {rec['signal_class']} (OI {call_oi}/{put_oi})")
    if quality_issues:
        lines.extend(quality_issues)
    else:
        lines.append("None")

    # IV disagreement
    lines += ["", "## IV Source Disagreement (>5pp)", ""]
    disagreements = [
        sym
        for sym, rec in tickers.items()
        if rec.get("iv")
        and rec["iv"].get("iv_disagreement_pp") is not None
        and abs(rec["iv"]["iv_disagreement_pp"]) > 5
    ]
    if disagreements:
        for sym in sorted(disagreements):
            d = tickers[sym]["iv"]["iv_disagreement_pp"]
            tt_iv = _pct(tickers[sym]["iv"].get("tastytrade_iv"))
            rh_iv = _pct(tickers[sym]["iv"].get("robinhood_call_iv"))
            lines.append(f"- **{sym}**: TT {tt_iv} vs RH call {rh_iv} ({d:+.1f}pp)")
    else:
        lines.append("None")

    # Governance
    lines += ["", "## Governance", ""]
    for k, v in gov.items():
        lines.append(f"- {k}: {v}")
    lines.append(f"- classification: {CLASSIFICATION}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Programmatic entry point (called from run_daily_production.py)
# ---------------------------------------------------------------------------


def run_options_shadow(
    as_of_date: str,
    tickers: Optional[List[str]] = None,
    rh_cache_file: Optional[str] = None,
    snapshots_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Fetch TT + merge optional RH cache → write shadow artifact. Non-blocking.

    Returns a summary dict suitable for logging. Never raises.
    """
    try:
        # Resolve tickers: prefer explicit list, else top-30 from latest snapshot
        if not tickers:
            if snapshots_dir is None:
                snapshots_dir = REPO_ROOT / "data" / "snapshots"
            snap_dirs = sorted(snapshots_dir.glob("*/rankings.csv"))
            if snap_dirs:
                import csv as _csv

                with open(snap_dirs[-1], encoding="utf-8") as _f:
                    rows = list(_csv.DictReader(_f))
                tickers = [
                    r["ticker"].upper() for r in rows if r.get("ticker") and int(r.get("actionable_rank") or 999) <= 30
                ]
            else:
                tickers = []

        if not tickers:
            return {"error": "no tickers resolved"}

        # TT fetch
        tt_data: Dict[str, Dict[str, Any]] = {}
        try:
            from common.options_diagnostics import _has_credentials, fetch_options_diagnostics

            if _has_credentials():
                tt_data = fetch_options_diagnostics(tickers, as_of_date)
        except Exception as exc:
            logger.warning("TT fetch failed in run_options_shadow: %s", exc)

        # RH cache
        rh_tickers: Dict[str, Dict[str, Any]] = {}
        rh_source_used = False
        if rh_cache_file:
            try:
                with open(rh_cache_file) as f:
                    rh_cache = json.load(f)
                rh_tickers = rh_cache.get("tickers", {})
                rh_source_used = bool(rh_tickers)
            except Exception as exc:
                logger.warning("RH cache load failed: %s", exc)

        artifact = _build_artifact(as_of_date, tickers, tt_data, rh_tickers, rh_source_used)
        md = _build_markdown(artifact)

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        json_path = ARTIFACT_DIR / f"{as_of_date}_options_shadow.json"
        md_path = ARTIFACT_DIR / f"{as_of_date}_options_shadow.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2, default=str)
            f.write("\n")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        s = artifact["summary"]
        return {
            "n_tickers": s["n_tickers"],
            "n_event_premium": s["n_event_premium"],
            "n_high_confidence": s["n_high_confidence"],
            "n_iv_signal_only": s["n_iv_signal_only"],
            "json_path": str(json_path),
            "md_path": str(md_path),
        }

    except Exception as exc:
        logger.warning("run_options_shadow failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge TT + RH options data into shadow artifact")
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--rh-cache-file", help="Path to Robinhood quotes cache JSON")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON only, no files written")
    args = parser.parse_args()

    try:
        _date.fromisoformat(args.as_of_date)
    except ValueError:
        logger.error("Invalid --as-of-date: %s", args.as_of_date)
        return 1

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        logger.error("No tickers provided")
        return 1

    # ---- Tastytrade fetch -----------------------------------------------
    tt_data: Dict[str, Dict[str, Any]] = {}
    try:
        from common.options_diagnostics import _has_credentials, fetch_options_diagnostics

        if not _has_credentials():
            logger.warning("TT credentials not set — all tickers will be NO_CHAIN")
        else:
            logger.info("Fetching Tastytrade options diagnostics for %d tickers", len(tickers))
            tt_data = fetch_options_diagnostics(tickers, args.as_of_date)
    except Exception as exc:
        logger.warning("Tastytrade fetch failed: %s — continuing with empty TT data", exc)

    # ---- Robinhood cache load -------------------------------------------
    rh_tickers: Dict[str, Dict[str, Any]] = {}
    rh_source_used = False
    if args.rh_cache_file:
        try:
            with open(args.rh_cache_file) as f:
                rh_cache = json.load(f)
            rh_tickers = rh_cache.get("tickers", {})
            rh_source_used = bool(rh_tickers)
            logger.info("Loaded RH cache: %d tickers from %s", len(rh_tickers), args.rh_cache_file)
        except Exception as exc:
            logger.warning("Failed to load RH cache file: %s — proceeding TT-only", exc)

    # ---- Build artifact -------------------------------------------------
    artifact = _build_artifact(args.as_of_date, tickers, tt_data, rh_tickers, rh_source_used)
    md = _build_markdown(artifact)

    if args.dry_run:
        print(json.dumps(artifact, indent=2, default=str))
        return 0

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / f"{args.as_of_date}_options_shadow.json"
    md_path = ARTIFACT_DIR / f"{args.as_of_date}_options_shadow.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, default=str)
        f.write("\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    logger.info("Wrote %s", json_path)
    logger.info("Wrote %s", md_path)

    # Print summary
    s = artifact["summary"]
    logger.info(
        "Summary: %d tickers | HC=%d CV=%d ISO=%d ILL=%d BQ=%d NC=%d EP=%d",
        s["n_tickers"],
        s["n_high_confidence"],
        s["n_contract_validated"],
        s["n_iv_signal_only"],
        s["n_illiquid"],
        s["n_broken_quote"],
        s["n_no_chain"],
        s["n_event_premium"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
