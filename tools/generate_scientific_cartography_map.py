#!/usr/bin/env python3
"""Scientific Cartography Map UX v0.2b — static disease-map generator.

Reads Sci-Cart diagnostic artifacts only. Produces self-contained HTML,
SVG, JSON, and README for a single disease view. No server, no CDN, no
production scoring sources.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VERSION = "v0.2b"

_FORBIDDEN_SOURCES = [
    "rankings.csv",
    "portfolio_positions.csv",
    "screen_output.json",
    "selector",
    "sizing",
    "final_score",
]

_STAGE_ORDER = [
    "preclinical",
    "phase1",
    "phase1/2",
    "phase2",
    "phase2b",
    "phase3",
    "filed",
    "approved",
]
_UNKNOWN_STAGE_LABEL = "unknown"

_MODALITY_COLORS = {
    "small molecule": "#4a90d9",
    "monoclonal antibody": "#e67e22",
    "cell therapy": "#27ae60",
    "gene therapy": "#9b59b6",
    "rna therapy": "#e74c3c",
    "protein/enzyme therapy": "#16a085",
}
_DEFAULT_COLOR = "#95a5a6"

_MAX_NODES_PER_CELL = 5
_CELL_W = 152
_CELL_H_PER_NODE = 22
_CELL_PADDING = 8
_LANE_LABEL_W = 210
_COL_HEADER_H = 54


# ---------------------------------------------------------------------------
# Governance guard
# ---------------------------------------------------------------------------


class ForbiddenSourceError(Exception):
    pass


def _check_forbidden(path: Path) -> None:
    path_str = str(path).lower()
    for pattern in _FORBIDDEN_SOURCES:
        if pattern.lower() in path_str:
            raise ForbiddenSourceError(
                f"Forbidden source detected in input path: {path} "
                f"(matched pattern: {pattern!r}). "
                "Map generator must not read production scoring files."
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_programs(artifact_dir: Path, disease_query: str) -> list[dict]:
    """Load and filter programs matching disease_query from program_records.jsonl."""
    programs_path = artifact_dir / "program_records.jsonl"
    _check_forbidden(programs_path)
    if not programs_path.exists():
        raise FileNotFoundError(f"program_records.jsonl not found in {artifact_dir}")

    query_lower = disease_query.lower().strip()
    matched: list[dict] = []
    with open(programs_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            dn = (p.get("disease_name") or "").lower()
            di = (p.get("disease_id") or "").lower()
            if query_lower in dn or query_lower == di:
                matched.append(p)
    return matched


def _load_manifest(artifact_dir: Path) -> dict:
    manifest_path = artifact_dir / "artifact_manifest.json"
    _check_forbidden(manifest_path)
    if not manifest_path.exists():
        return {}
    with open(manifest_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Layout engine
# ---------------------------------------------------------------------------


def _node_color(program: dict) -> str:
    modality = (program.get("modality") or "").lower()
    return _MODALITY_COLORS.get(modality, _DEFAULT_COLOR)


def _node_opacity(program: dict) -> float:
    conf = program.get("confidence", 0.0) or 0.0
    return round(0.30 + 0.70 * min(1.0, max(0.0, conf)), 3)


def _stage_key(program: dict) -> str:
    stage = program.get("clinical_stage")
    if stage in _STAGE_ORDER:
        return stage
    return _UNKNOWN_STAGE_LABEL


def _mech_key(program: dict) -> str:
    m = program.get("mechanism_class")
    return m if m else "Unknown Mechanism"


def build_map_data(programs: list[dict], disease_query: str, manifest: dict) -> dict:
    """Build structured lane/column/node data from filtered programs."""
    # Identify active stages (only show columns with at least 1 program)
    stage_counts: Counter = Counter(_stage_key(p) for p in programs)
    active_stages = [s for s in _STAGE_ORDER if stage_counts.get(s, 0) > 0]
    if stage_counts.get(_UNKNOWN_STAGE_LABEL, 0) > 0:
        active_stages.append(_UNKNOWN_STAGE_LABEL)

    # Build lane list sorted by total programs DESC; Unknown Mechanism always last
    mech_totals: Counter = Counter(_mech_key(p) for p in programs)
    known_mechs = sorted(
        [m for m in mech_totals if m != "Unknown Mechanism"],
        key=lambda m: mech_totals[m],
        reverse=True,
    )
    lanes = known_mechs + (["Unknown Mechanism"] if mech_totals.get("Unknown Mechanism") else [])

    # Build cell map: lane -> stage -> [programs]
    cells: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for p in programs:
        cells[_mech_key(p)][_stage_key(p)].append(p)

    # Sort programs within each cell by confidence DESC
    for lane_cells in cells.values():
        for stage_programs in lane_cells.values():
            stage_programs.sort(key=lambda p: p.get("confidence", 0) or 0, reverse=True)

    # Coverage stats
    mech_known = sum(1 for p in programs if p.get("mechanism_class"))
    ticker_known = sum(1 for p in programs if p.get("ticker"))
    stage_known = sum(1 for p in programs if p.get("clinical_stage"))
    ta_vals = [p.get("therapeutic_area") for p in programs if p.get("therapeutic_area")]
    ta_val = ta_vals[0] if ta_vals else None
    stage_dist = dict(Counter(_stage_key(p) for p in programs).most_common())
    mondo_ids = list({p.get("mondo_id") for p in programs if p.get("mondo_id")})

    warnings = []
    mech_pct = 100 * mech_known / len(programs) if programs else 0
    if mech_pct < 20:
        warnings.append(
            f"Mechanism coverage is sparse ({mech_pct:.1f}%). " "Unknown mechanism lane is dominant and expected."
        )
    if len(mondo_ids) > 1:
        warnings.append(f"Disease view spans {len(mondo_ids)} MONDO IDs — " "includes disease label variants.")

    return {
        "metadata": {
            "disease_name": disease_query,
            "disease_slug": disease_query.lower().replace(" ", "-").replace("/", "-"),
            "mondo_ids": mondo_ids,
            "therapeutic_area": ta_val,
            "as_of_date": manifest.get("as_of_date", "unknown"),
            "artifact_source": "scientific_cartography_diagnostic_artifacts",
            "generator_version": _VERSION,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "governance": {
                "read_only_diagnostic": True,
                "production_wiring": False,
                "alpha_promotion": False,
                "disclaimer": (
                    "NOT AN INVESTMENT RECOMMENDATION. "
                    "Diagnostic-only. Not derived from ranking, "
                    "selection, or scoring models."
                ),
            },
        },
        "summary": {
            "total_programs": len(programs),
            "stage_coverage_pct": round(100 * stage_known / len(programs), 1) if programs else 0,
            "mechanism_coverage_pct": round(mech_pct, 1),
            "ticker_coverage_pct": round(100 * ticker_known / len(programs), 1) if programs else 0,
            "stage_distribution": stage_dist,
            "mechanism_lane_count": len(lanes),
            "stage_column_count": len(active_stages),
        },
        "warnings": warnings,
        "lanes": lanes,
        "columns": active_stages,
        "cells": {
            lane: {
                stage: [
                    {
                        "asset_name": p.get("asset_name", ""),
                        "company_name": p.get("company_name") or "",
                        "ticker": p.get("ticker") or "",
                        "disease_name": p.get("disease_name", ""),
                        "mondo_id": p.get("mondo_id") or "",
                        "therapeutic_area": p.get("therapeutic_area") or "",
                        "mechanism_class": p.get("mechanism_class") or "",
                        "target": p.get("target") or "",
                        "modality": p.get("modality") or "",
                        "clinical_stage": p.get("clinical_stage") or "",
                        "confidence": round(p.get("confidence", 0) or 0, 3),
                        "source_refs_count": len(p.get("source_refs") or []),
                        "program_id": p.get("program_id", ""),
                    }
                    for p in cells[lane][stage]
                ]
                for stage in active_stages
            }
            for lane in lanes
        },
    }


# ---------------------------------------------------------------------------
# SVG renderer
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = 22) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def render_svg(map_data: dict) -> str:
    lanes = map_data["lanes"]
    columns = map_data["columns"]
    cells = map_data["cells"]

    # Compute lane heights
    lane_heights = {}
    for lane in lanes:
        max_nodes_in_lane = max(
            (len(cells.get(lane, {}).get(col, [])) for col in columns),
            default=0,
        )
        visible = min(max_nodes_in_lane, _MAX_NODES_PER_CELL) + (1 if max_nodes_in_lane > _MAX_NODES_PER_CELL else 0)
        lane_heights[lane] = max(visible * _CELL_H_PER_NODE + _CELL_PADDING * 2, 44)

    total_w = _LANE_LABEL_W + len(columns) * _CELL_W + 20
    total_h = _COL_HEADER_H + sum(lane_heights.values()) + 20

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_w}" height="{total_h}" '
        f'style="font-family:Arial,sans-serif;font-size:11px;">'
    ]

    # Background
    lines.append(f'<rect width="{total_w}" height="{total_h}" fill="#fafafa" stroke="#ddd" stroke-width="1"/>')

    # Column headers
    for ci, col in enumerate(columns):
        x = _LANE_LABEL_W + ci * _CELL_W
        label = col.upper() if col != _UNKNOWN_STAGE_LABEL else "UNKNOWN STAGE"
        lines.append(
            f'<rect x="{x}" y="0" width="{_CELL_W}" height="{_COL_HEADER_H}" '
            f'fill="#2c3e50" stroke="#fff" stroke-width="1"/>'
        )
        lines.append(
            f'<text x="{x + _CELL_W//2}" y="{_COL_HEADER_H//2 + 5}" '
            f'text-anchor="middle" fill="white" font-weight="bold" font-size="11">'
            f"{label}</text>"
        )

    # Lane rows
    y_offset = _COL_HEADER_H
    for lane in lanes:
        lh = lane_heights[lane]
        is_unknown_lane = lane == "Unknown Mechanism"

        # Lane label background
        bg_fill = "#ecf0f1" if not is_unknown_lane else "#ffeeba"
        lines.append(
            f'<rect x="0" y="{y_offset}" width="{_LANE_LABEL_W}" height="{lh}" '
            f'fill="{bg_fill}" stroke="#ccc" stroke-width="0.5"/>'
        )
        lane_display = _truncate(lane, 28)
        lines.append(
            f'<text x="8" y="{y_offset + lh//2 + 4}" fill="#2c3e50" '
            f'font-weight="{"bold" if is_unknown_lane else "normal"}" font-size="11">'
            f"{_xml_escape(lane_display)}</text>"
        )

        # Cells
        for ci, col in enumerate(columns):
            cx = _LANE_LABEL_W + ci * _CELL_W
            node_list = cells.get(lane, {}).get(col, [])
            cell_bg = "#fff" if not is_unknown_lane else "#fffdf0"
            lines.append(
                f'<rect x="{cx}" y="{y_offset}" width="{_CELL_W}" height="{lh}" '
                f'fill="{cell_bg}" stroke="#ddd" stroke-width="0.5"/>'
            )

            # Draw nodes
            visible_nodes = node_list[:_MAX_NODES_PER_CELL]
            for ni, node in enumerate(visible_nodes):
                ny = y_offset + _CELL_PADDING + ni * _CELL_H_PER_NODE
                color = _node_color(node)
                opacity = _node_opacity(node)
                has_ticker = bool(node.get("ticker"))
                stroke = "#333" if has_ticker else "#aaa"
                stroke_w = "1.5" if has_ticker else "0.5"
                label_text = _truncate(node.get("asset_name") or "—", 20)
                lines.append(
                    f'<rect x="{cx + 4}" y="{ny}" width="{_CELL_W - 8}" height="{_CELL_H_PER_NODE - 2}" '
                    f'fill="{color}" opacity="{opacity}" '
                    f'stroke="{stroke}" stroke-width="{stroke_w}" rx="2"/>'
                )
                lines.append(
                    f'<text x="{cx + 7}" y="{ny + 13}" fill="#1a1a1a" font-size="9">'
                    f"{_xml_escape(label_text)}</text>"
                )

            overflow = len(node_list) - _MAX_NODES_PER_CELL
            if overflow > 0:
                ny = y_offset + _CELL_PADDING + len(visible_nodes) * _CELL_H_PER_NODE
                lines.append(
                    f'<text x="{cx + _CELL_W//2}" y="{ny + 11}" '
                    f'text-anchor="middle" fill="#888" font-size="9" font-style="italic">'
                    f"+{overflow} more</text>"
                )

        y_offset += lh

    lines.append("</svg>")
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------


def render_html(map_data: dict, svg_content: str) -> str:
    meta = map_data["metadata"]
    summ = map_data["summary"]
    warnings = map_data["warnings"]
    disease = meta["disease_name"]
    ta = meta.get("therapeutic_area") or "—"
    as_of = meta.get("as_of_date", "unknown")
    generated = meta.get("generated_at_utc", "unknown")
    n_programs = summ["total_programs"]
    stage_pct = summ["stage_coverage_pct"]
    mech_pct = summ["mechanism_coverage_pct"]
    ticker_pct = summ["ticker_coverage_pct"]
    stage_dist = summ.get("stage_distribution", {})

    stage_dist_html = " | ".join(
        f"<b>{s}</b>: {c}" for s, c in sorted(stage_dist.items(), key=lambda x: x[1], reverse=True)
    )

    warning_html = ""
    if warnings:
        warning_html = '<div class="warning-banner">' + "".join(f"<div>⚠ {w}</div>" for w in warnings) + "</div>"

    mondo_html = ", ".join(meta.get("mondo_ids") or []) or "—"

    legend_swatches = "".join(
        f'<span class="legend-item"><span class="legend-swatch" style="background:{color}"></span>{name}</span>'
        for name, color in _MODALITY_COLORS.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sci-Cart Map — {disease}</title>
<style>
body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; background: #f5f5f5; color: #222; }}
.governance-banner {{
  background: #2c3e50; color: #ecf0f1; padding: 10px 20px;
  font-size: 12px; letter-spacing: 0.03em;
}}
.governance-banner b {{ color: #e74c3c; }}
.header {{ background: #fff; border-bottom: 2px solid #2c3e50; padding: 16px 20px; }}
.header h1 {{ margin: 0 0 6px; font-size: 22px; color: #2c3e50; }}
.header .meta {{ font-size: 12px; color: #555; }}
.header .meta span {{ margin-right: 16px; }}
.warning-banner {{
  background: #fff3cd; border-left: 4px solid #f0ad4e;
  padding: 8px 16px; margin: 12px 20px; font-size: 12px; color: #856404;
}}
.stats-row {{
  display: flex; gap: 16px; padding: 12px 20px;
  background: #fff; border-bottom: 1px solid #e0e0e0;
  font-size: 12px;
}}
.stat {{ background: #f0f4f8; border-radius: 4px; padding: 6px 12px; }}
.stat b {{ color: #2c3e50; }}
.map-container {{ padding: 20px; overflow-x: auto; }}
.legend {{ padding: 12px 20px; background: #fff; border-top: 1px solid #e0e0e0;
  font-size: 11px; color: #555; }}
.legend-item {{ display: inline-block; margin-right: 14px; }}
.legend-swatch {{ display: inline-block; width: 12px; height: 12px;
  border-radius: 2px; vertical-align: middle; margin-right: 4px; }}
.footer {{ padding: 10px 20px; font-size: 11px; color: #888; border-top: 1px solid #e0e0e0; }}
</style>
</head>
<body>
<div class="governance-banner">
  <b>DIAGNOSTIC ONLY — NOT AN INVESTMENT RECOMMENDATION.</b>
  Scientific Cartography {_VERSION}. Read-only. No ranking, selection, or scoring.
  Frozen production model. No live data.
</div>

<div class="header">
  <h1>Disease Map — {disease}</h1>
  <div class="meta">
    <span><b>Therapeutic Area:</b> {ta}</span>
    <span><b>MONDO IDs:</b> {mondo_html}</span>
    <span><b>As of:</b> {as_of}</span>
    <span><b>Generated:</b> {generated}</span>
  </div>
</div>

{warning_html}

<div class="stats-row">
  <div class="stat"><b>Programs:</b> {n_programs:,}</div>
  <div class="stat"><b>Stage coverage:</b> {stage_pct}%</div>
  <div class="stat"><b>Mechanism coverage:</b> {mech_pct}%</div>
  <div class="stat"><b>Ticker linkage:</b> {ticker_pct}%</div>
  <div class="stat" style="flex:1"><b>Stage distribution:</b> {stage_dist_html}</div>
</div>

<div class="map-container">
{svg_content}
</div>

<div class="legend">
  <b>Modality colors:</b>
  {legend_swatches}
  <span class="legend-item"><span class="legend-swatch" style="background:{_DEFAULT_COLOR}"></span>unknown</span>
  &nbsp;&nbsp;
  <b>Opacity:</b> higher = more confident
  &nbsp;
  <b>Border:</b> solid thick = has ticker; thin = no ticker linkage
</div>

<div class="footer">
  Scientific Cartography {_VERSION} &nbsp;|&nbsp;
  Source: diagnostic artifacts only &nbsp;|&nbsp;
  {generated}
  &nbsp;|&nbsp;
  DIAGNOSTIC ONLY — NOT AN INVESTMENT RECOMMENDATION
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# README renderer
# ---------------------------------------------------------------------------


def render_readme(map_data: dict) -> str:
    meta = map_data["metadata"]
    summ = map_data["summary"]
    disease = meta["disease_name"]
    as_of = meta["as_of_date"]
    n = summ["total_programs"]
    stage_pct = summ["stage_coverage_pct"]
    mech_pct = summ["mechanism_coverage_pct"]

    return f"""# Scientific Cartography Map — {disease}

