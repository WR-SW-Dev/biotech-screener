#!/usr/bin/env python3
"""
Full data audit: per-ticker validation across ALL input lanes.

Motivation: 13F CUSIP->ticker resolution bug affected ~70 tickers.
This script audits every major data source for every ticker in the
current universe and classifies each ticker as VALID, DEGRADED, or BROKEN.

Usage:
    python scripts/research/full_data_audit.py [--snapshot-date 2026-04-06]

Outputs:
    artifacts/data_audit/ticker_validation_matrix.json
    artifacts/data_audit/audit_summary.md
    (plus console summary)
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parents[2]
PROD = BASE / "production_data"
DATA = BASE / "data"

KNOWN_CATALYST_FAMILIES = {"CLINICAL", "REGULATORY", "SAFETY", "UNKNOWN", ""}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_float(v):
    """Return float or None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _is_recent(datestr, max_days=7, ref_date=None):
    """Check if ISO date string is within max_days of ref_date."""
    if not datestr:
        return False
    try:
        # Handle both date-only and datetime formats
        dt_str = str(datestr)[:10]
        dt = datetime.strptime(dt_str, "%Y-%m-%d")
        ref = ref_date or datetime.now()
        return (ref - dt).days <= max_days
    except (ValueError, TypeError):
        return False


