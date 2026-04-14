#!/usr/bin/env python3
"""Lightweight heartbeat checks for Tier 2 agents.

Replaces 6 LLM-based OpenClaw agents with cheap file/JSON checks.
Only invokes an LLM (via OpenClaw) when anomalies are detected.

Usage:
    python tools/agent_heartbeat_checks.py                    # run all checks
    python tools/agent_heartbeat_checks.py --agent qa         # run one agent
    python tools/agent_heartbeat_checks.py --dry-run          # print, don't escalate
    python tools/agent_heartbeat_checks.py --date 2026-04-02  # check specific date
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
LOGS_DIR = REPO_ROOT / "logs"
OPENCLAW = REPO_ROOT / "tools" / "run_openclaw.sh"

# ── Result types ──────────────────────────────────────────────


class CheckResult:
    def __init__(self, agent: str, status: str, detail: str = "", anomalies: list = None):
        self.agent = agent
        self.status = status  # OK, WARN, FAIL, STALE, SKIP
        self.detail = detail
        self.anomalies = anomalies or []

    @property
    def needs_llm(self):
        return self.status in ("WARN", "FAIL") and len(self.anomalies) > 0

    def __repr__(self):
        sym = {"OK": "✓", "WARN": "⚠", "FAIL": "✗", "STALE": "◌", "SKIP": "–"}
        s = f"  {sym.get(self.status, '?')} {self.agent}: {self.status}"
        if self.detail:
            s += f" — {self.detail}"
        if self.anomalies:
            for a in self.anomalies:
                s += f"\n      → {a}"
        return s


def as_of_date(dt: date) -> str:
    return dt.strftime("%Y-%m-%d")


# ── QA Agent ──────────────────────────────────────────────────


def check_qa(dt: date) -> CheckResult:
    """Validate today's snapshot exists and is structurally sound."""
    ds = as_of_date(dt)
    snap = SNAPSHOT_DIR / ds
    anomalies = []

    if not snap.is_dir():
        return CheckResult("qa", "STALE", f"No snapshot for {ds}")

    # Check critical files
    for fname in ["rankings.csv", "metadata.json"]:
        if not (snap / fname).exists():
            anomalies.append(f"OUTPUT_MISSING: {fname}")

    # Validate metadata date
    meta_path = snap / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            if meta.get("as_of_date") != ds:
                anomalies.append(f"DATE_MISMATCH: metadata says {meta.get('as_of_date')}, expected {ds}")
        except (json.JSONDecodeError, KeyError) as e:
            anomalies.append(f"METADATA_CORRUPT: {e}")

    # Check phase2 health
    p2 = snap / "phase2_health.json"
    if p2.exists():
        try:
            health = json.loads(p2.read_text())
            status = health.get("status", "UNKNOWN")
            if status == "FAIL":
                anomalies.append(f"PHASE2_FAIL: {health.get('message', 'no detail')}")
        except json.JSONDecodeError:
            anomalies.append("PHASE2_CORRUPT: cannot parse phase2_health.json")

    # Check production log for tracebacks
    log = LOGS_DIR / f"daily_production_{ds}.log"
    if log.exists():
        text = log.read_text()
        if "Traceback" in text and "snapshot promoted" not in text.lower():
            anomalies.append("PIPELINE_CRASH_SUSPECTED: traceback in production log without promotion")

    if anomalies:
        return CheckResult("qa", "FAIL", f"{len(anomalies)} issue(s)", anomalies)
    return CheckResult("qa", "OK", f"Snapshot {ds} valid")


# ── IC Health Monitor ─────────────────────────────────────────


