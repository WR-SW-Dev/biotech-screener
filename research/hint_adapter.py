"""HINT/TOP dataset adapter — schema mapper and data loader.

Maps HINT clinical-trial-outcome-prediction data into our internal schema.
Used for benchmarking PoS v3 and extracting protocol-derived features.

HINT repo: vendor/hint/ (cloned from github.com/futianfan/clinical-trial-outcome-prediction)
License: non-commercial research use only.

Data flow:
    vendor/hint/data/raw_data.csv → HINTRecord → internal schema fields

PIT safety:
    - HINT labels are benchmark-only (label_source="hint_top_benchmark")
    - HINT outcomes are NOT used in live inference
    - Protocol features derived from eligibility text are PIT-safe
      (eligibility is posted to ClinicalTrials.gov before trial start)
"""

from __future__ import annotations

import ast
import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HINT_DATA_DIR = Path(__file__).resolve().parent.parent / "vendor" / "hint" / "data"

# Phase normalization: HINT uses "phase 1", "phase 2", "phase 3"
_HINT_PHASE_MAP = {
    "phase 1": "1",
    "phase 1/phase 2": "1_2",
    "phase 2": "2",
    "phase 2/phase 3": "2_3",
    "phase 3": "3",
    "phase 4": "4",
    "early phase 1": "1",
}


@dataclass
class HINTRecord:
    """Single HINT/TOP trial record mapped to internal schema."""

    nctid: str
    phase: str  # normalized: "1", "2", "3", etc.
    label: int  # 1 = success, 0 = failure
    diseases: List[str]
    drugs: List[str]
    icdcodes: List[str]
    criteria_text: str
    status: str
    why_stop: str

    # Derived fields (populated by schema mapper)
    hint_drug_norm: str = ""
    hint_disease_norm: str = ""
    hint_protocol_text: str = ""
    hint_phase: str = ""
    hint_label: int = 0
    hint_match_confidence: float = 0.0

    # PIT safety tag
    label_source: str = "hint_top_benchmark"
    usage: str = "offline_eval_only"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nctid": self.nctid,
            "phase": self.phase,
            "label": self.label,
            "diseases": self.diseases,
            "drugs": self.drugs,
            "criteria_text": self.criteria_text[:500],
            "hint_drug_norm": self.hint_drug_norm,
            "hint_disease_norm": self.hint_disease_norm,
            "hint_phase": self.hint_phase,
            "hint_label": self.hint_label,
            "hint_match_confidence": self.hint_match_confidence,
            "label_source": self.label_source,
            "usage": self.usage,
        }


def _safe_parse_list(raw: str) -> List[str]:
    """Parse a Python-style list string, e.g. "['a', 'b']"."""
    if not raw or raw.strip() in ("", "[]"):
        return []
    try:
        result = ast.literal_eval(raw)
        if isinstance(result, list):
            return [str(x) for x in result]
        return [str(result)]
    except (ValueError, SyntaxError):
        return [raw.strip()]


def load_hint_raw(
    data_dir: Path = HINT_DATA_DIR,
    phase_filter: Optional[str] = None,
) -> List[HINTRecord]:
    """Load HINT raw_data.csv into HINTRecord objects.

    Args:
        data_dir: Path to vendor/hint/data/.
        phase_filter: Optional phase to filter ("1", "2", "3"). None = all.

    Returns:
        List of HINTRecord objects.
    """
    raw_path = data_dir / "raw_data.csv"
    if not raw_path.exists():
        logger.warning("HINT raw_data.csv not found at %s", raw_path)
        return []

    records = []
    with open(raw_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            phase_raw = row.get("phase", "").strip().lower()
            phase = _HINT_PHASE_MAP.get(phase_raw, "unknown")

            if phase_filter and phase != phase_filter:
                continue

            diseases = _safe_parse_list(row.get("diseases", ""))
            drugs = _safe_parse_list(row.get("drugs", ""))
            icdcodes = _safe_parse_list(row.get("icdcodes", ""))
            criteria = row.get("criteria", "").strip()

            rec = HINTRecord(
                nctid=row.get("nctid", ""),
                phase=phase,
                label=int(row.get("label", 0)),
                diseases=diseases,
                drugs=drugs,
                icdcodes=icdcodes,
                criteria_text=criteria,
                status=row.get("status", ""),
                why_stop=row.get("why_stop", ""),
                hint_drug_norm=drugs[0].lower() if drugs else "",
                hint_disease_norm=diseases[0].lower() if diseases else "",
                hint_protocol_text=criteria,
                hint_phase=phase,
                hint_label=int(row.get("label", 0)),
            )
            records.append(rec)

    logger.info("HINT: loaded %d records (phase=%s)", len(records), phase_filter or "all")
    return records


def load_hint_splits(
    data_dir: Path = HINT_DATA_DIR,
    phase: str = "III",
) -> Dict[str, List[HINTRecord]]:
    """Load HINT train/valid/test splits for a given phase.

    Returns:
        {"train": [...], "valid": [...], "test": [...]}
    """
    splits = {}
    for split in ("train", "valid", "test"):
        fname = f"phase_{phase}_{split}.csv"
        fpath = data_dir / fname
        if not fpath.exists():
            logger.warning("HINT split file not found: %s", fpath)
            splits[split] = []
            continue

        records = []
        with open(fpath, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                phase_raw = row.get("phase", "").strip().lower()
                ph = _HINT_PHASE_MAP.get(phase_raw, "unknown")
                diseases = _safe_parse_list(row.get("diseases", ""))
                drugs = _safe_parse_list(row.get("drugs", ""))
                criteria = row.get("criteria", "").strip()

                rec = HINTRecord(
                    nctid=row.get("nctid", ""),
                    phase=ph,
                    label=int(row.get("label", 0)),
                    diseases=diseases,
                    drugs=drugs,
                    icdcodes=_safe_parse_list(row.get("icdcodes", "")),
                    criteria_text=criteria,
                    status=row.get("status", ""),
                    why_stop=row.get("why_stop", ""),
                    hint_drug_norm=drugs[0].lower() if drugs else "",
                    hint_disease_norm=diseases[0].lower() if diseases else "",
                    hint_protocol_text=criteria,
                    hint_phase=ph,
                    hint_label=int(row.get("label", 0)),
                )
                records.append(rec)
        splits[split] = records
        logger.info("HINT %s_%s: %d records", phase, split, len(records))

    return splits


def load_hint_sponsor_rates(
    data_dir: Path = HINT_DATA_DIR,
) -> Dict[str, Dict[str, float]]:
    """Load HINT sponsor approval rate table.

    Returns:
        {sponsor_name: {"approval_rate": float, "total": int}}
    """
    path = data_dir / "sponsor2approvalrate.csv"
    if not path.exists():
        return {}
    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sponsor = row.get("sponsor", "").strip()
            if not sponsor:
                continue
            try:
                result[sponsor] = {
                    "approval_rate": float(row.get("approval_rate", 0)),
                    "total": int(row.get("total", 0)),
                }
            except (ValueError, TypeError):
                continue
    return result


def match_hint_to_internal(
    hint_records: List[HINTRecord],
    our_nct_ids: set,
) -> Dict[str, HINTRecord]:
    """Match HINT records to our universe by NCT ID.

    Returns:
        {nctid: HINTRecord} for records in our universe.
    """
    matched = {}
    for rec in hint_records:
        if rec.nctid in our_nct_ids:
            rec.hint_match_confidence = 1.0  # exact NCT match
            matched[rec.nctid] = rec
    logger.info("HINT match: %d/%d records matched to our NCT IDs", len(matched), len(hint_records))
    return matched
