"""Fetch and ingest AACT clinical trial snapshot.

Downloads daily pipe-delimited flat files from AACT, normalizes into
a trial_master parquet/JSON artifact, and emits health metadata.

AACT source: https://aact.ctti-clinicaltrials.org/pipe_files

Usage:
    python tools/fetch_aact_snapshot.py --as-of-date 2026-04-01
    python tools/fetch_aact_snapshot.py --as-of-date 2026-04-01 --full-pipeline
    python tools/fetch_aact_snapshot.py --local-dir /path/to/aact_csvs --as-of-date 2026-04-01
    python tools/fetch_aact_snapshot.py --health-check
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_DATA = REPO_ROOT / "production_data"
AACT_SNAPSHOT_DIR = REPO_ROOT / "data" / "aact" / "snapshots"
AACT_DOWNLOAD_DIR = REPO_ROOT / "data" / "aact" / "downloads"
SPONSOR_MAP_PATH = PROD_DATA / "sponsor_alias_map.json"
OVERRIDE_MAP_PATH = PROD_DATA / "aact_manual_overrides.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("aact_ingest")

# AACT tables we ingest (pipe-delimited, UTF-8)
REQUIRED_TABLES = ["studies", "sponsors", "conditions", "interventions"]
OPTIONAL_TABLES = ["outcomes", "result_groups", "facility_investigators", "designs"]

# Canonical trial master fields
TRIAL_MASTER_FIELDS = [
    "nct_id",
    "brief_title",
    "official_title",
    "overall_status",
    "phase",
    "enrollment",
    "enrollment_type",
    "study_type",
    "primary_completion_date",
    "primary_completion_date_type",
    "completion_date",
    "completion_date_type",
    "results_first_posted_date",
    "study_first_posted_date",
    "last_update_posted_date",
    "start_date",
    "has_results",
    "source_snapshot_date",
]

SPONSOR_FIELDS = ["nct_id", "lead_sponsor_name", "collaborator_names"]
CONDITION_FIELDS = ["nct_id", "condition_names"]
INTERVENTION_FIELDS = ["nct_id", "intervention_names", "intervention_types"]

# Status normalization (AACT uses both Title Case and SCREAMING_SNAKE_CASE)
STATUS_NORMALIZE = {
    "recruiting": "Recruiting",
    "RECRUITING": "Recruiting",
    "active, not recruiting": "Active, not recruiting",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "completed": "Completed",
    "COMPLETED": "Completed",
    "terminated": "Terminated",
    "TERMINATED": "Terminated",
    "suspended": "Suspended",
    "SUSPENDED": "Suspended",
    "withdrawn": "Withdrawn",
    "WITHDRAWN": "Withdrawn",
    "enrolling by invitation": "Enrolling by invitation",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "not yet recruiting": "Not yet recruiting",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "unknown status": "Unknown",
    "UNKNOWN_STATUS": "Unknown",
    "no longer available": "No longer available",
    "NO_LONGER_AVAILABLE": "No longer available",
    "available": "Available",
    "AVAILABLE": "Available",
    "approved for marketing": "Approved for marketing",
    "APPROVED_FOR_MARKETING": "Approved for marketing",
    "temporarily not available": "Temporarily not available",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "withheld": "Withheld",
    "WITHHELD": "Withheld",
}

PHASE_NORMALIZE = {
    "Phase 1": "Phase 1",
    "PHASE1": "Phase 1",
    "Phase 2": "Phase 2",
    "PHASE2": "Phase 2",
    "Phase 3": "Phase 3",
    "PHASE3": "Phase 3",
    "Phase 4": "Phase 4",
    "PHASE4": "Phase 4",
    "Phase 1/Phase 2": "Phase 1/2",
    "PHASE1/PHASE2": "Phase 1/2",
    "Phase 2/Phase 3": "Phase 2/3",
    "PHASE2/PHASE3": "Phase 2/3",
    "Early Phase 1": "Early Phase 1",
    "EARLY_PHASE1": "Early Phase 1",
    "Not Applicable": "Not Applicable",
    "NOT_APPLICABLE": "Not Applicable",
    "N/A": "Not Applicable",
    "NA": "Not Applicable",
}


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_sponsor_map() -> dict[str, str]:
    """Load sponsor name → ticker mapping.

    Merges:
    1. production_data/sponsor_alias_map.json
    2. Existing TICKER_TO_SPONSORS from collect_ctgov_data.py (if importable)
    """
    mapping: dict[str, str] = {}

    # Load alias map
    data = _load_json(SPONSOR_MAP_PATH)
    if data and isinstance(data, dict):
        mapping.update(data)

    # Try to import existing sponsor mapping from collect_ctgov_data
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from collect_ctgov_data import TICKER_TO_SPONSORS

        for ticker, sponsors in TICKER_TO_SPONSORS.items():
            for sponsor in sponsors:
                if sponsor not in mapping:
                    mapping[sponsor] = ticker
    except (ImportError, Exception):
        pass

    return mapping


def _load_overrides() -> dict[str, dict]:
    """Load manual NCT ID → ticker overrides."""
    data = _load_json(OVERRIDE_MAP_PATH)
    return data if isinstance(data, dict) else {}


def _normalize_status(raw: str) -> str:
    return STATUS_NORMALIZE.get(raw, STATUS_NORMALIZE.get(raw.strip(), raw.strip()))


def _normalize_phase(raw: str) -> str:
    return PHASE_NORMALIZE.get(raw, PHASE_NORMALIZE.get(raw.strip(), raw.strip()))


def _parse_date_safe(v: str | None) -> str | None:
    if not v or v.strip() in ("", "N/A", "NA"):
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_int_safe(v: str | None) -> int | None:
    if not v or v.strip() in ("", "N/A"):
        return None
    try:
        return int(v.strip())
    except ValueError:
        return None


def _parse_bool_safe(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in ("t", "true", "1", "yes")


# ---------------------------------------------------------------------------
# AACT flat-file parsing
# ---------------------------------------------------------------------------


def _read_pipe_file(path: Path) -> list[dict]:
    """Read pipe-delimited AACT flat file."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            rows.append(row)
    return rows


