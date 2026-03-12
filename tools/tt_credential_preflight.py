#!/usr/bin/env python3
"""Tastytrade credential preflight check.

Quick one-command check that TT_SECRET and TT_REFRESH are set and that the
tastytrade API responds.  Designed to be run before a production screen to
confirm options diagnostics will produce usable data.

Exit codes:
  0 — PASS (credentials set, API reachable)
  1 — FAIL (credentials missing or API unreachable)
  2 — WARN (credentials set but API returned unexpected response)

Usage:
    python tools/tt_credential_preflight.py
    python tools/tt_credential_preflight.py --json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, WARN, FAIL
    detail: str
    value: Any = None


@dataclass
class PreflightResult:
    schema: str = "tt_credential_preflight.v1"
    overall: str = "PASS"
    can_proceed: bool = True
    checks: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_env_vars() -> CheckResult:
    """Check that TT_SECRET and TT_REFRESH are set in the environment."""
    tt_secret = os.environ.get("TT_SECRET", "")
    tt_refresh = os.environ.get("TT_REFRESH", "")

    if not tt_secret and not tt_refresh:
        return CheckResult(
            "env_vars",
            "FAIL",
            "TT_SECRET and TT_REFRESH are both missing. " "Set them in .env or export them in your shell.",
        )
    if not tt_secret:
        return CheckResult(
            "env_vars",
            "FAIL",
            "TT_SECRET is missing (TT_REFRESH is set).",
        )
    if not tt_refresh:
        return CheckResult(
            "env_vars",
            "FAIL",
            "TT_REFRESH is missing (TT_SECRET is set).",
        )

    return CheckResult(
        "env_vars",
        "PASS",
        f"TT_SECRET ({len(tt_secret)} chars) and TT_REFRESH ({len(tt_refresh)} chars) are set.",
        value={"tt_secret_len": len(tt_secret), "tt_refresh_len": len(tt_refresh)},
    )


def check_dotenv_file() -> CheckResult:
    """Check that .env file exists and contains TT credentials."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return CheckResult(
            "dotenv_file",
            "WARN",
            f".env not found at {env_path}. Credentials must come from shell environment.",
        )

    content = env_path.read_text()
    has_secret = "TT_SECRET=" in content  # pragma: allowlist secret
    has_refresh = "TT_REFRESH=" in content

    if has_secret and has_refresh:
        return CheckResult(
            "dotenv_file",
            "PASS",
            f".env at {env_path} contains both TT_SECRET and TT_REFRESH.",
        )
    missing = []
    if not has_secret:
        missing.append("TT_SECRET")
    if not has_refresh:
        missing.append("TT_REFRESH")
    return CheckResult(
        "dotenv_file",
        "WARN",
        f".env missing: {', '.join(missing)}. Must be set in shell environment.",
    )


def check_api_reachable() -> CheckResult:
    """Attempt a lightweight tastytrade session to verify credentials work."""
    try:
        from common.options_diagnostics import _has_credentials

        if not _has_credentials():
            return CheckResult(
                "api_reachable",
                "FAIL",
                "Credentials not available to options_diagnostics module.",
            )
    except ImportError:
        return CheckResult(
            "api_reachable",
            "WARN",
            "Could not import common.options_diagnostics.",
        )

    # Try a single-ticker diagnostic fetch to verify end-to-end
    try:
        from common.options_diagnostics import fetch_options_diagnostics

        result = fetch_options_diagnostics(["XBI"], as_of_date="2026-03-12")
        xbi = result.get("XBI", {})
        basis = xbi.get("opt_diagnostic_basis", "")

        if basis == "no_credentials":
            return CheckResult(
                "api_reachable",
                "FAIL",
                "API returned no_credentials despite env vars being set.",
            )
        if basis == "no_session":
            return CheckResult(
                "api_reachable",
                "FAIL",
                "Could not create tastytrade session. Credentials may be expired or invalid.",
            )
        if basis == "no_metrics":
            return CheckResult(
                "api_reachable",
                "WARN",
                "Session created but no metrics returned for XBI (may be normal for ETFs).",
                value={"diagnostic_basis": basis},
            )
        if xbi.get("opt_has_data") == "1":
            return CheckResult(
                "api_reachable",
                "PASS",
                f"API responded with live data (basis: {basis}).",
                value={"diagnostic_basis": basis, "opt_has_data": True},
            )

        return CheckResult(
            "api_reachable",
            "WARN",
            f"API responded but opt_has_data=0 (basis: {basis}).",
            value={"diagnostic_basis": basis},
        )

    except Exception as exc:
        return CheckResult(
            "api_reachable",
            "FAIL",
            f"API call failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_STATUS_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}


def run_preflight(*, skip_api: bool = False) -> PreflightResult:
    """Run all preflight checks and return aggregated result."""
    result = PreflightResult()

    checks = [check_dotenv_file(), check_env_vars()]
    if not skip_api:
        checks.append(check_api_reachable())

    worst = "PASS"
    for c in checks:
        result.checks.append(asdict(c))
        if _STATUS_ORDER.get(c.status, 0) > _STATUS_ORDER.get(worst, 0):
            worst = c.status

    result.overall = worst
    result.can_proceed = worst != "FAIL"
    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def format_text(result: PreflightResult) -> str:
    """Human-readable output."""
    lines = [f"TT Credential Preflight: {result.overall}"]
    lines.append("")
    for c in result.checks:
        marker = {"PASS": "+", "WARN": "~", "FAIL": "!"}[c["status"]]
        lines.append(f"  [{marker}] {c['name']}: {c['detail']}")
    lines.append("")
    if result.can_proceed:
        lines.append("Options diagnostics should produce usable data on next screen run.")
    else:
        lines.append("OPTIONS DATA WILL BE EMPTY on next screen run. Fix credentials first.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Tastytrade credential preflight")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--skip-api", action="store_true", help="Skip live API check")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    result = run_preflight(skip_api=args.skip_api)

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(format_text(result))

    if result.overall == "FAIL":
        sys.exit(1)
    elif result.overall == "WARN":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
