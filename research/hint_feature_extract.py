"""Protocol feature extraction from HINT/TOP eligibility criteria text.

Extracts transparent, auditable, PIT-safe features from trial eligibility
criteria that can feed the existing clinical_score_z decomposition.

No deep learning. No BioBERT. Just text pattern extraction.

PIT safety: eligibility criteria are posted to ClinicalTrials.gov before
trial enrollment begins. These features are safe for pre-catalyst inference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ProtocolFeatures:
    """Engineered features from trial eligibility/protocol text.

    All fields are PIT-safe (derived from pre-trial-start public data).
    """

    nctid: str

    # Structural counts
    inclusion_criteria_count: int
    exclusion_criteria_count: int
    eligibility_text_length: int

    # Design flags
    biomarker_selection_flag: bool
    comparator_present_flag: bool
    randomization_flag: bool
    blinding_flag: bool
    multi_arm_flag: bool

    # Complexity proxy
    endpoint_specificity_proxy: float  # [0, 1]
    protocol_complexity_score: float  # [0, 1]

    # PIT tag
    pit_status: str = "pre_catalyst_safe"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nctid": self.nctid,
            "inclusion_criteria_count": self.inclusion_criteria_count,
            "exclusion_criteria_count": self.exclusion_criteria_count,
            "eligibility_text_length": self.eligibility_text_length,
            "biomarker_selection_flag": self.biomarker_selection_flag,
            "comparator_present_flag": self.comparator_present_flag,
            "randomization_flag": self.randomization_flag,
            "blinding_flag": self.blinding_flag,
            "multi_arm_flag": self.multi_arm_flag,
            "endpoint_specificity_proxy": round(self.endpoint_specificity_proxy, 4),
            "protocol_complexity_score": round(self.protocol_complexity_score, 4),
            "pit_status": self.pit_status,
        }


# ---------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------

_BIOMARKER_PATTERNS = [
    r"\bbiomarker\b",
    r"\bher2\b",
    r"\bher-2\b",
    r"\begfr\b",
    r"\bbraf\b",
    r"\bkras\b",
    r"\bbrca\b",
    r"\bpd-l1\b",
    r"\bpdl1\b",
    r"\bmsi\b",
    r"\btmb\b",
    r"\balk\b",
    r"\bfgfr\b",
    r"\bntrk\b",
    r"\bret\b",
    r"\bcd19\b",
    r"\bcd20\b",
    r"\bcd38\b",
    r"\bbcma\b",
    r"\bmolecular.?select",
    r"\bgenotype\b",
    r"\bmutation.?positive\b",
    r"\bexpression.?positive\b",
    r"\bmarker.?positive\b",
]

_COMPARATOR_PATTERNS = [
    r"\bplacebo\b",
    r"\bcomparator\b",
    r"\bstandard.?of.?care\b",
    r"\bactive.?control\b",
    r"\bsoc\b",
    r"\bcontrol.?arm\b",
    r"\bbest.?supportive\b",
]

_RANDOMIZATION_PATTERNS = [
    r"\brandom\w*\b",
    r"\brandomiz\w*\b",
]

_BLINDING_PATTERNS = [
    r"\bdouble.?blind\b",
    r"\bsingle.?blind\b",
    r"\btriple.?blind\b",
    r"\bblinded\b",
    r"\bmasked\b",
    r"\bdouble.?mask\b",
]

_MULTI_ARM_PATTERNS = [
    r"\bmulti.?arm\b",
    r"\b\d+.?arm\b",
    r"\bthree.?arm\b",
    r"\bfour.?arm\b",
    r"\bcohort\s+[a-d]\b",
]

_ENDPOINT_KEYWORDS = [
    r"\boverall.?survival\b",
    r"\bprogression.?free\b",
    r"\bpfs\b",
    r"\bcomplete.?response\b",
    r"\bobjective.?response\b",
    r"\borr\b",
    r"\bprimary.?endpoint\b",
    r"\bco-primary\b",
    r"\bhazard.?ratio\b",
    r"\bkaplan\b",
    r"\bsuperior\b",
    r"\bnon.?inferior\b",
]


def _count_criteria(text: str, section: str) -> int:
    """Count bullet-point criteria in inclusion/exclusion section."""
    lines = text.split("\n")
    in_section = False
    count = 0
    for line in lines:
        stripped = line.strip().lower()
        if section in stripped:
            in_section = True
            continue
        if in_section:
            # End of section if we hit the other section header
            other = "exclusion" if section == "inclusion" else "inclusion"
            if other in stripped:
                break
            # Count lines that start with a bullet marker
            if re.match(r"^[-–•*]\s|^\d+[\.\)]\s|^[a-z][\.\)]\s", stripped):
                count += 1
    return count


def _has_pattern(text: str, patterns: list) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in patterns)


def _endpoint_specificity(text: str) -> float:
    """Score how specific the protocol is about endpoints. [0, 1]."""
    lower = text.lower()
    hits = sum(1 for p in _ENDPOINT_KEYWORDS if re.search(p, lower))
    return min(hits / 5.0, 1.0)  # saturates at 5 endpoint keywords


def _protocol_complexity(
    inclusion_n: int,
    exclusion_n: int,
    text_len: int,
    biomarker: bool,
    multi_arm: bool,
) -> float:
    """Composite protocol complexity score. [0, 1].

    Higher = more complex trial design (more criteria, longer text,
    biomarker selection, multi-arm). Complex trials have lower base-rate
    PoS but higher quality if they succeed.
    """
    import math

    # Normalized components
    criteria_score = min((inclusion_n + exclusion_n) / 30.0, 1.0)
    length_score = min(math.log1p(text_len) / math.log1p(5000), 1.0)
    biomarker_score = 0.2 if biomarker else 0.0
    multi_arm_score = 0.1 if multi_arm else 0.0

    return min(
        0.35 * criteria_score + 0.30 * length_score + 0.20 * biomarker_score + 0.15 * multi_arm_score,
        1.0,
    )


def extract_protocol_features(
    nctid: str,
    criteria_text: str,
) -> ProtocolFeatures:
    """Extract structured features from trial eligibility criteria text.

    All outputs are PIT-safe (derived from publicly posted eligibility text).
    """
    text = criteria_text or ""

    inclusion_n = _count_criteria(text, "inclusion")
    exclusion_n = _count_criteria(text, "exclusion")
    text_len = len(text)

    biomarker = _has_pattern(text, _BIOMARKER_PATTERNS)
    comparator = _has_pattern(text, _COMPARATOR_PATTERNS)
    randomization = _has_pattern(text, _RANDOMIZATION_PATTERNS)
    blinding = _has_pattern(text, _BLINDING_PATTERNS)
    multi_arm = _has_pattern(text, _MULTI_ARM_PATTERNS)

    endpoint_spec = _endpoint_specificity(text)
    complexity = _protocol_complexity(inclusion_n, exclusion_n, text_len, biomarker, multi_arm)

    return ProtocolFeatures(
        nctid=nctid,
        inclusion_criteria_count=inclusion_n,
        exclusion_criteria_count=exclusion_n,
        eligibility_text_length=text_len,
        biomarker_selection_flag=biomarker,
        comparator_present_flag=comparator,
        randomization_flag=randomization,
        blinding_flag=blinding,
        multi_arm_flag=multi_arm,
        endpoint_specificity_proxy=endpoint_spec,
        protocol_complexity_score=complexity,
    )


def extract_batch(
    records: list,
) -> Dict[str, ProtocolFeatures]:
    """Extract protocol features for a batch of HINTRecords or dicts.

    Args:
        records: List of HINTRecord objects or dicts with 'nctid' and 'criteria_text'.

    Returns:
        {nctid: ProtocolFeatures}
    """
    result = {}
    for rec in records:
        if hasattr(rec, "nctid"):
            nctid = rec.nctid
            text = rec.criteria_text
        else:
            nctid = rec.get("nctid", rec.get("nct_id", ""))
            text = rec.get("criteria_text", rec.get("criteria", ""))

        if not nctid:
            continue
        result[nctid] = extract_protocol_features(nctid, text)
    return result
