"""
scientific_cartography - Read-only scientific context layer for biotech screener.

Maps the investable biotech universe by disease, mechanism, asset, stage, evidence,
competitive context, and inflection points.

GOVERNANCE:
- READ_ONLY_DIAGNOSTIC mode
- NO_RANKER_CHANGE, NO_SELECTOR_CHANGE, NO_SIZING_CHANGE
- POINT_IN_TIME_SAFE_REQUIRED
- NO_ALPHA_PROMOTION
"""

from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.normalize.mechanism_normalizer import MechanismNormalizer
from scientific_cartography.normalize.stage_normalizer import StageNormalizer
from scientific_cartography.schemas.disease_schema import DiseaseRecord
from scientific_cartography.schemas.program_schema import ProgramRecord

__all__ = [
    "DiseaseNormalizer",
    "MechanismNormalizer",
    "StageNormalizer",
    "DiseaseRecord",
    "ProgramRecord",
]