def parse_studies(studies_path: Path, snapshot_date: str) -> dict[str, dict]:
    """Parse studies.txt → dict keyed by nct_id."""
    rows = _read_pipe_file(studies_path)
    trials = {}
    for row in rows:
        nct_id = row.get("nct_id", "").strip()
        if not nct_id:
            continue
        trials[nct_id] = {
            "nct_id": nct_id,
            "brief_title": row.get("brief_title", "").strip()[:500] or None,
            "official_title": row.get("official_title", "").strip()[:500] or None,
            "overall_status": _normalize_status(row.get("overall_status", "")),
            "phase": _normalize_phase(row.get("phase", "")),
            "enrollment": _parse_int_safe(row.get("enrollment")),
            "enrollment_type": row.get("enrollment_type", "").strip() or None,
            "study_type": row.get("study_type", "").strip() or None,
            "primary_completion_date": _parse_date_safe(row.get("primary_completion_date")),
            "primary_completion_date_type": row.get("primary_completion_date_type", "").strip() or None,
            "completion_date": _parse_date_safe(row.get("completion_date")),
            "completion_date_type": row.get("completion_date_type", "").strip() or None,
            "results_first_posted_date": _parse_date_safe(row.get("results_first_posted_date")),
            "study_first_posted_date": _parse_date_safe(row.get("study_first_posted_date")),
            "last_update_posted_date": _parse_date_safe(row.get("last_update_posted_date")),
            "start_date": _parse_date_safe(row.get("start_date")),
            "has_results": _parse_bool_safe(row.get("has_results")),
            "source_snapshot_date": snapshot_date,
        }
    return trials


def parse_sponsors(sponsors_path: Path) -> dict[str, dict]:
    """Parse sponsors.txt → dict keyed by nct_id with lead/collaborators."""
    rows = _read_pipe_file(sponsors_path)
    by_nct: dict[str, dict] = {}
    for row in rows:
        nct_id = row.get("nct_id", "").strip()
        if not nct_id:
            continue
        lead_or_collab = row.get("lead_or_collaborator", "").strip().lower()
        name = row.get("name", "").strip()
        if nct_id not in by_nct:
            by_nct[nct_id] = {"lead_sponsor_name": None, "collaborator_names": []}
        if lead_or_collab == "lead":
            by_nct[nct_id]["lead_sponsor_name"] = name
        else:
            by_nct[nct_id]["collaborator_names"].append(name)
    return by_nct