def check_ic_health(dt: date) -> CheckResult:
    """Check IC dashboard exists and signal health."""
    ds = as_of_date(dt)
    dash_path = ARTIFACTS_DIR / "ic_dashboard" / f"{ds}_dashboard.json"
    anomalies = []

    if not dash_path.exists():
        return CheckResult("ic_health_monitor", "STALE", f"No dashboard for {ds}")

    try:
        dash = json.loads(dash_path.read_text())
    except json.JSONDecodeError:
        return CheckResult("ic_health_monitor", "FAIL", "Dashboard corrupt", ["CORRUPT_DASHBOARD"])

    attention = dash.get("attention", "UNKNOWN")
    signals = dash.get("signals", {})

    for sig_name, sig_data in signals.items():
        health = sig_data.get("health", "UNKNOWN") if isinstance(sig_data, dict) else "UNKNOWN"
        if health in ("ALERT", "CRITICAL"):
            anomalies.append(f"SIGNAL_{health}: {sig_name}")
        elif health == "WARN":
            anomalies.append(f"SIGNAL_WARN: {sig_name}")

    # Check history for trend decay (3+ consecutive IC drops)
    hist_path = ARTIFACTS_DIR / "ic_dashboard" / "history.jsonl"
    if hist_path.exists():
        lines = hist_path.read_text().strip().split("\n")
        if len(lines) >= 5:
            try:
                recent = [json.loads(line) for line in lines[-5:]]
                for sig_name in signals:
                    ics = [
                        r.get("signals", {}).get(sig_name, {}).get("ic")
                        for r in recent
                        if isinstance(r.get("signals", {}).get(sig_name), dict)
                    ]
                    ics = [x for x in ics if x is not None]
                    if len(ics) >= 4:
                        drops = sum(1 for i in range(1, len(ics)) if ics[i] < ics[i - 1])
                        if drops >= 3:
                            anomalies.append(f"TREND_DECAY: {sig_name} ({drops} consecutive IC drops)")
            except json.JSONDecodeError:
                pass

    if any("ALERT" in a or "CRITICAL" in a for a in anomalies):
        return CheckResult("ic_health_monitor", "FAIL", f"attention={attention}", anomalies)
    if anomalies:
        return CheckResult("ic_health_monitor", "WARN", f"attention={attention}", anomalies)
    return CheckResult("ic_health_monitor", "OK", f"attention={attention}")


# ── Fleet Steward ─────────────────────────────────────────────


def check_fleet_steward(dt: date) -> CheckResult:
    """Check fleet-wide artifact freshness."""
    ds = as_of_date(dt)
    anomalies = []

    # Production snapshot
    if not (SNAPSHOT_DIR / ds / "rankings.csv").exists():
        anomalies.append("MISSING: today's snapshot")

    # Artifact freshness checks
    checks = {
        "ops_digest": ARTIFACTS_DIR / "ops_digest" / f"{ds}_digest.json",
        "ic_dashboard": ARTIFACTS_DIR / "ic_dashboard" / f"{ds}_dashboard.json",
        "shadow_monitor": ARTIFACTS_DIR / "shadow_monitor" / f"{ds}_monitor.json",
    }
    for name, path in checks.items():
        if not path.exists():
            # Only flag if past expected production time (5:30 PM ET)
            if datetime.now().hour >= 18:
                anomalies.append(f"STALE: {name} missing for {ds}")

    # Earnings ICS freshness (< 2 days old)
    ics_path = ARTIFACTS_DIR / "earnings_sync" / "biotech_earnings.ics"
    if ics_path.exists():
        age_hours = (datetime.now().timestamp() - ics_path.stat().st_mtime) / 3600
        if age_hours > 48:
            anomalies.append(f"STALE: earnings ICS {age_hours:.0f}h old")
    else:
        anomalies.append("MISSING: earnings ICS")

    # CRT join table freshness (< 3 days)
    crt_join = REPO_ROOT / "output" / "catalyst_ev" / "crt_options_join.json"
    if crt_join.exists():
        age_hours = (datetime.now().timestamp() - crt_join.stat().st_mtime) / 3600
        if age_hours > 72:
            anomalies.append(f"STALE: CRT join table {age_hours:.0f}h old")

    if anomalies:
        return CheckResult(
            "fleet_steward", "WARN" if len(anomalies) <= 2 else "FAIL", f"{len(anomalies)} issue(s)", anomalies
        )
    return CheckResult("fleet_steward", "OK", "All artifacts fresh")


# ── Calibration ───────────────────────────────────────────────


