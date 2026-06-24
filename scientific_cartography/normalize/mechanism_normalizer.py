"""Normalize mechanism class, modality, and target from raw intervention text."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MechanismResolution:
    """Result of mechanism/modality/target normalization."""

    raw_text: str
    """Raw intervention/asset text from source."""

    normalized_text: Optional[str] = None
    """Normalized mechanism text if resolved."""

    modality: Optional[str] = None
    """Modality: small molecule, mAb, cell therapy, gene therapy, RNA, etc."""

    mechanism_class: Optional[str] = None
    """Mechanism class: JAK inhibitor, IL-13 mAb, BTK inhibitor, etc."""

    target: Optional[str] = None
    """Drug target if explicitly identified: EGFR, IL13, TYK2, CD19, etc."""

    confidence: float = 0.0
    """Confidence in resolution (0.0 to 1.0)."""

    resolution_status: str = "unknown"
    """Status: resolved, ambiguous, unknown."""

    source_refs: list[str] = field(default_factory=list)
    """Source references for the normalization."""

    warnings: list[str] = field(default_factory=list)
    """Warnings encountered during normalization."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "modality": self.modality,
            "mechanism_class": self.mechanism_class,
            "target": self.target,
            "confidence": self.confidence,
            "resolution_status": self.resolution_status,
            "source_refs": self.source_refs,
            "warnings": self.warnings,
        }