def parse_conditions(conditions_path: Path) -> dict[str, list[str]]:
    """Parse conditions.txt → dict keyed by nct_id with condition list."""
    rows = _read_pipe_file(conditions_path)
    by_nct: dict[str, list[str]] = {}
    for row in rows:
        nct_id = row.get("nct_id", "").strip()
        name = row.get("name", "").strip() or row.get("downcase_name", "").strip()
        if nct_id and name:
            by_nct.setdefault(nct_id, []).append(name)
    return by_nct


def parse_interventions(interventions_path: Path) -> dict[str, list[dict]]:
    """Parse interventions.txt → dict keyed by nct_id."""
    rows = _read_pipe_file(interventions_path)
    by_nct: dict[str, list[dict]] = {}
    for row in rows:
        nct_id = row.get("nct_id", "").strip()
        if not nct_id:
            continue
        by_nct.setdefault(nct_id, []).append(
            {
                "name": row.get("name", "").strip(),
                "intervention_type": row.get("intervention_type", "").strip(),
            }
        )
    return by_nct


# ---------------------------------------------------------------------------
# Sponsor linkage
# ---------------------------------------------------------------------------


def link_sponsors(
    trials: dict[str, dict],
    sponsor_map: dict[str, str],
    overrides: dict[str, dict],
) -> None:
    """Resolve sponsor → ticker linkage for each trial in-place."""
    for nct_id, trial in trials.items():
        # Check manual overrides first
        if nct_id in overrides:
            ovr = overrides[nct_id]
            trial["mapped_ticker"] = ovr.get("ticker")
            trial["mapping_confidence"] = "high"
            trial["mapping_method"] = "override"
            continue

        sponsor = trial.get("lead_sponsor_name", "")
        if not sponsor:
            trial["mapped_ticker"] = None
            trial["mapping_confidence"] = "none"
            trial["mapping_method"] = "unmatched"
            continue

        # Exact match
        if sponsor in sponsor_map:
            trial["mapped_ticker"] = sponsor_map[sponsor]
            trial["mapping_confidence"] = "high"
            trial["mapping_method"] = "exact"
            continue

        # Case-insensitive match
        sponsor_lower = sponsor.lower()
        matched = False
        for map_name, ticker in sponsor_map.items():
            if map_name.lower() == sponsor_lower:
                trial["mapped_ticker"] = ticker
                trial["mapping_confidence"] = "high"
                trial["mapping_method"] = "alias"
                matched = True
                break

        if not matched:
            # Substring match (lower confidence)
            for map_name, ticker in sponsor_map.items():
                if map_name.lower() in sponsor_lower or sponsor_lower in map_name.lower():
                    trial["mapped_ticker"] = ticker
                    trial["mapping_confidence"] = "medium"
                    trial["mapping_method"] = "alias"
                    matched = True
                    break

        if not matched:
            trial["mapped_ticker"] = None
            trial["mapping_confidence"] = "none"
            trial["mapping_method"] = "unmatched"


# ---------------------------------------------------------------------------
# Delta detection
# ---------------------------------------------------------------------------


