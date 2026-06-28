#!/usr/bin/env python3
"""Scientific Cartography Map UX v0.3 — poster-style disease-map generator.

Reads Sci-Cart diagnostic artifacts only. Produces self-contained HTML,
SVG, JSON, and README for a single disease view. No server, no CDN, no
production scoring sources.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VERSION = "v0.3"

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

# D3: Non-drug/behavioral intervention filter
# Exact lowercase asset names that are clearly not pharmaceutical programs.
_NON_DRUG_EXACT = frozenset(
    {
        "no treatment",
        "no treatment given",
        "no treatment (control)",
        "no intervention",
        "placebo",
        "exercise",
        "diet",
        "aerobic exercise",
        "aerobic training",
        "usual care",
        "observation",
        "watchful waiting",
        "lifestyle therapy",
        "lifestyle intervention",
        "dietary advice",
        "physical activity",
        "standard diet",
        # Diagnostics / instruments (v0.2d)
        "ogtt",
        "oral glucose tolerance test",
        "mems cap",
        # Dosing-regimen-only names (v0.2d)
        "basal bolus",
        "basal plus",
    }
)
# Startswith prefixes (lowercase) for patterns too long for exact matching.
_NON_DRUG_STARTSWITH = (
    "aerobic ",
    "tobacco cessation",
    "nutritional ",
    "comparison of eating",
    "behavioral intervention",
    "low-level laser",
    "exercise program",
    "exercise training",
    "diet program",
    "lifestyle modification",
    "dietary supplement",
    "physical exercise",
    "resistance training",
    "cognitive behavioral",
    "no treatment",
    # Devices / wearables (v0.2d)
    "withings",
    "hem-col",
    "mems (",
    # Diagnostics / instruments (v0.2d)
    "questionnaire",
    "blood glucose meter",
    "comparison of different blood glucose",
    "glucose meter",
    "oral glucose tolerance",
)
# Regex for dosing-regimen names that start with a dose quantity (v0.2d).
# Matches: "0.5 units/kg ...", "1 unit ...", "2 units ..."
_DOSE_ONLY_RE = re.compile(r"^\d+(\.\d+)?\s+units?", re.IGNORECASE)

# D1: Stage ranks for deduplication (higher = later stage = preferred).
_DEDUP_STAGE_RANK = {
    "preclinical": 0,
    "phase1": 1,
    "phase1/2": 2,
    "phase2": 3,
    "phase2b": 4,
    "phase3": 5,
    "filed": 6,
    "approved": 7,
}

# D1 canonicalization: strip common drug-class prefix and route/form/dose
# suffixes from asset names before dedup key comparison.
_ASSET_CANON_PREFIXES = ("insulin ",)
_ASSET_CANON_SUFFIXES = (
    " via insulin pen",
    " via pen",
    " injection",
    " oral tablet",
    " oral tablets",
)
# Strip trailing dose specs: " 10mg Tab", " 300 U/mL", " 100 units", etc.
_ASSET_DOSE_SUFFIX_RE = re.compile(
    r"\s+\d+(\.\d+)?\s*(mg|mcg|ug|u/ml|u/kg|units?|iu|tablet|tab)\b.*$",
    re.IGNORECASE,
)


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
# D3: Non-drug filter
# ---------------------------------------------------------------------------


def _filter_non_drug_programs(programs: list[dict]) -> tuple[list[dict], dict]:
    """Remove behavioral/lifestyle/device interventions that are not pharmaceutical assets.

    Returns (kept_programs, meta) where meta has filtered_count and examples.
    """
    kept = []
    filtered_names = []
    for prog in programs:
        name = (prog.get("asset_name") or "").lower().strip()
        is_non_drug = (
            name in _NON_DRUG_EXACT
            or any(name.startswith(pat) for pat in _NON_DRUG_STARTSWITH)
            or bool(_DOSE_ONLY_RE.match(name))
        )
        if is_non_drug:
            filtered_names.append(prog.get("asset_name", ""))
        else:
            kept.append(prog)
    return kept, {"filtered_count": len(filtered_names), "examples": filtered_names[:5]}


# ---------------------------------------------------------------------------
# D1: Asset deduplication + name canonicalization
# ---------------------------------------------------------------------------


def _canonical_asset_name(name: str) -> str:
    """Return a canonical lowercase key for dedup: strip insulin prefix, route suffix, dose."""
    key = name.lower().strip()
    # Strip "insulin " prefix (insulin glargine → glargine, insulin alone stays)
    for prefix in _ASSET_CANON_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix):
            key = key[len(prefix) :]
            break
    # Strip route/form suffix (glargine via insulin pen → glargine)
    for suffix in _ASSET_CANON_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
            break
    # Strip trailing dose spec (glargine 300 u/ml → glargine, drug 10mg tab → drug)
    key = _ASSET_DOSE_SUFFIX_RE.sub("", key).strip()
    return key


def _deduplicate_programs(programs: list[dict]) -> list[dict]:
    """Collapse to one record per canonical (asset_name, company_name) at highest stage.

    Uses _canonical_asset_name for the grouping key so name variants like
    "insulin glargine" / "Glargine" / "glargine via insulin pen" collapse together.
    Merges source_refs and records trial_count.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for prog in programs:
        key = (
            _canonical_asset_name(prog.get("asset_name") or ""),
            (prog.get("company_name") or "").lower().strip(),
        )
        groups[key].append(prog)

    result = []
    for _key, group in groups.items():
        best = max(
            group,
            key=lambda p: _DEDUP_STAGE_RANK.get(p.get("clinical_stage"), -1),
        )
        seen_refs: set = set()
        merged_refs: list = []
        for p in group:
            for ref in p.get("source_refs") or []:
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    merged_refs.append(ref)
        best = dict(best)
        best["source_refs"] = merged_refs[:10]
        best["trial_count"] = len(group)
        result.append(best)

    return result


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
    preprocessing = manifest.get("_preprocessing", {})

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
        warnings.append(f"Disease view spans {len(mondo_ids)} MONDO IDs — includes disease label variants.")
    non_drug_filtered = preprocessing.get("non_drug_filtered_count", 0)
    if non_drug_filtered > 0:
        examples = preprocessing.get("non_drug_filtered_examples", [])[:3]
        examples_str = ", ".join(f'"{e}"' for e in examples)
        warnings.append(f"{non_drug_filtered} non-pharmaceutical programs filtered (e.g. {examples_str}).")
    canon_merges = preprocessing.get("canonicalization_merge_count", 0)
    if canon_merges > 0:
        canon_ex = preprocessing.get("canonicalization_examples", [])[:2]
        warnings.append(
            f"{canon_merges} asset-name variant groups merged by canonicalization " f"(e.g. {'; '.join(canon_ex)})."
        )

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
            "raw_program_count": preprocessing.get("raw_program_count", len(programs)),
            "non_drug_filtered_count": preprocessing.get("non_drug_filtered_count", 0),
            "canonicalization_merge_count": preprocessing.get("canonicalization_merge_count", 0),
            "deduped_program_count": preprocessing.get("deduped_program_count", len(programs)),
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
    cells = map_data["cells"]
    lanes = map_data["lanes"]

    disease = meta["disease_name"]
    ta = meta.get("therapeutic_area") or "—"
    as_of = meta.get("as_of_date", "unknown")
    generated = meta.get("generated_at_utc", "unknown")
    mondo_html = ", ".join(meta.get("mondo_ids") or []) or "—"

    n_programs = summ["total_programs"]
    raw_count = summ.get("raw_program_count", n_programs)
    non_drug_filtered = summ.get("non_drug_filtered_count", 0)
    deduped = summ.get("deduped_program_count", n_programs)
    stage_pct = summ["stage_coverage_pct"]
    mech_pct = summ["mechanism_coverage_pct"]
    ticker_pct = summ["ticker_coverage_pct"]
    stage_dist = summ.get("stage_distribution", {})
    canon_merges = summ.get("canonicalization_merge_count", 0)

    # Lane counts for right rail
    lane_counts = [(lane, sum(len(progs) for progs in cells[lane].values())) for lane in lanes]

    def _stage_label(s: str) -> str:
        labels = {
            "preclinical": "Preclinical",
            "phase1": "Phase 1",
            "phase1/2": "Phase 1/2",
            "phase2": "Phase 2",
            "phase2b": "Phase 2b",
            "phase3": "Phase 3",
            "filed": "Filed",
            "approved": "Approved",
            "unknown": "Unknown stage",
        }
        return labels.get(s, s.title())

    max_stage_count = max(stage_dist.values(), default=1)
    stage_rows = "".join(
        f'<tr><td class="sd-label">{_stage_label(s)}</td>'
        f'<td class="sd-count">{c}</td>'
        f'<td class="sd-bar"><div class="bar" style="width:{min(100, int(100 * c / max_stage_count))}%">'
        f"</div></td></tr>"
        for s, c in sorted(stage_dist.items(), key=lambda x: x[1], reverse=True)
    )

    max_lane_count = max((c for _, c in lane_counts if c > 0), default=1)
    lane_rows = "".join(
        f'<tr><td class="sd-label">{_xml_escape(ln)}</td>'
        f'<td class="sd-count">{cnt}</td>'
        f'<td class="sd-bar"><div class="bar{"" if ln != "Unknown Mechanism" else " bar-unknown"}" '
        f'style="width:{min(100, int(100 * cnt / max_lane_count))}%"></div></td></tr>'
        for ln, cnt in lane_counts
    )

    warning_blocks = "".join(f'<div class="warning-item">&#9888; {_xml_escape(str(w))}</div>' for w in warnings)
    warning_section = f'<div class="warning-block">{warning_blocks}</div>' if warnings else ""

    legend_swatches = "".join(
        f'<span class="ls"><span class="lsw" style="background:{color}"></span>{name}</span>'
        for name, color in _MODALITY_COLORS.items()
    )

    unknown_count = sum(len(progs) for progs in cells.get("Unknown Mechanism", {}).values())
    named_count = n_programs - unknown_count

    post_d3 = raw_count - non_drug_filtered
    pipeline_rows = (
        f'<div class="inv-row"><span>Raw CT.gov records</span><b>{raw_count:,}</b></div>'
        + (
            f'<div class="inv-row filtered"><span>Non-drug filtered (D3)</span>' f"<b>−{non_drug_filtered}</b></div>"
            if non_drug_filtered
            else ""
        )
        + (
            f'<div class="inv-row filtered"><span>Deduplicated (D1)</span>' f"<b>{deduped:,} unique</b></div>"
            if deduped != post_d3
            else f'<div class="inv-row"><span>After dedup (D1)</span><b>{deduped:,}</b></div>'
        )
        + (
            f'<div class="inv-row filtered"><span>Canon. merges</span>' f"<b>{canon_merges} groups</b></div>"
            if canon_merges
            else ""
        )
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scientific Cartography — {_xml_escape(disease)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Arial,Helvetica,sans-serif;font-size:13px;background:#eef0f3;color:#1a252f}}
/* Governance banner */
.gov-banner{{background:#1a252f;color:#aab7c4;padding:7px 20px;font-size:11px;letter-spacing:.04em;display:flex;align-items:center;gap:16px}}
.gov-banner b{{color:#e74c3c;font-size:12px}}
/* Poster header */
.poster-header{{background:linear-gradient(135deg,#2c3e50 0%,#1a252f 100%);color:#fff;padding:18px 28px 16px}}
.poster-header .sc-label{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#7f8c8d;margin-bottom:6px}}
.poster-header h1{{font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1.1;margin-bottom:10px}}
.poster-header .header-meta{{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:11px;color:#95a5a6}}
.poster-header .header-meta span b{{color:#bdc3c7}}
/* Three-column body */
.poster-body{{display:flex;align-items:flex-start;min-height:600px}}
/* Left rail */
.left-rail{{width:232px;flex-shrink:0;background:#fff;border-right:1px solid #dde1e7;padding:16px;display:flex;flex-direction:column;gap:16px}}
.rail-section h3{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#7f8c8d;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #eef0f3}}
.inv-row{{display:flex;justify-content:space-between;align-items:baseline;font-size:12px;padding:3px 0;border-bottom:1px solid #f5f6f7}}
.inv-row.filtered{{color:#888}}
.inv-row b{{font-size:13px;color:#2c3e50}}
.cov-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:4px}}
.cov-cell{{background:#f5f7fa;border-radius:4px;padding:6px 8px;text-align:center}}
.cov-cell .cov-val{{font-size:18px;font-weight:800;color:#2c3e50;line-height:1}}
.cov-cell .cov-lbl{{font-size:9px;color:#7f8c8d;text-transform:uppercase;letter-spacing:.06em;margin-top:2px}}
.caveat-item{{font-size:11px;color:#666;padding:3px 0;border-bottom:1px dotted #eee;line-height:1.4}}
.provenance-item{{font-size:11px;color:#555;padding:2px 0}}
/* Center panel */
.center-panel{{flex:1;min-width:0;padding:16px;display:flex;flex-direction:column;gap:12px}}
.warning-block{{background:#fff8e1;border-left:3px solid #f0ad4e;padding:8px 12px;border-radius:0 4px 4px 0}}
.warning-item{{font-size:11px;color:#856404;padding:2px 0;line-height:1.4}}
.map-viewport{{overflow-x:auto;background:#fff;border:1px solid #dde1e7;border-radius:4px;padding:8px}}
.legend-strip{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:10px;color:#555;background:#fff;border:1px solid #dde1e7;border-radius:4px;padding:8px 12px}}
.ls{{display:inline-flex;align-items:center;gap:4px}}
.lsw{{display:inline-block;width:10px;height:10px;border-radius:2px;flex-shrink:0}}
.legend-note{{font-size:10px;color:#888;margin-left:auto}}
/* Right rail */
.right-rail{{width:232px;flex-shrink:0;background:#fff;border-left:1px solid #dde1e7;padding:16px;display:flex;flex-direction:column;gap:16px}}
.sd-table{{width:100%;border-collapse:collapse;font-size:11px}}
.sd-table td{{padding:3px 0;vertical-align:middle}}
.sd-label{{color:#2c3e50;padding-right:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px}}
.sd-count{{color:#7f8c8d;width:28px;text-align:right;padding-right:6px;white-space:nowrap}}
.sd-bar{{width:60px}}
.bar{{height:8px;background:#4a90d9;border-radius:2px;min-width:2px}}
.bar-unknown{{background:#bdc3c7}}
.gap-row{{font-size:11px;padding:3px 0;display:flex;justify-content:space-between;border-bottom:1px solid #f5f6f7}}
.gap-row b{{color:#2c3e50}}
/* Footer */
.poster-footer{{background:#f8f9fa;border-top:2px solid #dde1e7;padding:10px 20px;font-size:10px;color:#888;display:flex;flex-wrap:wrap;gap:4px 20px}}
.poster-footer b{{color:#555}}
</style>
</head>
<body>

<div class="gov-banner">
  <b>DIAGNOSTIC ONLY — NOT AN INVESTMENT RECOMMENDATION</b>
  <span>Read-only · No ranking, selection, scoring, or production wiring · Frozen model · No live data</span>
  <span style="margin-left:auto">Scientific Cartography {_VERSION}</span>
</div>

<header class="poster-header">
  <div class="sc-label">Scientific Cartography · Disease Landscape Map</div>
  <h1>{_xml_escape(disease.title())}</h1>
  <div class="header-meta">
    <span><b>Therapeutic area:</b> {_xml_escape(ta)}</span>
    <span><b>MONDO:</b> {mondo_html}</span>
    <span><b>As of:</b> {as_of}</span>
    <span><b>Artifact source:</b> CT.gov diagnostic pipeline</span>
  </div>
</header>

<div class="poster-body">

  <aside class="left-rail">
    <section class="rail-section">
      <h3>Pipeline</h3>
      {pipeline_rows}
    </section>

    <section class="rail-section">
      <h3>Coverage</h3>
      <div class="cov-grid">
        <div class="cov-cell">
          <div class="cov-val">{stage_pct}%</div>
          <div class="cov-lbl">Stage</div>
        </div>
        <div class="cov-cell">
          <div class="cov-val">{mech_pct}%</div>
          <div class="cov-lbl">Mechanism</div>
        </div>
        <div class="cov-cell">
          <div class="cov-val">{ticker_pct}%</div>
          <div class="cov-lbl">Ticker</div>
        </div>
        <div class="cov-cell">
          <div class="cov-val">{len(lanes)}</div>
          <div class="cov-lbl">Lanes</div>
        </div>
      </div>
    </section>

    <section class="rail-section">
      <h3>Data Provenance</h3>
      <div class="provenance-item">Source: CT.gov trial records</div>
      <div class="provenance-item">No rankings.csv · No portfolio · No scores</div>
      <div class="provenance-item">As of: {as_of}</div>
    </section>

    <section class="rail-section">
      <h3>Caveats</h3>
      <div class="caveat-item">Mechanism coverage sparse — Unknown lane expected to dominate.</div>
      <div class="caveat-item">Ticker linkage requires authorized snapshot input.</div>
      <div class="caveat-item">Stage = highest observed in CT.gov; may lag reality.</div>
      <div class="caveat-item">Combination products conservatively left as Unknown Mechanism.</div>
    </section>
  </aside>

  <main class="center-panel">
    {warning_section}
    <div class="map-viewport">
      {svg_content}
    </div>
    <div class="legend-strip">
      <b style="font-size:10px;color:#555">Modality:</b>
      {legend_swatches}
      <span class="ls"><span class="lsw" style="background:{_DEFAULT_COLOR}"></span>unknown</span>
      <span class="legend-note">Opacity = confidence · Thick border = ticker linked</span>
    </div>
  </main>

  <aside class="right-rail">
    <section class="rail-section">
      <h3>Stage Distribution</h3>
      <table class="sd-table">
        {stage_rows}
      </table>
    </section>

    <section class="rail-section">
      <h3>Mechanism Lanes</h3>
      <table class="sd-table">
        {lane_rows}
      </table>
    </section>

    <section class="rail-section">
      <h3>Coverage Gaps</h3>
      <div class="gap-row"><span>Unknown mechanism</span><b>{unknown_count}</b></div>
      <div class="gap-row"><span>Named-lane programs</span><b>{named_count}</b></div>
      <div class="gap-row"><span>Unlinked tickers</span><b>{n_programs - int(n_programs * ticker_pct / 100)}</b></div>
      <div class="gap-row"><span>Unknown stage</span><b>{stage_dist.get("unknown", 0)}</b></div>
    </section>
  </aside>

</div>

<footer class="poster-footer">
  <span><b>Source:</b> Scientific Cartography diagnostic artifacts only</span>
  <span><b>Generator:</b> {_VERSION} · {generated}</span>
  <span><b>Governance:</b> READ_ONLY_DIAGNOSTIC · no production wiring · frozen model</span>
  <span><b>Forbidden sources:</b> rankings.csv, portfolio_positions.csv, screen_output.json — not read</span>
  <span>DIAGNOSTIC ONLY — NOT AN INVESTMENT RECOMMENDATION</span>
</footer>

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
- Ticker linkage comes from the diagnostic's authorized company/universe snapshot (`--company-file`); the live `rankings.csv` is never read here by design.
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

    raw_programs = _load_programs(input_dir, disease)
    raw_count = len(raw_programs)

    if not quiet:
        print(f"  Found {raw_count} raw matching programs", file=sys.stderr)

    if not raw_programs:
        raise ValueError(f"No programs found for disease query: {disease!r}")

    # D3: remove behavioral/lifestyle/device non-drug programs
    programs, non_drug_meta = _filter_non_drug_programs(raw_programs)
    if not quiet and non_drug_meta["filtered_count"]:
        print(
            f"  D3 filter: removed {non_drug_meta['filtered_count']} non-drug programs",
            file=sys.stderr,
        )

    # Track canonicalization merges: groups where multiple DISTINCT raw-lowercase
    # names map to the same canonical key (i.e., prefix/suffix stripping collapsed them).
    _canon_to_raw: dict[tuple, set] = defaultdict(set)
    for prog in programs:
        raw_lower = (prog.get("asset_name") or "").lower().strip()
        canon_key = _canonical_asset_name(prog.get("asset_name") or "")
        company_lower = (prog.get("company_name") or "").lower().strip()
        _canon_to_raw[(canon_key, company_lower)].add(raw_lower)
    canon_merge_count = sum(1 for raws in _canon_to_raw.values() if len(raws) > 1)
    canon_examples = [" / ".join(sorted(raws)[:3]) for raws in _canon_to_raw.values() if len(raws) > 1][:5]

    # D1: deduplicate by canonical (asset_name, company_name) → keep highest stage
    programs = _deduplicate_programs(programs)
    deduped_count = len(programs)

    if not quiet:
        pre_dedup = raw_count - non_drug_meta["filtered_count"]
        print(
            f"  D1 dedup: {pre_dedup} → {deduped_count} unique (canonical asset, company) programs",
            file=sys.stderr,
        )
        if canon_merge_count:
            print(
                f"  Canonicalization merged {canon_merge_count} asset-name variant groups",
                file=sys.stderr,
            )

    if not programs:
        raise ValueError(f"No programs remain after D3/D1 filtering for disease query: {disease!r}")

    manifest = _load_manifest(input_dir)
    manifest["_preprocessing"] = {
        "raw_program_count": raw_count,
        "non_drug_filtered_count": non_drug_meta["filtered_count"],
        "non_drug_filtered_examples": non_drug_meta["examples"],
        "deduped_program_count": deduped_count,
        "canonicalization_merge_count": canon_merge_count,
        "canonicalization_examples": canon_examples,
    }
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
