#!/usr/bin/env python3
"""Data Explorer Agent — CLI for analysis and reporting.

Usage:
    python -m tools.data_explorer summary data/snapshots/2026-04-13
    python -m tools.data_explorer compare data/snapshots/2026-04-12 data/snapshots/2026-04-13
    python -m tools.data_explorer qa data/snapshots/2026-04-13
    python -m tools.data_explorer catalog data/snapshots/2026-04-13
    python -m tools.data_explorer field coinvest_score_z data/snapshots/2026-04-13
    python -m tools.data_explorer field --field coinvest_score_z --path data/snapshots/2026-04-13
    python -m tools.data_explorer top-n data/snapshots/2026-04-13 -n 30
    python -m tools.data_explorer daily data/snapshots/2026-04-13
    python -m tools.data_explorer shell

All commands accept:
    --format text|json    Output format (default: text)
    --output PATH         Write output to file instead of stdout
    --strict-exit         Propagate QA exit codes (0/1/2) instead of
                          treating warnings as success

Read-only. Does not modify production data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from tools.data_explorer.formatters import format_response
from tools.data_explorer.service import run_catalog, run_compare, run_daily, run_field, run_qa, run_summary, run_top_n

logger = logging.getLogger("data_explorer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _output_dir(label: str = "") -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = f"{label}_{ts}" if label else ts
    out = Path("reports/data_explorer") / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def _emit(text: str, output_path: str | None) -> None:
    """Print to stdout or write to file."""
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text + "\n")
    else:
        print(text)


def _qa_process_exit(resp: dict, strict: bool) -> int:
    """Derive process exit code from a QA exit_code.

    Default: 0 for clean or warnings, 2 for errors.
    Strict:  0/1/2 propagated directly.
    """
    qa_code = resp.get("data", {}).get("exit_code", 0)
    if strict:
        return qa_code
    return 2 if qa_code >= 2 else 0


def _daily_process_exit(resp: dict, strict: bool) -> int:
    """Derive process exit code from daily's embedded QA exit_code."""
    qa_code = resp.get("data", {}).get("qa", {}).get("exit_code", 0)
    if strict:
        return qa_code
    return 2 if qa_code >= 2 else 0


def _wants_artifacts(args: argparse.Namespace) -> bool:
    """True when we should generate report/chart artifacts."""
    return args.format == "text" and not args.output


def _print_artifact_info(resp: dict) -> None:
    """Print paths of generated artifacts to stderr."""
    data = resp.get("data", {})
    if "report_path" in data:
        print(f"\nReport saved: {data['report_path']}")
    if "manifest_path" in data:
        print(f"Manifest saved: {data['manifest_path']}")
    chart_paths = data.get("chart_paths", [])
    if chart_paths:
        print(f"Charts: {len(chart_paths)}")


# ---------------------------------------------------------------------------
# Command handlers (thin — delegate to service, format, emit)
# ---------------------------------------------------------------------------


def cmd_summary(args: argparse.Namespace) -> int:
    out_dir = _output_dir("summary") if _wants_artifacts(args) else None
    resp = run_summary(args.path, verbose=args.verbose, out_dir=out_dir)
    _emit(format_response(resp, args.format), args.output)
    if out_dir:
        _print_artifact_info(resp)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    out_dir = _output_dir("compare") if _wants_artifacts(args) else None
    resp = run_compare(args.path_a, args.path_b, n=args.n, verbose=args.verbose, out_dir=out_dir)
    _emit(format_response(resp, args.format), args.output)
    if out_dir:
        _print_artifact_info(resp)
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    out_dir = _output_dir("qa") if _wants_artifacts(args) else None
    resp = run_qa(args.path, verbose=args.verbose, out_dir=out_dir)
    _emit(format_response(resp, args.format), args.output)
    if out_dir:
        _print_artifact_info(resp)
    return _qa_process_exit(resp, args.strict_exit)


def cmd_catalog(args: argparse.Namespace) -> int:
    resp = run_catalog(args.path)
    _emit(format_response(resp, args.format), args.output)
    return 0


def cmd_field(args: argparse.Namespace) -> int:
    field, path = _resolve_field_args(args)
    resp = run_field(path, field)
    _emit(format_response(resp, args.format), args.output)
    return 0 if resp["ok"] else 1


def cmd_top_n(args: argparse.Namespace) -> int:
    resp = run_top_n(args.path, n=args.n)
    _emit(format_response(resp, args.format), args.output)
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    out_dir = _output_dir("daily") if _wants_artifacts(args) else None
    resp = run_daily(args.path, verbose=args.verbose, out_dir=out_dir)
    _emit(format_response(resp, args.format), args.output)
    if out_dir:
        _print_artifact_info(resp)
    return _daily_process_exit(resp, args.strict_exit)