def check_calibration(dt: date) -> CheckResult:
    """Check for new candidate rulesets needing review."""
    rulesets_dir = REPO_ROOT / "production_data" / "decision_rulesets"
    anomalies = []

    if not rulesets_dir.is_dir():
        return CheckResult("calibration", "OK", "No rulesets directory")

    # Find candidate files newer than 48h
    cutoff = datetime.now().timestamp() - 48 * 3600
    candidates = []
    for f in rulesets_dir.glob("candidate_*.json"):
        if f.stat().st_mtime > cutoff:
            candidates.append(f.name)

    if candidates:
        # Check if calibration note exists for today
        note = REPO_ROOT / "output" / "calibration" / "calibration_note.md"
        if not note.exists() or note.stat().st_mtime < cutoff:
            anomalies.append(f"CALIBRATION_REVIEW_NEEDED: {len(candidates)} candidate(s): {', '.join(candidates)}")

    if anomalies:
        return CheckResult("calibration", "WARN", "New candidates", anomalies)
    return CheckResult("calibration", "OK", "No pending candidates")


# ── Shadow Monitor ────────────────────────────────────────────


def check_shadow_monitor(dt: date) -> CheckResult:
    """Check shadow portfolio performance for anomalies."""
    ds = as_of_date(dt)
    anomalies = []

    monitor_path = ARTIFACTS_DIR / "shadow_monitor" / f"{ds}_monitor.json"
    if not monitor_path.exists():
        return CheckResult("shadow_monitor", "STALE", f"No monitor for {ds}")

    try:
        monitor = json.loads(monitor_path.read_text())
    except json.JSONDecodeError:
        return CheckResult("shadow_monitor", "FAIL", "Monitor corrupt", ["CORRUPT"])

    # Check alert codes from the monitor
    alerts = monitor.get("alerts", [])
    alert_level = monitor.get("attention", "UNKNOWN")

    for alert in alerts:
        code = alert.get("code", "") if isinstance(alert, dict) else str(alert)
        if any(
            x in str(code).upper()
            for x in ("DRAWDOWN_STREAK", "SINGLE_DAY_LOSS", "EXCESS_DETERIORATION", "MAX_DRAWDOWN")
        ):
            anomalies.append(f"PERF_ALERT: {code}")

    # Fallback: read performance.csv for streak detection
    perf_path = ARTIFACTS_DIR / "live_shadow" / "performance.csv"
    if perf_path.exists() and not anomalies:
        try:
            lines = perf_path.read_text().strip().split("\n")
            if len(lines) > 3:
                # Simple: check last 5 days for consecutive losses
                recent = lines[-6:]  # header + 5 rows
                if len(recent) > 1:
                    header = recent[0].split(",")
                    pnl_idx = next(
                        (i for i, h in enumerate(header) if "pnl" in h.lower() or "return" in h.lower()), None
                    )
                    if pnl_idx is not None:
                        losses = 0
                        for row in recent[1:]:
                            cols = row.split(",")
                            if len(cols) > pnl_idx:
                                try:
                                    if float(cols[pnl_idx]) < 0:
                                        losses += 1
                                    else:
                                        losses = 0
                                except ValueError:
                                    pass
                        if losses >= 3:
                            anomalies.append(f"DRAWDOWN_STREAK: {losses} consecutive losing days")
        except Exception:
            pass

    if anomalies:
        return CheckResult(
            "shadow_monitor", "FAIL" if len(anomalies) > 1 else "WARN", f"attention={alert_level}", anomalies
        )
    return CheckResult("shadow_monitor", "OK", f"attention={alert_level}")


# ── AACT Trial Ingest ─────────────────────────────────────────


