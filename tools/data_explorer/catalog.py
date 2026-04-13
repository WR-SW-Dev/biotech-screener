"""Artifact catalog — discover available artifacts in a snapshot directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

# Known artifact patterns and their categories
ARTIFACT_PATTERNS: Dict[str, Dict[str, str]] = {
    # Rankings
    "rankings.csv": {"category": "rankings", "description": "Main ranked universe"},
    # EES / TrapOps
    "expectation_error_overlay.json": {"category": "ees", "description": "EES v2 scores"},
    "ees_gate_diagnostics.json": {"category": "ees", "description": "Quality/trap gate diagnostics"},
    "ees_gate_performance.json": {"category": "ees", "description": "Gate performance tracker"},
    # Execution
    "execution_stress_base.json": {"category": "execution", "description": "Base execution stress"},
    "execution_stress_stress.json": {"category": "execution", "description": "Stress execution stress"},
    # Expression overlay
    "expression_overlay_summary.json": {"category": "expression", "description": "Expression overlay summary"},
    "expression_recommendations.json": {"category": "expression", "description": "Tradeable recommendations"},
    # Options
    "options_diagnostics.json": {"category": "options", "description": "Options chain diagnostics"},
    # Catalyst
    "catalyst_risk_matrix.json": {"category": "catalyst", "description": "Catalyst risk matrix"},
    "catalyst_shadow_metrics.json": {"category": "catalyst", "description": "Shadow comparison metrics"},
    "catalyst_source_mix.json": {"category": "catalyst", "description": "Catalyst source distribution"},
    # Coverage / QA
    "coverage_quality.json": {"category": "coverage", "description": "Coverage quality metrics"},
    "eligibility_summary.json": {"category": "coverage", "description": "Eligibility gate summary"},
    "cache_health.json": {"category": "health", "description": "Cache freshness health"},
    # Integrity
    "rankings.csv.sha256": {"category": "integrity", "description": "Rankings checksum"},
    "snapshot_manifest.json": {"category": "integrity", "description": "Snapshot manifest"},
    # Shadow
    "shadow_comparison.json": {"category": "shadow", "description": "Shadow model comparison"},
}


def discover_artifacts(
    snap_dir: Union[str, Path],
) -> Dict[str, Dict[str, Any]]:
    """Discover available artifacts in a snapshot directory.

    Returns dict keyed by filename with category, description, path, size.
    """
    snap_dir = Path(snap_dir)
    if not snap_dir.is_dir():
        return {}

    found: Dict[str, Dict[str, Any]] = {}
    for path in sorted(snap_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        info = ARTIFACT_PATTERNS.get(name, {})
        found[name] = {
            "category": info.get("category", "other"),
            "description": info.get("description", ""),
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "extension": path.suffix,
        }

    return found


def catalog_summary(
    snap_dir: Union[str, Path],
) -> Dict[str, Any]:
    """High-level catalog summary for a snapshot directory."""
    artifacts = discover_artifacts(snap_dir)
    snap_dir = Path(snap_dir)

    by_category: Dict[str, List[str]] = {}
    for name, info in artifacts.items():
        cat = info["category"]
        by_category.setdefault(cat, []).append(name)

    return {
        "snapshot_dir": str(snap_dir),
        "snapshot_date": snap_dir.name[:10] if len(snap_dir.name) >= 10 else snap_dir.name,
        "n_artifacts": len(artifacts),
        "by_category": {k: sorted(v) for k, v in sorted(by_category.items())},
        "has_rankings": "rankings.csv" in artifacts,
        "has_ees": any(a["category"] == "ees" for a in artifacts.values()),
        "has_expression": any(a["category"] == "expression" for a in artifacts.values()),
        "has_options": any(a["category"] == "options" for a in artifacts.values()),
        "artifacts": artifacts,
    }


def list_snapshot_dates(
    snapshots_dir: Union[str, Path],
) -> List[str]:
    """List available snapshot dates (directory names), most recent first."""
    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.is_dir():
        return []
    dirs = [
        d.name
        for d in sorted(snapshots_dir.iterdir(), reverse=True)
        if d.is_dir() and len(d.name) >= 10 and d.name[:4].isdigit()
    ]
    return dirs
