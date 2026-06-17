"""Schemas for scientific cartography records."""

from scientific_cartography.schemas.asset_schema import AssetRecord
from scientific_cartography.schemas.company_schema import CompanyRecord
from scientific_cartography.schemas.disease_schema import DiseaseRecord
from scientific_cartography.schemas.program_schema import ProgramRecord
from scientific_cartography.schemas.trial_schema import TrialRecord

__all__ = [
    "CompanyRecord",
    "AssetRecord",
    "TrialRecord",
    "DiseaseRecord",
    "ProgramRecord",
]