def compute_deltas(
    current: dict[str, dict],
    prior: dict[str, dict],
    materiality_pcd_days: int = 14,
    materiality_enrollment_pct: float = 0.20,
) -> list[dict]:
    """Compute trial deltas between current and prior snapshots."""
    deltas = []
    current_ncts = set(current.keys())
    prior_ncts = set(prior.keys())

    # New trials
    for nct_id in current_ncts - prior_ncts:
        deltas.append(
            {
                "nct_id": nct_id,
                "delta_type": "new_trial",
                "old_value": None,
                "new_value": current[nct_id].get("overall_status"),
                "materiality_flag": False,
                "mapped_ticker": current[nct_id].get("mapped_ticker"),
            }
        )

    # Removed trials
    for nct_id in prior_ncts - current_ncts:
        deltas.append(
            {
                "nct_id": nct_id,
                "delta_type": "trial_removed_or_missing",
                "old_value": prior[nct_id].get("overall_status"),
                "new_value": None,
                "materiality_flag": True,
                "mapped_ticker": prior[nct_id].get("mapped_ticker"),
            }
        )

    # Changed trials
    terminal_statuses = {"Completed", "Terminated", "Withdrawn", "Suspended"}
    for nct_id in current_ncts & prior_ncts:
        cur = current[nct_id]
        pri = prior[nct_id]

        # Status change
        if cur.get("overall_status") != pri.get("overall_status"):
            is_material = cur.get("overall_status") in terminal_statuses
            deltas.append(
                {
                    "nct_id": nct_id,
                    "delta_type": "status_change",
                    "old_value": pri.get("overall_status"),
                    "new_value": cur.get("overall_status"),
                    "materiality_flag": is_material,
                    "mapped_ticker": cur.get("mapped_ticker"),
                }
            )

        # PCD change
        cur_pcd = cur.get("primary_completion_date")
        pri_pcd = pri.get("primary_completion_date")
        if cur_pcd and pri_pcd and cur_pcd != pri_pcd:
            try:
                d1 = datetime.strptime(pri_pcd, "%Y-%m-%d")
                d2 = datetime.strptime(cur_pcd, "%Y-%m-%d")
                shift_days = abs((d2 - d1).days)
                is_material = shift_days >= materiality_pcd_days
            except ValueError:
                shift_days = 0
                is_material = False
            deltas.append(
                {
                    "nct_id": nct_id,
                    "delta_type": "primary_completion_change",
                    "old_value": pri_pcd,
                    "new_value": cur_pcd,
                    "shift_days": shift_days,
                    "materiality_flag": is_material,
                    "mapped_ticker": cur.get("mapped_ticker"),
                }
            )

        # Enrollment change
        cur_enr = cur.get("enrollment")
        pri_enr = pri.get("enrollment")
        if cur_enr and pri_enr and cur_enr != pri_enr:
            pct_change = abs(cur_enr - pri_enr) / max(pri_enr, 1)
            is_material = pct_change >= materiality_enrollment_pct
            deltas.append(
                {
                    "nct_id": nct_id,
                    "delta_type": "enrollment_change",
                    "old_value": pri_enr,
                    "new_value": cur_enr,
                    "pct_change": round(pct_change, 3),
                    "materiality_flag": is_material,
                    "mapped_ticker": cur.get("mapped_ticker"),
                }
            )

        # Results posted
        if cur.get("results_first_posted_date") and not pri.get("results_first_posted_date"):
            deltas.append(
                {
                    "nct_id": nct_id,
                    "delta_type": "results_posted",
                    "old_value": None,
                    "new_value": cur.get("results_first_posted_date"),
                    "materiality_flag": True,
                    "mapped_ticker": cur.get("mapped_ticker"),
                }
            )

    return deltas


# ---------------------------------------------------------------------------
# Health report
# ---------------------------------------------------------------------------


