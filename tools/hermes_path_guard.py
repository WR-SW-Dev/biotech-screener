#!/usr/bin/env python3
"""Path guard: determine whether a write to a path is allowed for a given permission tier.

Usage:
    python3 tools/hermes_path_guard.py --check artifacts/my_agent/out.json --tier 0
    python3 tools/hermes_path_guard.py --check ranker/weights.json --authority observe_only
    python3 tools/hermes_path_guard.py --self-test

Exit codes:
    0 = allowed
    1 = blocked
    2 = invalid arguments / self-test failure
"""

from __future__ import annotations

import argparse
import sys

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

AUTHORITY_TO_TIER: dict[str, int] = {
    "observe_only": 0,
    "observe_and_propose": 1,
    "write_artifacts": 2,
    "mutate_data": 3,
    "mutate_config": 4,
}

TIER_TO_AUTHORITY: dict[int, str] = {v: k for k, v in AUTHORITY_TO_TIER.items()}

# Paths always frozen regardless of tier.
# Match as path prefixes (normalised, no leading slash).
ALWAYS_FROZEN: list[str] = [
    "ranker/",
    "selector/",
    "portfolio/",
    "sizing/",
    "final_score/",
    "data/snapshots",  # data/snapshots/ and data/snapshots_pit/
    "production_data/",
    "artifacts/generated/",
    ".env",
    ".github/workflows/",
]

# Paths blocked at Tier 0 (observe_only) beyond always-frozen.
TIER_0_BLOCKED: list[str] = [
    "specs/",
    "data/aact/",
    "data/sec/",
    "data/universe/",
    "output/catalyst_ev/",
]

# Paths blocked at Tier 1 (observe_and_propose).
TIER_1_BLOCKED: list[str] = [
    "data/aact/",
    "data/sec/",
    "data/universe/",
    "output/catalyst_ev/",
]

# Paths blocked at Tier 2 (write_artifacts).
TIER_2_BLOCKED: list[str] = [
    "data/aact/",
    "data/sec/",
    "data/universe/",
    "output/catalyst_ev/",
]

# Tier 3 may write data/ except frozen; config is still blocked.
TIER_3_BLOCKED: list[str] = [
    "specs/",
    ".github/workflows/",
    "CLAUDE.md",
]

# Tier 4 has no additional path blocks (operator-only).
TIER_4_BLOCKED: list[str] = []

_BLOCKED_BY_TIER: dict[int, list[str]] = {
    0: TIER_0_BLOCKED,
    1: TIER_1_BLOCKED,
    2: TIER_2_BLOCKED,
    3: TIER_3_BLOCKED,
    4: TIER_4_BLOCKED,
}


def _normalise(path: str) -> str:
    """Strip leading ./ and normalise separators to /."""
    p = path.replace("\\", "/").lstrip("./")
    return p


def _matches_any(path: str, prefixes: list[str]) -> str | None:
    """Return the first matching prefix, or None."""
    norm = _normalise(path)
    for prefix in prefixes:
        pnorm = _normalise(prefix)
        if norm == pnorm or norm.startswith(pnorm):
            return prefix
    return None


def check_path(path: str, tier: int) -> tuple[bool, str]:
    """Return (allowed, reason).

    allowed=True  → write is permitted at this tier
    allowed=False → write is blocked; reason explains why
    """
    if tier not in TIER_TO_AUTHORITY:
        return False, f"Unknown tier {tier}"

    frozen = _matches_any(path, ALWAYS_FROZEN)
    if frozen:
        return False, f"ALWAYS_FROZEN: matches '{frozen}'"

    tier_blocks = _BLOCKED_BY_TIER.get(tier, [])
    blocked = _matches_any(path, tier_blocks)
    if blocked:
        authority = TIER_TO_AUTHORITY[tier]
        return False, f"TIER_{tier}_BLOCKED ({authority}): matches '{blocked}'"

    return True, f"ALLOWED at tier {tier} ({TIER_TO_AUTHORITY[tier]})"


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