def check_aact_ingest(dt: date) -> CheckResult:
    """Check AACT ingest ran and produced healthy output."""
    ds = as_of_date(dt)
    aact_snap = REPO_ROOT / "data" / "aact" / "snapshots" / ds
    anomalies = []

    if not aact_snap.is_dir():
        # Check if any recent snapshot exists (within 8 days — AACT is weekly)
        aact_base = REPO_ROOT / "data" / "aact" / "snapshots"
        if aact_base.is_dir():
            snaps = sorted(
                (d for d in aact_base.iterdir() if d.is_dir() and (d / "aact_health.json").exists()),
                reverse=True,
            )
            if snaps:
                latest = snaps[0].name
                age = (dt - date.fromisoformat(latest)).days if latest >= "2020" else 999
                if age <= 8:
                    return CheckResult("aact_trial_ingest", "OK", f"Latest snapshot: {latest} ({age}d old, weekly)")
        return CheckResult("aact_trial_ingest", "STALE", f"No AACT snapshot within 8d of {ds}")

    # Check health report
    health_path = aact_snap / "aact_health.json"
    if health_path.exists():
        try:
            health = json.loads(health_path.read_text())
            n_trials = health.get("n_trials", 0)
            n_linked = health.get("n_linked_to_ticker", 0)
            if n_trials == 0:
                anomalies.append("EMPTY_SNAPSHOT: 0 trials")
            if n_linked == 0 and n_trials > 0:
                anomalies.append("LINKAGE_BROKEN: 0 linked to tickers")
            schema_drift = health.get("schema_drift", [])
            if schema_drift:
                anomalies.append(f"SCHEMA_DRIFT: {', '.join(schema_drift[:3])}")
        except json.JSONDecodeError:
            anomalies.append("HEALTH_CORRUPT")
    else:
        anomalies.append("HEALTH_MISSING")

    # Check key outputs exist
    for fname in ["trial_master.json", "trial_status_deltas.jsonl"]:
        if not (aact_snap / fname).exists():
            anomalies.append(f"OUTPUT_MISSING: {fname}")

    if anomalies:
        return CheckResult(
            "aact_trial_ingest", "WARN" if len(anomalies) <= 1 else "FAIL", f"{len(anomalies)} issue(s)", anomalies
        )
    return CheckResult("aact_trial_ingest", "OK", f"Snapshot {ds} healthy")


# ── Biotech News Digest ──────────────────────────────────────


def check_news_digest(dt: date) -> CheckResult:
    """Verify news digests were produced.

    The evening digest arrives at ~18:00 ET, but heartbeat runs at 17:30.
    To avoid false positives, check yesterday's (completed) digest counts
    when running before 19:00, and today's only at/after 19:00.
    """
    ds = as_of_date(dt)
    anomalies = []
    digest_dir = ARTIFACTS_DIR / "news_digest"

    if not digest_dir.is_dir():
        return CheckResult("biotech_news_digest", "STALE", "No news_digest artifact directory")

    hour = datetime.now().hour
    today_digests = list(digest_dir.glob(f"biotech_news_digest_{ds}_*.json"))

    if hour >= 19:
        # After all scheduled digests: check today
        if len(today_digests) == 0:
            anomalies.append("MISSED_ALL: no digest by 19:00")
        elif len(today_digests) < 2:
            anomalies.append(f"DIGEST_LAG: only {len(today_digests)} digest(s) by 19:00")
    else:
        # Before evening digest: check yesterday (completed day) instead
        from datetime import timedelta

        yesterday = dt - timedelta(days=1)
        yesterday_ds = as_of_date(yesterday)
        yesterday_digests = list(digest_dir.glob(f"biotech_news_digest_{yesterday_ds}_*.json"))
        if yesterday_digests is not None and len(yesterday_digests) == 0:
            # Skip weekends — no digests expected
            if yesterday.weekday() < 5:
                anomalies.append(f"MISSED_YESTERDAY: no digest for {yesterday_ds}")

    # Check press release freshness
    pr_dir = REPO_ROOT / "data" / "press_releases"
    if pr_dir.is_dir():
        pr_files = sorted(pr_dir.iterdir(), reverse=True)
        if pr_files:
            latest_name = pr_files[0].name
            try:
                latest_date = date.fromisoformat(latest_name[:10])
                age = (dt - latest_date).days
                if age > 2:
                    anomalies.append(f"STALE_SOURCE: press_releases last updated {age}d ago")
            except ValueError:
                pass

    # Check delivery log for failures
    delivery_log = digest_dir / "delivery_log.jsonl"
    if delivery_log.exists():
        try:
            lines = delivery_log.read_text().strip().split("\n")
            today_lines = [ln for ln in lines[-20:] if ds in ln]
            for line in today_lines:
                entry = json.loads(line)
                if entry.get("status") == "FAIL":
                    anomalies.append(f"DELIVERY_FAIL: {entry.get('window', 'unknown')} send failed")
        except (json.JSONDecodeError, ValueError):
            pass

    if anomalies:
        return CheckResult(
            "biotech_news_digest", "WARN" if len(anomalies) <= 1 else "FAIL", f"{len(anomalies)} issue(s)", anomalies
        )
    return CheckResult("biotech_news_digest", "OK", f"{len(today_digests)} digest(s) for {ds}")


# ── Calibration Evidence ─────────────────────────────────────