def build_health_report(
    trials: dict[str, dict],
    deltas: list[dict],
    snapshot_date: str,
    tables_found: list[str],
    tables_missing: list[str],
    parse_warnings: list[str],
) -> dict:
    """Build aact_health.json artifact."""
    n_total = len(trials)
    n_linked = sum(1 for t in trials.values() if t.get("mapped_ticker"))
    n_high = sum(1 for t in trials.values() if t.get("mapping_confidence") == "high")
    n_medium = sum(1 for t in trials.values() if t.get("mapping_confidence") == "medium")

    # Status distribution
    status_dist: dict[str, int] = {}
    for t in trials.values():
        s = t.get("overall_status", "Unknown")
        status_dist[s] = status_dist.get(s, 0) + 1

    # Phase distribution
    phase_dist: dict[str, int] = {}
    for t in trials.values():
        p = t.get("phase", "Unknown")
        phase_dist[p] = phase_dist.get(p, 0) + 1

    # Delta summary
    delta_by_type: dict[str, int] = {}
    material_deltas = 0
    for d in deltas:
        dt = d["delta_type"]
        delta_by_type[dt] = delta_by_type.get(dt, 0) + 1
        if d.get("materiality_flag"):
            material_deltas += 1

    return {
        "schema": "aact_health.v1",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "n_trials": n_total,
        "n_linked_to_ticker": n_linked,
        "n_high_confidence_links": n_high,
        "n_medium_confidence_links": n_medium,
        "linkage_pct": round(100 * n_linked / max(n_total, 1), 1),
        "tables_found": tables_found,
        "tables_missing": tables_missing,
        "parse_warnings": parse_warnings[:20],
        "status_distribution": dict(sorted(status_dist.items(), key=lambda x: -x[1])),
        "phase_distribution": dict(sorted(phase_dist.items(), key=lambda x: -x[1])),
        "delta_summary": {
            "n_total": len(deltas),
            "n_material": material_deltas,
            "by_type": delta_by_type,
        },
    }


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_aact_snapshot(download_dir: Path, snapshot_date: str | None = None) -> Path | None:
    """Download AACT pipe-delimited flat file dump.

    AACT flat files are at:
      https://aact.ctti-clinicaltrials.org/static/exported_files/daily/{YYYY-MM-DD}
    """
    import urllib.request

    download_dir.mkdir(parents=True, exist_ok=True)
    dl_date = snapshot_date or date.today().isoformat()
    dest = download_dir / f"aact_{dl_date}.zip"

    if dest.exists() and dest.stat().st_size > 1_000_000:
        log.info("AACT snapshot already downloaded: %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
        return dest

    url = f"https://aact.ctti-clinicaltrials.org/static/exported_files/daily/{dl_date}"
    log.info("Downloading AACT flat files from %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WakeRobin-AACT-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        log.info("Downloaded: %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
        return dest
    except Exception as e:
        log.error("Download failed: %s", e)
        # Try previous day if today's snapshot isn't available yet
        if snapshot_date == date.today().isoformat():
            from datetime import timedelta

            yesterday = (date.today() - timedelta(days=1)).isoformat()
            log.info("Retrying with yesterday's date: %s", yesterday)
            return download_aact_snapshot(download_dir, yesterday)
        return None


def extract_aact_zip(zip_path: Path, extract_dir: Path) -> list[str]:
    """Extract AACT ZIP to directory, return list of extracted table names."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith(".txt") or name.endswith(".csv"):
                zf.extract(name, extract_dir)
                table_name = Path(name).stem
                extracted.append(table_name)
                log.info("Extracted: %s", name)
    return extracted


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_ingest(
    source_dir: Path,
    snapshot_date: str,
    prior_snapshot_dir: Path | None = None,
) -> dict:
    """Run the full AACT ingest pipeline.

    Returns health report dict.
    """
    output_dir = AACT_SNAPSHOT_DIR / snapshot_date
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load mappings
    sponsor_map = _load_sponsor_map()
    overrides = _load_overrides()
    log.info("Sponsor map: %d entries, overrides: %d", len(sponsor_map), len(overrides))

    # Parse tables
    tables_found = []
    tables_missing = []
    parse_warnings = []

    # Studies (required)
    studies_path = _find_table_file(source_dir, "studies")
    if not studies_path:
        log.error("studies.txt not found in %s", source_dir)
        tables_missing.append("studies")
        return build_health_report({}, [], snapshot_date, tables_found, tables_missing, ["FATAL: studies.txt missing"])

    tables_found.append("studies")
    trials = parse_studies(studies_path, snapshot_date)
    log.info("Parsed %d trials from studies", len(trials))

    # Sponsors
    sponsors_path = _find_table_file(source_dir, "sponsors")
    if sponsors_path:
        tables_found.append("sponsors")
        sponsor_data = parse_sponsors(sponsors_path)
        for nct_id, sdata in sponsor_data.items():
            if nct_id in trials:
                trials[nct_id].update(sdata)
        log.info("Merged sponsors for %d trials", len(sponsor_data))
    else:
        tables_missing.append("sponsors")
        parse_warnings.append("sponsors.txt missing — no sponsor linkage possible")

    # Conditions
    conditions_path = _find_table_file(source_dir, "conditions")
    if conditions_path:
        tables_found.append("conditions")
        condition_data = parse_conditions(conditions_path)
        for nct_id, conds in condition_data.items():
            if nct_id in trials:
                trials[nct_id]["condition_names"] = conds
    else:
        tables_missing.append("conditions")

    # Interventions
    interventions_path = _find_table_file(source_dir, "interventions")
    if interventions_path:
        tables_found.append("interventions")
        intervention_data = parse_interventions(interventions_path)
        for nct_id, intv in intervention_data.items():
            if nct_id in trials:
                trials[nct_id]["intervention_names"] = [i["name"] for i in intv]
                trials[nct_id]["intervention_types"] = list(
                    set(i["intervention_type"] for i in intv if i["intervention_type"])
                )
    else:
        tables_missing.append("interventions")

    # Sponsor linkage
    link_sponsors(trials, sponsor_map, overrides)
    n_linked = sum(1 for t in trials.values() if t.get("mapped_ticker"))
    log.info("Sponsor linkage: %d/%d trials linked to tickers", n_linked, len(trials))

    # Compute deltas
    deltas = []
    if prior_snapshot_dir:
        prior_master_path = prior_snapshot_dir / "trial_master.json"
        if prior_master_path.exists():
            with open(prior_master_path, encoding="utf-8") as f:
                prior_data = json.load(f)
            prior_trials = {t["nct_id"]: t for t in prior_data.get("trials", [])}
            deltas = compute_deltas(trials, prior_trials)
            log.info("Deltas: %d total, %d material", len(deltas), sum(1 for d in deltas if d.get("materiality_flag")))

    # Write trial_master.json
    master_output = {
        "schema": "aact_trial_master.v1",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "n_trials": len(trials),
        "trials": list(trials.values()),
    }
    master_path = output_dir / "trial_master.json"
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master_output, f)
    log.info("Wrote trial_master.json: %d trials (%.1f MB)", len(trials), master_path.stat().st_size / 1e6)

    # Write deltas
    if deltas:
        deltas_path = output_dir / "trial_status_deltas.jsonl"
        with open(deltas_path, "w", encoding="utf-8") as f:
            for d in deltas:
                f.write(json.dumps(d) + "\n")
        log.info("Wrote %d deltas to trial_status_deltas.jsonl", len(deltas))

    # Write health report
    health = build_health_report(trials, deltas, snapshot_date, tables_found, tables_missing, parse_warnings)
    health_path = output_dir / "aact_health.json"
    with open(health_path, "w", encoding="utf-8") as f:
        json.dump(health, f, indent=2)
    log.info("Wrote aact_health.json")

    return health


def _find_table_file(source_dir: Path, table_name: str) -> Path | None:
    """Find an AACT table file (may be .txt or .csv, possibly in subdirectory)."""
    for ext in [".txt", ".csv"]:
        direct = source_dir / f"{table_name}{ext}"
        if direct.exists():
            return direct
    # Search subdirectories
    for f in source_dir.rglob(f"{table_name}.*"):
        if f.suffix in (".txt", ".csv"):
            return f
    return None


def _find_prior_snapshot(snapshot_date: str) -> Path | None:
    """Find the most recent snapshot before the given date."""
    if not AACT_SNAPSHOT_DIR.exists():
        return None
    dirs = sorted(
        (d for d in AACT_SNAPSHOT_DIR.iterdir() if d.is_dir() and d.name < snapshot_date),
        reverse=True,
    )
    return dirs[0] if dirs else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="AACT Trial Ingest Agent — Phase 1")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--local-dir", type=Path, help="Path to pre-downloaded AACT flat files")
    parser.add_argument("--download", action="store_true", help="Download latest AACT snapshot")
    parser.add_argument("--full-pipeline", action="store_true", help="Download + ingest + deltas")
    parser.add_argument("--health-check", action="store_true", help="Check latest snapshot health")
    args = parser.parse_args()

    if args.health_check:
        latest = _find_prior_snapshot("9999-99-99")
        if not latest:
            log.error("No AACT snapshots found")
            sys.exit(1)
        health_path = latest / "aact_health.json"
        if health_path.exists():
            with open(health_path) as f:
                health = json.load(f)
            log.info(
                "Latest snapshot: %s — %d trials, %.1f%% linked",
                health["snapshot_date"],
                health["n_trials"],
                health["linkage_pct"],
            )
        else:
            log.warning("No health report in %s", latest)
        sys.exit(0)

    source_dir = args.local_dir
    if args.download or args.full_pipeline:
        zip_path = download_aact_snapshot(AACT_DOWNLOAD_DIR)
        if not zip_path:
            sys.exit(1)
        source_dir = AACT_DOWNLOAD_DIR / f"extracted_{args.as_of_date}"
        extract_aact_zip(zip_path, source_dir)

    if not source_dir:
        log.error("Specify --local-dir or --download")
        sys.exit(1)

    if not source_dir.exists():
        log.error("Source directory not found: %s", source_dir)
        sys.exit(1)

    prior = _find_prior_snapshot(args.as_of_date)
    health = run_ingest(source_dir, args.as_of_date, prior)

    log.info(
        "Done: %d trials, %.1f%% linked, %d deltas (%d material)",
        health["n_trials"],
        health["linkage_pct"],
        health["delta_summary"]["n_total"],
        health["delta_summary"]["n_material"],
    )


if __name__ == "__main__":
    main()
