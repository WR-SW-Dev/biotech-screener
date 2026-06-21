"""Shared normalization constants for scientific cartography."""

GENERIC_COMPANY_NAMES = {"healthcare", "biotechnology", "biotech", "unknown"}

GENERIC_NORMALIZED_NAMES = {
    "therapeutics",
    "pharmaceuticals",
    "biosciences",
    "biotech",
    "biopharm",
    "company",
    "corporation",
}

CORPORATE_SUFFIX_PATTERNS = [
    r",\s*incorporated\s*$",
    r",\s*inc\.?\s*$",
    r",\s*corporation\s*$",
    r",\s*corp\.?\s*$",
    r",\s*limited\s*$",
    r",\s*ltd\.?\s*$",
    r"\s+incorporated\s*$",
    r"\s+inc\.?\s*$",
    r"\s+corporation\s*$",
    r"\s+corp\.?\s*$",
    r"\s+limited\s*$",
    r"\s+ltd\.?\s*$",
    r"\s+limited\s+liability\s+company\s*$",
    r"\s+llc\s*$",
    r"\s+therapeutics\s*$",
    r"\s+pharmaceuticals\s*$",
    r"\s+biosciences\s*$",
    r"\s+biotech\s*$",
    r"\s+biopharm\s*$",
    r"\s+plc\s*$",
    r"\s+s\.?a\.?\s*$",
    r"\s+se\s*$",
    r"\s+ag\s*$",
    r"\s+n\.?v\.?\s*$",
    r"\s+gmbh\s*$",
]

SOURCE_PRIORITY = {
    "sec": 1,
    "sec_filing": 1,
    "investor_deck": 2,
    "deck": 2,
    "ctgov": 3,
    "fda": 4,
    "fda_label": 4,
    "open_targets": 5,
    "chembl": 6,
    "pubmed": 7,
    "manual": 8,
    "manual_override": 8,
}