def check_calibration_evidence(dt: date) -> CheckResult:
    """Verify calibration evidence ledger is reasonably fresh (weekly tolerance)."""
    evidence_dir = ARTIFACTS_DIR / "calibration_evidence"
    anomalies = []

    if not evidence_dir.is_dir():
        return CheckResult("calibration_evidence", "STALE", "No calibration_evidence directory")

    ledger = evidence_dir / "ledger.jsonl"
    if not ledger.exists():
        return CheckResult("calibration_evidence", "STALE", "No evidence ledger")

    # Check ledger freshness (tolerate up to 10 calendar days / ~7 trading days)
    try:
        mtime = datetime.fromtimestamp(ledger.stat().st_mtime).date()
        age = (dt - mtime).days
        if age > 10:
            anomalies.append(f"STALE_LEDGER: last modified {age}d ago (limit 10d)")
    except OSError:
        anomalies.append("LEDGER_STAT_FAIL: cannot read file mtime")

    # Check for recent evidence files
    evidence_files = sorted(evidence_dir.glob("*_evidence.json"), reverse=True)
    if not evidence_files:
        anomalies.append("NO_EVIDENCE_FILES: directory empty")
    elif evidence_files:
        latest = evidence_files[0].name[:10]
        try:
            latest_date = date.fromisoformat(latest)
            age = (dt - latest_date).days
            if age > 10:
                anomalies.append(f"STALE_EVIDENCE: latest file is {age}d old")
        except ValueError:
            pass

    if anomalies:
        return CheckResult(
            "calibration_evidence", "WARN" if len(anomalies) <= 1 else "FAIL", f"{len(anomalies)} issue(s)", anomalies
        )
    return CheckResult("calibration_evidence", "OK", f"Ledger fresh, {len(evidence_files)} evidence file(s)")


# ── Data Auditor ─────────────────────────────────────────────


def check_data_auditor(dt: date) -> CheckResult:
    """Verify data auditor produced today's integrity report."""
    ds = as_of_date(dt)
    auditor_dir = ARTIFACTS_DIR / "data_auditor"
    anomalies = []

    if not auditor_dir.is_dir():
        return CheckResult("data_auditor", "STALE", "No data_auditor directory")

    report_path = auditor_dir / f"integrity_report_{ds}.json"
    if not report_path.exists():
        # Check most recent report
        reports = sorted(auditor_dir.glob("integrity_report_*.json"), reverse=True)
        if not reports:
            return CheckResult("data_auditor", "STALE", "No integrity reports found")
        latest = reports[0].name
        latest_date_str = latest.replace("integrity_report_", "").replace(".json", "")
        try:
            age = (dt - date.fromisoformat(latest_date_str)).days
            if age > 2:
                return CheckResult("data_auditor", "STALE", f"Latest report {age}d old ({latest_date_str})")
        except ValueError:
            pass
        report_path = reports[0]

    # Read the report verdict
    try:
        report = json.loads(report_path.read_text())
        verdict = report.get("verdict", "UNKNOWN")
        if verdict == "FAIL":
            issues = report.get("issues", [])
            for issue in issues[:5]:
                anomalies.append(
                    f"INTEGRITY_{issue.get('severity', 'UNKNOWN').upper()}: {issue.get('check', 'unknown')}"
                )
            return CheckResult("data_auditor", "FAIL", "Integrity verdict: FAIL", anomalies)
        elif verdict == "WARN":
            return CheckResult(
                "data_auditor",
                "WARN",
                "Integrity verdict: WARN",
                [f"WARN: {i.get('check', '?')}" for i in report.get("issues", [])[:3]],
            )
    except (json.JSONDecodeError, KeyError):
        anomalies.append("REPORT_CORRUPT: cannot parse integrity report")
        return CheckResult("data_auditor", "FAIL", "Report corrupt", anomalies)

    return CheckResult("data_auditor", "OK", f"Integrity report {report_path.name}: PASS")


# ── Orchestrator ──────────────────────────────────────────────

AGENTS = {
    "qa": check_qa,
    "ic_health_monitor": check_ic_health,
    "fleet_steward": check_fleet_steward,
    "calibration": check_calibration,
    "shadow_watch": check_shadow_monitor,
    "aact_trial_ingest": check_aact_ingest,
    "herald": check_news_digest,
    "calibration_evidence": check_calibration_evidence,
    "data_auditor": check_data_auditor,
}


