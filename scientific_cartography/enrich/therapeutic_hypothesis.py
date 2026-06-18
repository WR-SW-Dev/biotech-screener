"""Generate therapeutic hypotheses by combining Open Targets + ChEMBL.

A therapeutic hypothesis links:
1. Company asset (mechanism, modality, target)
2. Disease context (MONDO ID, therapeutic area)
3. Target–disease evidence (Open Targets association score)
4. Competitive precedent (approved/clinical drugs in ChEMBL)
5. Mechanism maturity (has credible precedent?)

Transforms: "Company X has a JAK inhibitor in atopic dermatitis"
Into: "Company X targets JAK1 (88% association with AD per OT),
       with filgotinib/baricitinib precedent (both Phase 4 in RA/AD)
       and high mechanism maturity (JAK inhibition is established in
       Th2 inflammation)."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from scientific_cartography.enrich.chembl_enricher import ChEMBLCompound, ChEMBLEnricher
from scientific_cartography.enrich.open_targets_enricher import OpenTargetsEnricher, TargetDiseaseAssociation


@dataclass
class TherapeuticHypothesis:
    """Complete therapeutic hypothesis linking mechanism to disease evidence."""

    company_name: str
    """Company developing the asset."""

    asset_name: str
    """Asset/compound name."""

    target_symbols: list[str]
    """Primary target(s) (e.g., ['JAK1', 'TYK2'])."""

    mechanism_class: str
    """Mechanism (e.g., JAK1 inhibitor)."""

    disease_id: str
    """Mondo disease ID (e.g., MONDO:0004980)."""

    disease_name: str
    """Disease name (e.g., atopic dermatitis)."""

    target_disease_evidence: list[TargetDiseaseAssociation] = field(default_factory=list)
    """Open Targets associations for each target."""

    precedent_drugs: list[ChEMBLCompound] = field(default_factory=list)
    """ChEMBL drugs with same mechanism in same/related disease."""

    mechanism_maturity_score: float = 0.0
    """Score 0.0–1.0 based on precedent and evidence."""

    confidence: float = 0.0
    """Overall hypothesis confidence (0.0–1.0)."""

    therapeutic_hypothesis_text: str = ""
    """Human-readable hypothesis statement."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "company_name": self.company_name,
            "asset_name": self.asset_name,
            "target_symbols": self.target_symbols,
            "mechanism_class": self.mechanism_class,
            "disease_id": self.disease_id,
            "disease_name": self.disease_name,
            "target_disease_evidence": [e.to_dict() for e in self.target_disease_evidence],
            "precedent_drugs": [d.to_dict() for d in self.precedent_drugs],
            "mechanism_maturity_score": round(self.mechanism_maturity_score, 4),
            "confidence": round(self.confidence, 4),
            "therapeutic_hypothesis_text": self.therapeutic_hypothesis_text,
        }