def _load_json(path):
    """Load JSON file, return None on failure."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  WARNING: Cannot load {path}: {e}")
        return None


def _load_csv_rows(path):
    """Load CSV into list of dicts, return [] on failure."""
    try:
        with open(path, "r", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"  WARNING: Cannot load {path}")
        return []


# ---------------------------------------------------------------------------
# Data loaders (read everything once)
# ---------------------------------------------------------------------------
def load_all_data(snapshot_date):
    """Load all data sources into memory. Returns dict of data objects."""
    snap_dir = DATA / "snapshots" / snapshot_date
    d = {}

    print(f"Loading data for snapshot date: {snapshot_date}")
    print(f"  Snapshot dir: {snap_dir}")
    print(f"  Production dir: {PROD}")
    print()

    # Universe
    d["universe"] = _load_json(PROD / "universe.json") or []
    d["universe_tickers"] = {t["ticker"] for t in d["universe"] if "ticker" in t}
    print(f"  universe.json: {len(d['universe_tickers'])} tickers")

    # CUSIP static map (cusip -> ticker)
    raw_cusip = _load_json(PROD / "cusip_static_map.json") or {}
    d["cusip_tickers"] = set(raw_cusip.values())  # tickers that have a CUSIP
    d["cusip_map"] = raw_cusip
    print(f"  cusip_static_map.json: {len(d['cusip_tickers'])} tickers mapped")

    # Market data (list of dicts with 'ticker' key)
    raw_mkt = _load_json(PROD / "market_data.json") or []
    d["market_data"] = {r["ticker"]: r for r in raw_mkt if "ticker" in r}
    print(f"  market_data.json: {len(d['market_data'])} tickers")

    # Price history (large CSV - read only latest date per ticker)
    d["price_latest"] = {}  # ticker -> {date, close}
    d["price_tickers"] = set()
    d["price_impossible"] = {}  # ticker -> list of issues
    ph_path = PROD / "price_history.csv"
    if ph_path.exists():
        count = 0
        with open(ph_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tk = row.get("ticker", "")
                dt = row.get("date", "")
                cl = _safe_float(row.get("close"))
                if not tk:
                    continue
                d["price_tickers"].add(tk)
                count += 1
                # Track latest date per ticker
                if tk not in d["price_latest"] or dt > d["price_latest"][tk]["date"]:
                    d["price_latest"][tk] = {"date": dt, "close": cl}
                # Flag impossible values
                if cl is not None:
                    issues = []
                    if cl > 10000:
                        issues.append(f"price={cl} > 10000")
                    if cl < 0.01:
                        issues.append(f"price={cl} < 0.01")
                    if cl <= 0:
                        issues.append(f"price={cl} <= 0")
                    if issues and tk not in d["price_impossible"]:
                        d["price_impossible"][tk] = issues
        print(f"  price_history.csv: {len(d['price_tickers'])} tickers, {count} rows")
    else:
        print("  WARNING: price_history.csv not found")

    # Corporate actions
    raw_ca = _load_json(PROD / "corporate_actions.json") or {}
    actions = raw_ca.get("actions", [])
    d["corporate_action_tickers"] = set()
    for a in actions:
        tk = a.get("ticker")
        if tk:
            d["corporate_action_tickers"].add(tk)
    print(f"  corporate_actions.json: {len(d['corporate_action_tickers'])} tickers with actions")

    # Institutional summary (snapshot)
    raw_inst = _load_json(snap_dir / "institutional_summary.json")
    if raw_inst and "tickers" in raw_inst:
        d["inst_summary"] = raw_inst["tickers"]
    else:
        d["inst_summary"] = {}
    print(f"  institutional_summary.json: {len(d['inst_summary'])} tickers")

    # Institutional delta (snapshot)
    raw_delta = _load_json(snap_dir / "institutional_summary_delta.json")
    if raw_delta and "tickers" in raw_delta:
        d["inst_delta"] = raw_delta["tickers"]
    else:
        d["inst_delta"] = {}
    print(f"  institutional_summary_delta.json: {len(d['inst_delta'])} tickers")

    # Rankings (snapshot)
    rank_rows = _load_csv_rows(snap_dir / "rankings.csv")
    d["rankings"] = {r["ticker"]: r for r in rank_rows if "ticker" in r}
    print(f"  rankings.csv: {len(d['rankings'])} tickers")

    # Options diagnostics (snapshot)
    opt_rows = _load_csv_rows(snap_dir / "options_diagnostics.csv")
    d["options"] = {r["ticker"]: r for r in opt_rows if "ticker" in r}
    print(f"  options_diagnostics.csv: {len(d['options'])} tickers")

    print()
    return d


# ---------------------------------------------------------------------------
# Per-ticker validation
# ---------------------------------------------------------------------------
def validate_ticker(ticker, data, ref_date):
    """Run all checks for one ticker. Returns dict of check results."""
    checks = {}
    critical_fails = []
    degraded_fails = []

    # -----------------------------------------------------------------------
    # Identity checks
    # -----------------------------------------------------------------------
    checks["in_universe"] = ticker in data["universe_tickers"]
    checks["has_cusip"] = ticker in data["cusip_tickers"]
    checks["in_market_data"] = ticker in data["market_data"]
    checks["in_price_history"] = ticker in data["price_tickers"]
    checks["has_corporate_action"] = ticker in data["corporate_action_tickers"]

    if not checks["in_universe"]:
        critical_fails.append("NOT in universe.json")
    if not checks["has_cusip"]:
        degraded_fails.append("no CUSIP mapping")
    if not checks["in_market_data"]:
        critical_fails.append("NOT in market_data.json")

    # -----------------------------------------------------------------------
    # Market data checks
    # -----------------------------------------------------------------------
    mkt = data["market_data"].get(ticker, {})
    price = _safe_float(mkt.get("price"))
    mcap = _safe_float(mkt.get("market_cap"))
    collected = mkt.get("collected_at")
    avg_vol = _safe_float(mkt.get("avg_volume"))
    beta = _safe_float(mkt.get("beta"))

    checks["mkt_has_price"] = price is not None and price > 0
    checks["mkt_has_market_cap"] = mcap is not None and mcap > 0
    checks["mkt_has_collected_at"] = collected is not None and collected != ""
    checks["mkt_collected_recent"] = _is_recent(collected, max_days=7, ref_date=ref_date)
    checks["mkt_has_avg_volume"] = avg_vol is not None and avg_vol > 0
    checks["mkt_has_beta"] = beta is not None

    if not checks["mkt_has_price"]:
        critical_fails.append(f"market_data price missing/zero ({price})")
    if not checks["mkt_has_market_cap"]:
        critical_fails.append(f"market_data market_cap missing/zero ({mcap})")
    if not checks["mkt_collected_recent"]:
        degraded_fails.append(f"market_data collected_at not recent ({collected})")
    if not checks["mkt_has_avg_volume"]:
        degraded_fails.append("market_data avg_volume missing")
    if not checks["mkt_has_beta"]:
        degraded_fails.append("market_data beta missing")

    # -----------------------------------------------------------------------
    # Price history checks
    # -----------------------------------------------------------------------
    ph = data["price_latest"].get(ticker)
    if ph:
        checks["ph_has_data"] = True
        checks["ph_recent"] = _is_recent(ph["date"], max_days=7, ref_date=ref_date)
        checks["ph_positive"] = ph["close"] is not None and ph["close"] > 0
        checks["ph_no_impossible"] = ticker not in data["price_impossible"]
    else:
        checks["ph_has_data"] = False
        checks["ph_recent"] = False
        checks["ph_positive"] = False
        checks["ph_no_impossible"] = True  # vacuously true

    if not checks["ph_has_data"]:
        critical_fails.append("no price history at all")
    elif not checks["ph_recent"]:
        degraded_fails.append(f"price_history last date={ph['date']}, not recent")
    if not checks["ph_positive"] and checks["ph_has_data"]:
        critical_fails.append(f"price_history latest close={ph.get('close')}")
    if not checks["ph_no_impossible"]:
        degraded_fails.append(f"price_history impossible values: {data['price_impossible'].get(ticker)}")

    # -----------------------------------------------------------------------
    # Institutional summary checks
    # -----------------------------------------------------------------------
    inst = data["inst_summary"].get(ticker)
    if inst:
        checks["inst_has_entry"] = True
        ehc = inst.get("elite_holders_count")
        isz = inst.get("inst_score_z")
        checks["inst_elite_count_valid"] = ehc is not None and isinstance(ehc, (int, float)) and ehc >= 0
        checks["inst_score_z_valid"] = isz is not None and isinstance(isz, (int, float))
    else:
        checks["inst_has_entry"] = False
        checks["inst_elite_count_valid"] = False
        checks["inst_score_z_valid"] = False

    if not checks["inst_has_entry"]:
        degraded_fails.append("no institutional_summary entry")

    # -----------------------------------------------------------------------
    # Institutional delta checks
    # -----------------------------------------------------------------------
    delta = data["inst_delta"].get(ticker)
    if delta:
        checks["delta_has_entry"] = True
        ned = delta.get("net_elite_holders_delta")
        checks["delta_net_valid"] = ned is not None and isinstance(ned, (int, float))
    else:
        checks["delta_has_entry"] = False
        checks["delta_net_valid"] = False

    if not checks["delta_has_entry"]:
        degraded_fails.append("no institutional_delta entry")

    # -----------------------------------------------------------------------
    # Rankings checks
    # -----------------------------------------------------------------------
    rank = data["rankings"].get(ticker)
    if rank:
        checks["rank_has_row"] = True

        ar = rank.get("actionable_rank", "")
        checks["rank_has_actionable_rank"] = ar != "" and ar is not None
        coinvest_z = rank.get("coinvest_score_z", "")
        checks["rank_has_coinvest_z"] = coinvest_z != "" and coinvest_z is not None
        fin_score = rank.get("financial_score", "")
        checks["rank_has_financial_score"] = fin_score != "" and fin_score is not None
        cat_days = rank.get("catalyst_days", "")
        checks["rank_has_catalyst_days"] = cat_days != "" and cat_days is not None
        cat_fam = rank.get("catalyst_family", "")
        checks["rank_has_catalyst_family"] = cat_fam is not None  # blank is OK
        clin = rank.get("clinical_score", "")
        checks["rank_has_clinical_score"] = clin != "" and clin is not None
        sel = rank.get("selector_score", "")
        checks["rank_has_selector_score"] = sel != "" and sel is not None

        # Impossible values
        ar_f = _safe_float(ar)
        checks["rank_no_impossible"] = True
        rank_issues = []
        if ar_f is not None and ar_f < 0:
            rank_issues.append(f"actionable_rank={ar_f}<0")
            checks["rank_no_impossible"] = False
        coinvest_f = _safe_float(coinvest_z)
        if coinvest_f is not None and (coinvest_f > 100 or coinvest_f < -100):
            rank_issues.append(f"coinvest_score_z={coinvest_f} out of range")
            checks["rank_no_impossible"] = False

        # ---------------------------------------------------------------
        # Catalyst checks
        # ---------------------------------------------------------------
        cat_days_f = _safe_float(cat_days)
        if cat_days_f is not None:
            checks["cat_days_range"] = 0 < cat_days_f < 1000
            if not checks["cat_days_range"]:
                degraded_fails.append(f"catalyst_days={cat_days_f} out of range")
        else:
            checks["cat_days_range"] = True  # no catalyst is OK

        checks["cat_family_valid"] = cat_fam in KNOWN_CATALYST_FAMILIES
        if not checks["cat_family_valid"]:
            degraded_fails.append(f"catalyst_family='{cat_fam}' unknown")

        is_hard = rank.get("is_hard_catalyst", "")
        checks["cat_is_hard_bool"] = is_hard in ("", "0", "1", "True", "False", True, False, 0, 1, None)

        cat_src = rank.get("catalyst_source", "")
        if cat_days_f is not None and cat_days_f > 0:
            checks["cat_source_present"] = cat_src != "" and cat_src is not None
            if not checks["cat_source_present"]:
                degraded_fails.append("catalyst_days present but no catalyst_source")
        else:
            checks["cat_source_present"] = True  # N/A

        # ---------------------------------------------------------------
        # Financial checks
        # ---------------------------------------------------------------
        fin_f = _safe_float(fin_score)
        if fin_f is not None:
            checks["fin_score_range"] = 0 <= fin_f <= 100
            checks["fin_score_nonneg"] = fin_f >= 0
            if not checks["fin_score_range"]:
                degraded_fails.append(f"financial_score={fin_f} out of [0,100]")
        else:
            checks["fin_score_range"] = True  # missing = separate check
            checks["fin_score_nonneg"] = True

        # ---------------------------------------------------------------
        # Cross-source consistency: sponsor_tier1_count vs inst elite_holders_count
        # ---------------------------------------------------------------
        sponsor_t1 = _safe_int(rank.get("sponsor_tier1_count"))
        inst_elite = None
        if inst:
            inst_elite = inst.get("elite_holders_count")
            if inst_elite is not None:
                inst_elite = int(inst_elite)

        if sponsor_t1 is not None and inst_elite is not None:
            checks["cross_sponsor_vs_inst"] = sponsor_t1 == inst_elite
            if not checks["cross_sponsor_vs_inst"]:
                critical_fails.append(
                    f"CUSIP BUG? sponsor_tier1_count={sponsor_t1} != " f"inst elite_holders_count={inst_elite}"
                )
        else:
            checks["cross_sponsor_vs_inst"] = None  # can't compare

        # Cross-check: coinvest_tag vs elite count
        coinvest_tag = rank.get("coinvest_tag", "")
        if coinvest_tag and inst_elite is not None:
            # coinvest_tag looks like "elite_N" where N = sponsor count
            if coinvest_tag.startswith("elite_"):
                try:
                    tag_n = int(coinvest_tag.split("_")[1])
                    checks["cross_coinvest_tag_vs_elite"] = tag_n == inst_elite
                    if not checks["cross_coinvest_tag_vs_elite"]:
                        critical_fails.append(
                            f"CUSIP BUG? coinvest_tag={coinvest_tag} but " f"elite_holders_count={inst_elite}"
                        )
                except (ValueError, IndexError):
                    checks["cross_coinvest_tag_vs_elite"] = None
            else:
                checks["cross_coinvest_tag_vs_elite"] = None  # N/A
        else:
            checks["cross_coinvest_tag_vs_elite"] = None

        if not checks["rank_has_actionable_rank"]:
            # Not having a rank could mean ineligible - check eligible flag
            eligible = rank.get("eligible", "")
            if eligible == "1" or eligible == "True" or eligible is True:
                critical_fails.append("eligible but no actionable_rank")
            # If ineligible, missing rank is expected
        if not checks["rank_has_selector_score"]:
            degraded_fails.append("no selector_score in rankings")

    else:
        checks["rank_has_row"] = False
        checks["rank_has_actionable_rank"] = False
        checks["rank_has_coinvest_z"] = False
        checks["rank_has_financial_score"] = False
        checks["rank_has_catalyst_days"] = False
        checks["rank_has_catalyst_family"] = False
        checks["rank_has_clinical_score"] = False
        checks["rank_has_selector_score"] = False
        checks["rank_no_impossible"] = True
        checks["cat_days_range"] = True
        checks["cat_family_valid"] = True
        checks["cat_is_hard_bool"] = True
        checks["cat_source_present"] = True
        checks["fin_score_range"] = True
        checks["fin_score_nonneg"] = True
        checks["cross_sponsor_vs_inst"] = None
        checks["cross_coinvest_tag_vs_elite"] = None
        critical_fails.append("NOT in rankings.csv")

    # -----------------------------------------------------------------------
    # Options checks
    # -----------------------------------------------------------------------
    opt = data["options"].get(ticker)
    if opt:
        checks["opt_has_data"] = True
        iv = opt.get("opt_atm_iv", "")
        checks["opt_has_iv"] = iv != "" and iv is not None and _safe_float(iv) is not None
    else:
        checks["opt_has_data"] = False
        checks["opt_has_iv"] = False

    if not checks["opt_has_data"]:
        degraded_fails.append("no options data")

    # -----------------------------------------------------------------------
    # Classification
    # -----------------------------------------------------------------------
    if critical_fails:
        status = "BROKEN"
    elif degraded_fails:
        status = "DEGRADED"
    else:
        status = "VALID"

    return {
        "ticker": ticker,
        "status": status,
        "critical_fails": critical_fails,
        "degraded_fails": degraded_fails,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------
def compute_lane_stats(results):
    """Compute per-lane pass/fail/coverage stats."""
    total = len(results)
    lanes = {
        "identity": {
            "checks": ["in_universe", "has_cusip", "in_market_data", "in_price_history"],
            "pass": defaultdict(int),
        },
        "market_data": {
            "checks": [
                "mkt_has_price",
                "mkt_has_market_cap",
                "mkt_has_collected_at",
                "mkt_collected_recent",
                "mkt_has_avg_volume",
                "mkt_has_beta",
            ],
            "pass": defaultdict(int),
        },
        "price_history": {
            "checks": ["ph_has_data", "ph_recent", "ph_positive", "ph_no_impossible"],
            "pass": defaultdict(int),
        },
        "institutional": {
            "checks": ["inst_has_entry", "inst_elite_count_valid", "inst_score_z_valid"],
            "pass": defaultdict(int),
        },
        "inst_delta": {
            "checks": ["delta_has_entry", "delta_net_valid"],
            "pass": defaultdict(int),
        },
        "rankings": {
            "checks": [
                "rank_has_row",
                "rank_has_actionable_rank",
                "rank_has_coinvest_z",
                "rank_has_financial_score",
                "rank_has_catalyst_days",
                "rank_has_catalyst_family",
                "rank_has_clinical_score",
                "rank_has_selector_score",
                "rank_no_impossible",
            ],
            "pass": defaultdict(int),
        },
        "catalyst": {
            "checks": ["cat_days_range", "cat_family_valid", "cat_is_hard_bool", "cat_source_present"],
            "pass": defaultdict(int),
        },
        "financial": {
            "checks": ["fin_score_range", "fin_score_nonneg"],
            "pass": defaultdict(int),
        },
        "options": {
            "checks": ["opt_has_data", "opt_has_iv"],
            "pass": defaultdict(int),
        },
        "cross_source": {
            "checks": ["cross_sponsor_vs_inst", "cross_coinvest_tag_vs_elite"],
            "pass": defaultdict(int),
        },
    }

    for r in results:
        for lane_name, lane in lanes.items():
            for ck in lane["checks"]:
                val = r["checks"].get(ck)
                if val is True:
                    lane["pass"][ck] += 1
                elif val is None:
                    lane["pass"][f"{ck}_NA"] = lane["pass"].get(f"{ck}_NA", 0) + 1

    # Build summary dicts
    summary = {}
    for lane_name, lane in lanes.items():
        checks_summary = {}
        for ck in lane["checks"]:
            passed = lane["pass"][ck]
            na_count = lane["pass"].get(f"{ck}_NA", 0)
            failed = total - passed - na_count
            checks_summary[ck] = {
                "pass": passed,
                "fail": failed,
                "na": na_count,
                "pct_pass": round(100 * passed / total, 1) if total else 0,
            }
        summary[lane_name] = checks_summary

    return summary


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def print_summary(results, lane_stats):
    total = len(results)
    valid = sum(1 for r in results if r["status"] == "VALID")
    degraded = sum(1 for r in results if r["status"] == "DEGRADED")
    broken = sum(1 for r in results if r["status"] == "BROKEN")

    print("=" * 72)
    print("FULL DATA AUDIT SUMMARY")
    print("=" * 72)
    print(f"Total tickers: {total}")
    print(f"  VALID:    {valid:4d} ({100*valid/total:.1f}%)")
    print(f"  DEGRADED: {degraded:4d} ({100*degraded/total:.1f}%)")
    print(f"  BROKEN:   {broken:4d} ({100*broken/total:.1f}%)")
    print()

    # Per-lane summary
    print("-" * 72)
    print(f"{'LANE':<20} {'CHECK':<35} {'PASS':>5} {'FAIL':>5} {'N/A':>5} {'%':>6}")
    print("-" * 72)
    for lane_name, checks in lane_stats.items():
        for ck, stats in checks.items():
            print(
                f"{lane_name:<20} {ck:<35} "
                f"{stats['pass']:>5} {stats['fail']:>5} {stats['na']:>5} "
                f"{stats['pct_pass']:>5.1f}%"
            )
        print()

    # BROKEN tickers
    broken_list = [r for r in results if r["status"] == "BROKEN"]
    if broken_list:
        print("=" * 72)
        print(f"BROKEN TICKERS ({len(broken_list)})")
        print("=" * 72)
        for r in sorted(broken_list, key=lambda x: x["ticker"]):
            print(f"  {r['ticker']:<10} {'; '.join(r['critical_fails'])}")
        print()

    # DEGRADED tickers
    degraded_list = [r for r in results if r["status"] == "DEGRADED"]
    if degraded_list:
        print("=" * 72)
        print(f"DEGRADED TICKERS ({len(degraded_list)})")
        print("=" * 72)
        for r in sorted(degraded_list, key=lambda x: x["ticker"]):
            fails = r["degraded_fails"]
            # Truncate for readability
            summary_str = "; ".join(fails[:5])
            if len(fails) > 5:
                summary_str += f" ... (+{len(fails)-5} more)"
            print(f"  {r['ticker']:<10} {summary_str}")
        print()

    # Cross-source mismatches (the CUSIP bug check)
    cross_mismatches = [
        r
        for r in results
        if r["checks"].get("cross_sponsor_vs_inst") is False or r["checks"].get("cross_coinvest_tag_vs_elite") is False
    ]
    if cross_mismatches:
        print("=" * 72)
        print(f"CROSS-SOURCE MISMATCHES (CUSIP BUG CANDIDATES): {len(cross_mismatches)}")
        print("=" * 72)
        for r in sorted(cross_mismatches, key=lambda x: x["ticker"]):
            for f in r["critical_fails"]:
                if "CUSIP BUG" in f:
                    print(f"  {r['ticker']:<10} {f}")
        print()


def write_outputs(results, lane_stats, snapshot_date):
    out_dir = BASE / "artifacts" / "data_audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(results)
    valid = sum(1 for r in results if r["status"] == "VALID")
    degraded = sum(1 for r in results if r["status"] == "DEGRADED")
    broken = sum(1 for r in results if r["status"] == "BROKEN")

    # ---- JSON matrix ----
    matrix = {
        "schema": "ticker_validation_matrix.v1",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "valid": valid,
            "degraded": degraded,
            "broken": broken,
        },
        "lane_stats": lane_stats,
        "tickers": {
            r["ticker"]: {
                "status": r["status"],
                "critical_fails": r["critical_fails"],
                "degraded_fails": r["degraded_fails"],
                "checks": {k: v for k, v in r["checks"].items()},
            }
            for r in results
        },
    }

    matrix_path = out_dir / "ticker_validation_matrix.json"
    with open(matrix_path, "w") as f:
        json.dump(matrix, f, indent=2, default=str)
    print(f"Wrote: {matrix_path}")

    # ---- Markdown summary ----
    lines = []
    lines.append(f"# Data Audit Summary - {snapshot_date}")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- Total tickers: {total}")
    lines.append(f"- VALID: {valid} ({100*valid/total:.1f}%)")
    lines.append(f"- DEGRADED: {degraded} ({100*degraded/total:.1f}%)")
    lines.append(f"- BROKEN: {broken} ({100*broken/total:.1f}%)")
    lines.append("")

    lines.append("## Per-Lane Statistics")
    lines.append("")
    lines.append("| Lane | Check | Pass | Fail | N/A | % |")
    lines.append("|------|-------|------|------|-----|---|")
    for lane_name, checks in lane_stats.items():
        for ck, stats in checks.items():
            lines.append(
                f"| {lane_name} | {ck} | {stats['pass']} | "
                f"{stats['fail']} | {stats['na']} | {stats['pct_pass']:.1f}% |"
            )
    lines.append("")

    # BROKEN
    broken_list = [r for r in results if r["status"] == "BROKEN"]
    if broken_list:
        lines.append(f"## BROKEN Tickers ({len(broken_list)})")
        lines.append("")
        for r in sorted(broken_list, key=lambda x: x["ticker"]):
            lines.append(f"- **{r['ticker']}**: {'; '.join(r['critical_fails'])}")
        lines.append("")

    # Cross-source mismatches
    cross_mismatches = [
        r
        for r in results
        if r["checks"].get("cross_sponsor_vs_inst") is False or r["checks"].get("cross_coinvest_tag_vs_elite") is False
    ]
    if cross_mismatches:
        lines.append(f"## Cross-Source Mismatches (CUSIP Bug Candidates): {len(cross_mismatches)}")
        lines.append("")
        for r in sorted(cross_mismatches, key=lambda x: x["ticker"]):
            for fail in r["critical_fails"]:
                if "CUSIP BUG" in fail:
                    lines.append(f"- **{r['ticker']}**: {fail}")
        lines.append("")

    # DEGRADED
    degraded_list = [r for r in results if r["status"] == "DEGRADED"]
    if degraded_list:
        lines.append(f"## DEGRADED Tickers ({len(degraded_list)})")
        lines.append("")
        for r in sorted(degraded_list, key=lambda x: x["ticker"]):
            lines.append(f"- **{r['ticker']}**: {'; '.join(r['degraded_fails'][:5])}")
        lines.append("")

    md_path = out_dir / "audit_summary.md"
    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote: {md_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Full data audit across all input lanes")
    parser.add_argument(
        "--snapshot-date",
        default="2026-04-06",
        help="Snapshot date to audit (default: 2026-04-06)",
    )
    args = parser.parse_args()
    snapshot_date = args.snapshot_date

    # Reference date for recency checks
    try:
        ref_date = datetime.strptime(snapshot_date, "%Y-%m-%d")
    except ValueError:
        ref_date = datetime.now()

    # Load all data once
    data = load_all_data(snapshot_date)

    if not data["universe_tickers"]:
        print("ERROR: No tickers in universe. Aborting.")
        sys.exit(1)

    # Build the full ticker set: universe + anything that appears in any source
    # (catches orphans in data files not in universe)
    all_tickers = set(data["universe_tickers"])
    all_tickers |= set(data["market_data"].keys())
    all_tickers |= set(data["rankings"].keys())
    all_tickers |= set(data["inst_summary"].keys())

    print(
        f"Auditing {len(all_tickers)} tickers "
        f"({len(data['universe_tickers'])} in universe, "
        f"{len(all_tickers) - len(data['universe_tickers'])} orphans in other sources)"
    )
    print()

    # Validate each ticker
    results = []
    for ticker in sorted(all_tickers):
        result = validate_ticker(ticker, data, ref_date)
        results.append(result)

    # Compute lane stats
    lane_stats = compute_lane_stats(results)

    # Print
    print_summary(results, lane_stats)

    # Write outputs
    write_outputs(results, lane_stats, snapshot_date)

    # Exit code: 1 if any BROKEN
    broken_count = sum(1 for r in results if r["status"] == "BROKEN")
    if broken_count > 0:
        print(f"\nExit code 1: {broken_count} BROKEN tickers found.")
        sys.exit(1)
    else:
        print("\nExit code 0: No BROKEN tickers.")
        sys.exit(0)


if __name__ == "__main__":
    main()