# ---------------------------------------------------------------------------
# Field argument resolution — accept both positional orders and named flags
# ---------------------------------------------------------------------------


def _resolve_field_args(args: argparse.Namespace) -> tuple:
    """Resolve field name and path from flexible argument parsing.

    Accepts:
        field <field_name> <path>        (original order)
        field <path> <field_name>         (swapped — auto-detected)
        field --field <name> --path <p>   (named flags)
    """
    field_name = getattr(args, "field_name", None)
    path = getattr(args, "path_pos", None)

    # Named flags take precedence
    if args.field_flag and args.path_flag:
        return args.field_flag, args.path_flag

    # Positional: check if user swapped the order (path first, field second)
    if field_name and path:
        if Path(field_name).exists() and not Path(path).exists():
            return path, field_name
        return field_name, path

    # Partial: only one positional given
    if field_name and not path:
        if Path(field_name).exists():
            print("Error: missing field name. Usage: field <column_name> <path>")
            print("  or: field --field <column_name> --path <path>")
            sys.exit(1)
        print(f"Error: missing path. Usage: field {field_name} <path>")
        sys.exit(1)

    print("Error: field requires a column name and path.")
    print("  Usage: field <column_name> <path>")
    print("  or:    field --field <column_name> --path <path>")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Argparse setup
# ---------------------------------------------------------------------------


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add --format, --output, --strict-exit to a subparser."""
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "--strict-exit",
        action="store_true",
        default=False,
        help="Propagate QA exit codes: 0=clean, 1=warnings, 2=errors",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Data Explorer Agent — analysis and reporting for biotech screener",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")

    # Summary
    p_summary = sub.add_parser("summary", help="Snapshot summary")
    p_summary.add_argument("path", help="Path to rankings.csv or snapshot directory")
    _add_common_args(p_summary)

    # Compare
    p_compare = sub.add_parser("compare", help="Compare two snapshots")
    p_compare.add_argument("path_a", help="Path A (earlier)")
    p_compare.add_argument("path_b", help="Path B (later)")
    p_compare.add_argument("-n", type=int, default=30, help="Top-N for overlap (default: 30)")
    _add_common_args(p_compare)

    # QA
    p_qa = sub.add_parser("qa", help="Run QA checks")
    p_qa.add_argument("path", help="Path to rankings.csv or snapshot directory")
    _add_common_args(p_qa)

    # Catalog
    p_catalog = sub.add_parser("catalog", help="List available artifacts")
    p_catalog.add_argument("path", help="Path to snapshot directory")
    _add_common_args(p_catalog)

    # Field — supports both positional and named-flag forms
    p_field = sub.add_parser(
        "field",
        help="Show stats for a specific field",
        description=(
            "Show stats for a specific field.\n\n"
            "Usage:\n"
            "  field coinvest_score_z data/snapshots/2026-04-13\n"
            "  field --field coinvest_score_z --path data/snapshots/2026-04-13\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_field.add_argument("field_name", nargs="?", default=None, help="Column name (positional)")
    p_field.add_argument("path_pos", nargs="?", default=None, help="Path (positional)")
    p_field.add_argument("--field", dest="field_flag", default=None, help="Column name (named)")
    p_field.add_argument("--path", dest="path_flag", default=None, help="Path (named)")
    _add_common_args(p_field)

    # Top-N
    p_topn = sub.add_parser("top-n", help="Show top-N ranked names")
    p_topn.add_argument("path", help="Path to rankings.csv or snapshot directory")
    p_topn.add_argument("-n", type=int, default=30, help="Number of names (default: 30)")
    _add_common_args(p_topn)

    # Daily report
    p_daily = sub.add_parser("daily", help="Generate full daily report")
    p_daily.add_argument("path", help="Path to snapshot directory")
    _add_common_args(p_daily)

    # TUI shell
    sub.add_parser("shell", help="Launch interactive TUI shell")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "shell":
        from tools.data_explorer.tui_app import run_shell

        return run_shell()

    commands = {
        "summary": cmd_summary,
        "compare": cmd_compare,
        "qa": cmd_qa,
        "catalog": cmd_catalog,
        "field": cmd_field,
        "top-n": cmd_top_n,
        "daily": cmd_daily,
    }

    fn = commands.get(args.command)
    if fn:
        return fn(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