**Version:** {_VERSION}
**As of:** {as_of}
**Programs:** {n:,}
**Stage coverage:** {stage_pct}%
**Mechanism coverage:** {mech_pct}% (sparse — known limitation, see R6 design memo)

## Files

| File | Description |
|------|-------------|
| `index.html` | Self-contained HTML map (open with `file://`) |
| `map.svg` | Standalone SVG (embeddable) |
| `map.json` | Structured lane/column/node data |
| `README.md` | This file |

## Governance

**DIAGNOSTIC ONLY. NOT AN INVESTMENT RECOMMENDATION.**
Generated from Sci-Cart diagnostic artifacts only.
Does not read rankings, portfolio positions, scores, or screening outputs.
Production model freeze remains ACTIVE.

## Limitations

- Mechanism coverage is sparse (~{mech_pct}% resolved). Unknown mechanism lane
  is dominant and expected; do not interpret as competitive insight.
- Ticker linkage requires snapshot with `rankings.csv` — not used here by design.
- Stage distribution: {summ.get("stage_distribution", {})}
"""


# ---------------------------------------------------------------------------
# Top-level generator
# ---------------------------------------------------------------------------


def generate_map(
    input_dir: Path,
    disease: str,
    output_dir: Path,
    quiet: bool = False,
) -> dict:
    """Generate a static disease map from Sci-Cart artifacts.

    Returns a summary dict with counts and file paths.
    """
    _check_forbidden(input_dir)

    if not quiet:
        print(f"Loading programs for disease: {disease!r}", file=sys.stderr)

    programs = _load_programs(input_dir, disease)

    if not quiet:
        print(f"  Found {len(programs)} matching programs", file=sys.stderr)

    if not programs:
        raise ValueError(f"No programs found for disease query: {disease!r}")

    manifest = _load_manifest(input_dir)
    map_data = build_map_data(programs, disease, manifest)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate outputs
    map_json_str = json.dumps(map_data, indent=2, ensure_ascii=False)
    svg_content = render_svg(map_data)
    html_content = render_html(map_data, svg_content)
    readme_content = render_readme(map_data)

    (output_dir / "map.json").write_text(map_json_str, encoding="utf-8")
    (output_dir / "map.svg").write_text(svg_content, encoding="utf-8")
    (output_dir / "index.html").write_text(html_content, encoding="utf-8")
    (output_dir / "README.md").write_text(readme_content, encoding="utf-8")

    if not quiet:
        for fname in ["map.json", "map.svg", "index.html", "README.md"]:
            size = (output_dir / fname).stat().st_size
            print(f"  Wrote {fname} ({size:,} bytes)", file=sys.stderr)

    return {
        "disease": disease,
        "programs": len(programs),
        "lanes": len(map_data["lanes"]),
        "columns": len(map_data["columns"]),
        "output_dir": str(output_dir),
        "warnings": map_data["warnings"],
        "summary": map_data["summary"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Scientific Cartography Map UX {_VERSION} — static disease-map generator",
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Path to Sci-Cart diagnostic artifact directory",
    )
    parser.add_argument(
        "--disease",
        required=True,
        help="Disease name or MONDO ID to generate map for",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for generated map files",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress progress output",
    )

    args = parser.parse_args()

    try:
        result = generate_map(
            input_dir=Path(args.input_dir),
            disease=args.disease,
            output_dir=Path(args.output_dir),
            quiet=args.quiet,
        )
        if not args.quiet:
            print(f"\nMap generated: {result['output_dir']}", file=sys.stderr)
            print(f"  Programs: {result['programs']}", file=sys.stderr)
            print(f"  Lanes:    {result['lanes']}", file=sys.stderr)
            print(f"  Columns:  {result['columns']}", file=sys.stderr)
            for w in result["warnings"]:
                print(f"  WARNING: {w}", file=sys.stderr)
        return 0
    except ForbiddenSourceError as e:
        print(f"ERROR (governance): {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