_SELF_TEST_CASES: list[tuple[str, int, bool, str]] = [
    # (path, tier, expected_allowed, description)
    ("ranker/weights.json", 0, False, "ranker always frozen"),
    ("ranker/weights.json", 4, False, "ranker always frozen even at tier 4"),
    ("selector/model.pkl", 0, False, "selector always frozen"),
    ("data/snapshots/2026-06-26/screen.pkl", 0, False, "snapshots always frozen"),
    ("data/snapshots_pit/2026-06-26/rankings.csv", 3, False, "snapshots_pit always frozen"),
    ("portfolio/positions.csv", 2, False, "portfolio always frozen"),
    (".env", 0, False, ".env always frozen"),
    (".github/workflows/ci.yml", 0, False, "github workflows always frozen"),
    ("artifacts/generated/output.json", 0, False, "artifacts/generated always frozen"),
    ("production_data/raw.csv", 1, False, "production_data always frozen"),
    ("artifacts/my_agent/output.json", 0, True, "own artifacts tier 0"),
    ("artifacts/shared/report.json", 2, True, "shared artifacts tier 2"),
    ("docs/hermes_skills/screener-ops.md", 2, True, "hermes_skills write tier 2"),
    ("data/aact/snapshots/2026.json", 0, False, "aact blocked at tier 0"),
    ("data/aact/snapshots/2026.json", 3, True, "aact allowed at tier 3"),
    ("specs/spec_099.md", 3, False, "specs blocked at tier 3"),
    ("specs/spec_099.md", 4, True, "specs allowed at tier 4"),
    ("CLAUDE.md", 3, False, "CLAUDE.md blocked at tier 3"),
    ("CLAUDE.md", 4, True, "CLAUDE.md allowed at tier 4"),
    ("logs/my_agent_2026-06-26.log", 0, True, "logs allowed at tier 0"),
    ("artifacts/ops/held_spec_ledger/2026-06-26.json", 1, True, "held_spec allowed at tier 1"),
    ("output/catalyst_ev/events.json", 2, False, "catalyst_ev blocked at tier 2"),
    ("output/catalyst_ev/events.json", 3, True, "catalyst_ev allowed at tier 3"),
]


def run_self_test() -> int:
    failures = 0
    for path, tier, expected, description in _SELF_TEST_CASES:
        allowed, reason = check_path(path, tier)
        ok = allowed == expected
        sym = "PASS" if ok else "FAIL"
        print(f"  {sym}  [{description}]")
        if not ok:
            print(f"       path={path!r} tier={tier}")
            print(f"       expected={'ALLOWED' if expected else 'BLOCKED'}, got: {reason}")
            failures += 1
    print(f"\n{len(_SELF_TEST_CASES) - failures}/{len(_SELF_TEST_CASES)} tests passed")
    return 0 if failures == 0 else 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether a path write is allowed for a given permission tier.")
    parser.add_argument("--check", metavar="PATH", help="Path to check")
    parser.add_argument("--tier", type=int, choices=list(TIER_TO_AUTHORITY), help="Tier (0-4)")
    parser.add_argument(
        "--authority",
        choices=list(AUTHORITY_TO_TIER),
        help="authority_level name (alternative to --tier)",
    )
    parser.add_argument("--self-test", action="store_true", help="Run self-tests")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.check:
        parser.error("--check PATH is required (or --self-test)")

    tier = args.tier
    if tier is None and args.authority:
        tier = AUTHORITY_TO_TIER.get(args.authority)
        if tier is None:
            print(f"ERROR: unknown authority '{args.authority}'", file=sys.stderr)
            return 2

    if tier is None:
        parser.error("Either --tier or --authority is required with --check")

    allowed, reason = check_path(args.check, tier)
    print(reason)
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