class TherapeuticHypothesisGenerator:
    """Generate therapeutic hypotheses from program + target/disease data.

    Combines:
    - Open Targets: target–disease associations (0.0–1.0 score)
    - ChEMBL: precedent drugs, mechanism maturity, clinical phase
    - Program data: company, asset, mechanism, targets
    """

    def __init__(self, as_of_date: str = ""):
        """Initialize hypothesis generator.

        Args:
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date
        self.open_targets = OpenTargetsEnricher(as_of_date=as_of_date)
        self.chembl = ChEMBLEnricher(as_of_date=as_of_date)

    def generate(
        self,
        company_name: str,
        asset_name: str,
        mechanism_class: str,
        target_symbols: list[str],
        disease_id: str,
        disease_name: str,
    ) -> TherapeuticHypothesis:
        """Generate a therapeutic hypothesis.

        Args:
            company_name: Company name.
            asset_name: Asset name.
            mechanism_class: Mechanism (e.g., JAK1 inhibitor).
            target_symbols: List of gene symbols.
            disease_id: Mondo disease ID.
            disease_name: Disease name.

        Returns:
            TherapeuticHypothesis with evidence and precedent.
        """
        # 1. Fetch Open Targets evidence for each target
        ot_evidence = []
        avg_ot_score = 0.0

        for target in target_symbols:
            assoc = self.open_targets.lookup(target, disease_id)
            if assoc:
                ot_evidence.append(assoc)
                avg_ot_score += assoc.association_score

        if ot_evidence:
            avg_ot_score /= len(ot_evidence)

        # 2. Fetch ChEMBL precedent for each target
        precedent_drugs = []
        for target in target_symbols:
            drugs = self.chembl.lookup_by_target(target)
            precedent_drugs.extend(drugs)

        # 3. Score mechanism maturity
        mechanism_maturity = self._score_mechanism_maturity(target_symbols, precedent_drugs, avg_ot_score)

        # 4. Compute overall confidence
        confidence = min(
            [
                avg_ot_score,  # Target-disease evidence
                mechanism_maturity,  # Precedent + maturity
                0.95,  # Cap at 0.95 (never 100%)
            ]
        )

        # 5. Generate hypothesis text
        hypothesis_text = self._generate_hypothesis_text(
            company_name,
            asset_name,
            mechanism_class,
            target_symbols,
            disease_name,
            avg_ot_score,
            precedent_drugs,
        )

        return TherapeuticHypothesis(
            company_name=company_name,
            asset_name=asset_name,
            target_symbols=target_symbols,
            mechanism_class=mechanism_class,
            disease_id=disease_id,
            disease_name=disease_name,
            target_disease_evidence=ot_evidence,
            precedent_drugs=precedent_drugs,
            mechanism_maturity_score=mechanism_maturity,
            confidence=confidence,
            therapeutic_hypothesis_text=hypothesis_text,
        )

    def _score_mechanism_maturity(
        self,
        targets: list[str],
        precedent_drugs: list[ChEMBLCompound],
        ot_score: float,
    ) -> float:
        """Score mechanism maturity based on precedent and evidence.

        Returns 0.0–1.0:
        - 0.9–1.0: Approved drugs exist for mechanism
        - 0.7–0.9: Clinical-stage drugs exist
        - 0.5–0.7: Preclinical precedent, strong OT evidence
        - <0.5: Weak precedent or weak evidence
        """
        if not targets or not precedent_drugs:
            # No precedent: rely on OT evidence alone
            return max(0.3, ot_score * 0.7)

        # Check max phase of precedent drugs
        max_phase = max((d.max_phase for d in precedent_drugs), default=0)

        # Score based on precedent + evidence
        precedent_score = {
            4: 0.95,  # Approved drugs exist
            3: 0.85,  # Phase 3 drugs exist
            2: 0.75,  # Phase 2 drugs exist
            1: 0.60,  # Phase 1 drugs exist
            0: 0.40,  # Only preclinical
        }.get(max_phase, 0.40)

        # Blend precedent with OT evidence
        maturity = 0.6 * precedent_score + 0.4 * ot_score
        return min(0.95, max(0.3, maturity))

    def _generate_hypothesis_text(
        self,
        company: str,
        asset: str,
        mechanism: str,
        targets: list[str],
        disease: str,
        ot_score: float,
        precedent: list[ChEMBLCompound],
    ) -> str:
        """Generate human-readable hypothesis statement.

        Example:
        "Company X develops [asset] targeting JAK1/TYK2 in atopic dermatitis.
        JAK1 shows 88% target-disease association per Open Targets genetic/pathway
        evidence. Filgotinib (JAK1i, Phase 4 in RA) and baricitinib (JAK1/2i, Phase 4
        in RA/AD) demonstrate mechanism maturity. High hypothesis confidence."
        """
        target_str = "/".join(targets)
        precedent_str = ""

        if precedent:
            drugs = [
                f"{d.molecule_name} ({d.mechanism_of_action}, Phase {d.max_phase})"
                for d in sorted(precedent, key=lambda x: -x.max_phase)[:3]
            ]
            precedent_str = f" Known precedent: {'; '.join(drugs)}."

        hypothesis = (
            f"{company} develops {asset} targeting {target_str} in {disease}. "
            f"Target-disease association: {round(100*ot_score)}% per Open Targets "
            f"(genetic/pathway evidence).{precedent_str} "
            f"Hypothesis confidence: {'high' if ot_score >= 0.8 else 'moderate' if ot_score >= 0.6 else 'low'}."
        )

        return hypothesis