def _write_anomaly_file(results: list[CheckResult], dt: date):
    """Write anomaly summary to local file as durable record."""
    ds = as_of_date(dt)
    heartbeat_dir = ARTIFACTS_DIR / "heartbeat"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    out_path = heartbeat_dir / f"{ds}_anomalies.md"

    lines = [f"# Heartbeat Anomalies — {ds}\n"]
    lines.append(f"Generated: {datetime.now().isoformat()}\n")
    for r in results:
        if r.needs_llm:
            lines.append(f"\n## [{r.agent}] {r.status} — {r.detail}\n")
            for a in r.anomalies:
                lines.append(f"- {a}\n")
    out_path.write_text("".join(lines))
    print(f"  Anomaly summary written to {out_path}")


def escalate_to_llm(results: list[CheckResult], dry_run: bool = False, dt: date | None = None):
    """Send anomalies to OpenClaw LLM for interpretation."""
    anomaly_results = [r for r in results if r.needs_llm]
    if not anomaly_results:
        return

    # Always write anomalies to local file as durable fallback
    if dt is not None:
        _write_anomaly_file(anomaly_results, dt)

    summary = "ANOMALIES DETECTED — interpret and recommend action:\n\n"
    for r in anomaly_results:
        summary += f"[{r.agent}] {r.status}: {r.detail}\n"
        for a in r.anomalies:
            summary += f"  - {a}\n"
        summary += "\n"

    summary += "For each anomaly: (1) is it actionable? (2) what's the fix? (3) severity 1-5?"

    if dry_run:
        print(f"\n  Would escalate to LLM:\n  {summary}")
        return

    print(f"\n  Escalating {len(anomaly_results)} agent(s) to LLM...")
    try:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "run_agent_direct.py"), "--agent", "ops", "--message", summary],
            capture_output=True,
            text=True,
            timeout=150,
            cwd=str(REPO_ROOT),
        )
        if result.stdout.strip():
            response_text = result.stdout.strip()
            if "rejected" in response_text.lower() or "credit" in response_text.lower():
                print("\n  LLM escalation rejected (API billing). Anomalies saved to artifacts/heartbeat/.")
            else:
                print(f"\n  LLM response:\n{response_text}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"\n  LLM escalation failed: {e}. Anomalies saved to artifacts/heartbeat/.")


def main():
    parser = argparse.ArgumentParser(description="Tier 2 agent heartbeat checks")
    parser.add_argument("--agent", choices=list(AGENTS.keys()), help="Run single agent check")
    parser.add_argument("--date", type=str, help="Check date (YYYY-MM-DD), default today")
    parser.add_argument("--dry-run", action="store_true", help="Print anomalies, don't escalate")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    dt = date.fromisoformat(args.date) if args.date else date.today()
    agents_to_run = {args.agent: AGENTS[args.agent]} if args.agent else AGENTS

    print(f"Heartbeat checks for {as_of_date(dt)}")
    print(f"{'=' * 50}")

    results = []
    for name, check_fn in agents_to_run.items():
        try:
            result = check_fn(dt)
        except Exception as e:
            result = CheckResult(name, "FAIL", f"Check crashed: {e}", [f"EXCEPTION: {e}"])
        results.append(result)
        print(result)

    # Summary
    ok = sum(1 for r in results if r.status == "OK")
    warn = sum(1 for r in results if r.status == "WARN")
    fail = sum(1 for r in results if r.status == "FAIL")
    stale = sum(1 for r in results if r.status == "STALE")
    total_anomalies = sum(len(r.anomalies) for r in results)

    print(f"\n  Summary: {ok} OK, {warn} WARN, {fail} FAIL, {stale} STALE — {total_anomalies} anomalies")

    if args.json:
        out = [{"agent": r.agent, "status": r.status, "detail": r.detail, "anomalies": r.anomalies} for r in results]
        print(json.dumps(out, indent=2))

    # Escalate anomalies to LLM
    if total_anomalies > 0:
        escalate_to_llm(results, dry_run=args.dry_run, dt=dt)
    else:
        print("  No anomalies — LLM not needed.")

    sys.exit(1 if fail > 0 else 0)


if __name__ == "__main__":
    main()
