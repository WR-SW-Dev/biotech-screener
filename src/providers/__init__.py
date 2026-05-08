"""
Data providers for Wake Robin Biotech Alpha System.

Provider architecture follows the factory pattern with PIT boundary enforcement.
All providers return data that is already PIT-safe, so downstream modules
can remain pure and deterministic.
"""

from .aact_provider import AACTClinicalTrialsProvider
from .protocols import ClinicalTrialsProvider, ProviderResult, TrialDiff, TrialRow
from .stub_provider import StubClinicalTrialsProvider

__all__ = [
    "ClinicalTrialsProvider",
    "TrialRow",
    "TrialDiff",
    "ProviderResult",
    "AACTClinicalTrialsProvider",
    "StubClinicalTrialsProvider",
]