class MechanismNormalizer:
    """Normalize mechanism class, modality, and target conservatively."""

    def __init__(
        self,
        mechanism_aliases: Optional[dict[str, dict]] = None,
        as_of_date: str = "",
    ):
        """Initialize mechanism normalizer.

        Args:
            mechanism_aliases: Dict mapping raw_text -> {mechanism_class, target, modality, confidence}
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date
        self.mechanism_aliases = mechanism_aliases or {}
        self._cache: dict[str, MechanismResolution] = {}

        # Built-in mechanism dictionary
        self._mechanism_dict = {
            "jak inhibitor": {"mechanism_class": "JAK inhibitor", "target": "JAK", "modality": "small molecule"},
            "tyk2 inhibitor": {
                "mechanism_class": "TYK2 inhibitor",
                "target": "TYK2",
                "modality": "small molecule",
            },
            "btk inhibitor": {"mechanism_class": "BTK inhibitor", "target": "BTK", "modality": "small molecule"},
            "egfr inhibitor": {"mechanism_class": "EGFR inhibitor", "target": "EGFR", "modality": "small molecule"},
            "kras inhibitor": {"mechanism_class": "KRAS inhibitor", "target": "KRAS", "modality": "small molecule"},
            "parp inhibitor": {"mechanism_class": "PARP inhibitor", "target": "PARP", "modality": "small molecule"},
            "cdk4/6 inhibitor": {
                "mechanism_class": "CDK4/6 inhibitor",
                "target": "CDK4/6",
                "modality": "small molecule",
            },
            "glp-1 receptor agonist": {
                "mechanism_class": "GLP-1 receptor agonist",
                "target": "GLP1R",
                "modality": "small molecule",
            },
            "pcsk9 inhibitor": {
                "mechanism_class": "PCSK9 inhibitor",
                "target": "PCSK9",
                "modality": "small molecule",
            },
            "pcsk9 sirna": {"mechanism_class": "PCSK9 siRNA", "target": "PCSK9", "modality": "RNA therapy"},
            "il-13 monoclonal antibody": {
                "mechanism_class": "IL-13 monoclonal antibody",
                "target": "IL13",
                "modality": "monoclonal antibody",
            },
            "il-13 mab": {
                "mechanism_class": "IL-13 monoclonal antibody",
                "target": "IL13",
                "modality": "monoclonal antibody",
            },
            "il-4r alpha monoclonal antibody": {
                "mechanism_class": "IL-4R alpha monoclonal antibody",
                "target": "IL4RA",
                "modality": "monoclonal antibody",
            },
            "tnf inhibitor": {
                "mechanism_class": "TNF inhibitor",
                "target": "TNF",
                "modality": "monoclonal antibody",
            },
            "vegf inhibitor": {
                "mechanism_class": "VEGF inhibitor",
                "target": "VEGF",
                "modality": "monoclonal antibody",
            },
            "pd-1 inhibitor": {
                "mechanism_class": "PD-1 inhibitor",
                "target": "PDCD1",
                "modality": "monoclonal antibody",
            },
            "pd-l1 inhibitor": {
                "mechanism_class": "PD-L1 inhibitor",
                "target": "CD274",
                "modality": "monoclonal antibody",
            },
            "ctla-4 inhibitor": {
                "mechanism_class": "CTLA-4 inhibitor",
                "target": "CTLA4",
                "modality": "monoclonal antibody",
            },
            "cd19 car-t": {
                "mechanism_class": "CD19 CAR-T",
                "target": "CD19",
                "modality": "cell therapy",
            },
            "anti-cd19 car-t": {
                "mechanism_class": "CD19 CAR-T",
                "target": "CD19",
                "modality": "cell therapy",
            },
            "bcma car-t": {
                "mechanism_class": "BCMA CAR-T",
                "target": "BCMA",
                "modality": "cell therapy",
            },
            "aav gene therapy": {
                "mechanism_class": "AAV gene therapy",
                "target": None,
                "modality": "gene therapy",
            },
            "antisense oligonucleotide": {
                "mechanism_class": "antisense oligonucleotide",
                "target": None,
                "modality": "RNA therapy",
            },
            "aso": {"mechanism_class": "antisense oligonucleotide", "target": None, "modality": "RNA therapy"},
            "enzyme replacement therapy": {
                "mechanism_class": "enzyme replacement therapy",
                "target": None,
                "modality": "protein/enzyme therapy",
            },
            "mek inhibitor": {"mechanism_class": "MEK inhibitor", "target": "MEK", "modality": "small molecule"},
            "pi3k inhibitor": {"mechanism_class": "PI3K inhibitor", "target": "PI3K", "modality": "small molecule"},
            "akt inhibitor": {"mechanism_class": "AKT inhibitor", "target": "AKT", "modality": "small molecule"},
            "flt3 inhibitor": {"mechanism_class": "FLT3 inhibitor", "target": "FLT3", "modality": "small molecule"},
            "bcr-abl inhibitor": {
                "mechanism_class": "BCR-ABL inhibitor",
                "target": "BCR-ABL",
                "modality": "small molecule",
            },
            "hif inhibitor": {"mechanism_class": "HIF inhibitor", "target": "HIF", "modality": "small molecule"},
            "wnt inhibitor": {"mechanism_class": "WNT inhibitor", "target": "WNT", "modality": "small molecule"},
            "notch inhibitor": {"mechanism_class": "NOTCH inhibitor", "target": "NOTCH", "modality": "small molecule"},
            "hedgehog inhibitor": {
                "mechanism_class": "Hedgehog inhibitor",
                "target": "GLI",
                "modality": "small molecule",
            },
            "alpha-1 antitrypsin": {
                "mechanism_class": "Alpha-1 antitrypsin",
                "target": "SERPINA1",
                "modality": "protein/enzyme therapy",
            },
            "igf-1r inhibitor": {
                "mechanism_class": "IGF-1R inhibitor",
                "target": "IGF1R",
                "modality": "small molecule",
            },
            "met inhibitor": {"mechanism_class": "MET inhibitor", "target": "MET", "modality": "small molecule"},
            "tie-2 inhibitor": {"mechanism_class": "TIE-2 inhibitor", "target": "TIE2", "modality": "small molecule"},
            "fgf receptor inhibitor": {
                "mechanism_class": "FGFR inhibitor",
                "target": "FGFR",
                "modality": "small molecule",
            },
            "map kinase inhibitor": {
                "mechanism_class": "MAP kinase inhibitor",
                "target": "MAPK",
                "modality": "small molecule",
            },
        }

    def _normalize_for_lookup(self, raw_text: str) -> str:
        """Normalize text for lookup."""
        return raw_text.lower().strip()

    def normalize(self, raw_intervention: str) -> MechanismResolution:
        """Normalize raw intervention text to mechanism/modality/target.

        Args:
            raw_intervention: Raw intervention/asset name from trial.

        Returns:
            MechanismResolution with normalized fields or unknowns.
        """
        # Check cache
        cache_key = self._normalize_for_lookup(raw_intervention)
        if cache_key in self._cache:
            return self._cache[cache_key]

        warnings = []
        normalized = self._normalize_for_lookup(raw_intervention)

        # Try manual alias (highest priority)
        if normalized in self.mechanism_aliases:
            alias_data = self.mechanism_aliases[normalized]
            result = MechanismResolution(
                raw_text=raw_intervention,
                normalized_text=raw_intervention,
                mechanism_class=alias_data.get("mechanism_class"),
                modality=alias_data.get("modality"),
                target=alias_data.get("target"),
                confidence=alias_data.get("confidence", 0.95),
                resolution_status="resolved",
                source_refs=alias_data.get("source_refs", []),
                warnings=[],
            )
            self._cache[cache_key] = result
            return result

        # Try exact mechanism dictionary match
        if normalized in self._mechanism_dict:
            mech_data = self._mechanism_dict[normalized]
            result = MechanismResolution(
                raw_text=raw_intervention,
                normalized_text=raw_intervention,
                mechanism_class=mech_data.get("mechanism_class"),
                modality=mech_data.get("modality"),
                target=mech_data.get("target"),
                confidence=0.95,
                resolution_status="resolved",
                source_refs=[],
                warnings=[],
            )
            self._cache[cache_key] = result
            return result

        # Try substring match (conservative: only known phrases)
        substring_matches = [k for k in self._mechanism_dict.keys() if k in normalized and len(k) > 3]
        if len(substring_matches) == 1:
            # Single match is acceptable
            mech_data = self._mechanism_dict[substring_matches[0]]
            result = MechanismResolution(
                raw_text=raw_intervention,
                normalized_text=raw_intervention,
                mechanism_class=mech_data.get("mechanism_class"),
                modality=mech_data.get("modality"),
                target=mech_data.get("target"),
                confidence=0.85,
                resolution_status="resolved",
                source_refs=[],
                warnings=["substring match, not exact"],
            )
            self._cache[cache_key] = result
            return result
        elif len(substring_matches) > 1:
            # Multiple matches = ambiguous
            warnings.append(f"Ambiguous mechanism: matches {len(substring_matches)} phrases")
            result = MechanismResolution(
                raw_text=raw_intervention,
                confidence=0.0,
                resolution_status="ambiguous",
                warnings=warnings,
            )
            self._cache[cache_key] = result
            return result

        # Unknown
        warnings.append("Mechanism/modality not found in dictionary")
        result = MechanismResolution(
            raw_text=raw_intervention,
            confidence=0.0,
            resolution_status="unknown",
            warnings=warnings,
        )
        self._cache[cache_key] = result
        return result

    def bulk_normalize(self, interventions: list[str]) -> list[MechanismResolution]:
        """Normalize multiple interventions.

        Args:
            interventions: List of intervention texts.

        Returns:
            List of MechanismResolutions in same order.
        """
        return [self.normalize(text) for text in interventions]

    @classmethod
    def from_csv(cls, csv_path: Path, as_of_date: str = "") -> "MechanismNormalizer":
        """Load mechanism aliases from CSV file.

        CSV format:
        raw_text,mechanism_class,target,modality,confidence,notes

        Args:
            csv_path: Path to CSV file.
            as_of_date: Date for records.

        Returns:
            Initialized MechanismNormalizer with aliases loaded.
        """
        normalizer = cls(as_of_date=as_of_date)

        if not csv_path.exists():
            return normalizer

        try:
            import csv

            with open(csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_text = row.get("raw_text", "").strip()
                    if not raw_text or raw_text.startswith("#"):
                        continue

                    normalizer.mechanism_aliases[raw_text.lower()] = {
                        "mechanism_class": row.get("mechanism_class"),
                        "target": row.get("target"),
                        "modality": row.get("modality"),
                        "confidence": float(row.get("confidence", 0.95)),
                        "source_refs": [str(csv_path)],
                    }
        except Exception as e:
            print(f"Warning: Failed to load mechanism aliases from {csv_path}: {e}")

        return normalizer
