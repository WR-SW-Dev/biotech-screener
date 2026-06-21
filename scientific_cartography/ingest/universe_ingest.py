"""Ingest the biotech screener universe CSV (tickers + company names).

This is the Phase 2 universe ingester. It reads the canonical
``data/universe/biotech_universe_v1.csv`` file (columns: ``ticker,name,sector``)
and returns ``CompanyRecord`` objects that downstream builders use to resolve
sponsors.

The ingester is deliberately tolerant of column-name variants so it also works
with the legacy ``ticker,company,cik`` schema used by ``ExistingUniverseIngest``.
It is fully cache-only: no network access, no live API calls.
"""

import csv
import hashlib
from pathlib import Path
from typing import Optional

from scientific_cartography.schemas.company_schema import CompanyRecord


class UniverseIngest:
    """Load the screener universe from a local CSV file.

    The universe CSV is the point-in-time investable set for a given
    ``as_of_date``. Each row yields one ``CompanyRecord`` carrying the ticker,
    the company name, and provenance (``source_refs``, ``as_of_date``).
    """

    # Sector labels that are too generic to be treated as a company name.
    GENERIC_NAMES = {"healthcare", "biotechnology", "biotech", "unknown", ""}

    def __init__(self, as_of_date: str = ""):
        """Initialize ingester.

        Args:
            as_of_date: Date stamp applied to every record (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def _make_company_id(self, ticker: Optional[str], company_name: Optional[str]) -> str:
        """Create a stable company ID from ticker or company name."""
        if ticker:
            return f"COMPANY_TICKER_{ticker.upper()}"
        if company_name:
            normalized = company_name.lower().strip()
            hash_hex = hashlib.sha256(normalized.encode()).hexdigest()[:16]
            return f"COMPANY_{hash_hex}"
        return "COMPANY_UNKNOWN"

    def _resolve_name(self, row: dict) -> Optional[str]:
        """Pick the best company name from a CSV row.

        Tries ``name`` first (the v1 universe schema), then ``company`` and
        ``company_name`` for compatibility with other screener CSVs. Generic
        sector labels are skipped so we never store "Biotechnology" as a name.
        """
        for key in ("name", "company", "company_name"):
            value = row.get(key)
            if not value:
                continue
            cleaned = str(value).strip()
            if cleaned.lower() in self.GENERIC_NAMES:
                continue
            return cleaned
        return None

    def ingest(self, csv_path: Path) -> list[CompanyRecord]:
        """Ingest the universe CSV into CompanyRecords.

        Args:
            csv_path: Path to the universe CSV file.

        Returns:
            List of CompanyRecords, deduplicated by ticker (case-insensitive).
            Missing files yield an empty list (cache-only, never raises).
        """
        records: list[CompanyRecord] = []
        if not csv_path.exists():
            return records

        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                seen: set[str] = set()
                for row in reader:
                    ticker = (row.get("ticker") or "").strip() or None
                    name = self._resolve_name(row)
                    cik = (row.get("cik") or "").strip() or None
                    sector = (row.get("sector") or "").strip() or None

                    if not (ticker or name):
                        continue

                    dedupe_key = (ticker or name).lower()
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    company_id = self._make_company_id(ticker, name)
                    company_name = name or ticker or "Unknown"
                    # Confidence: full when we have both a ticker and a real
                    # name; lower when we only have one identifier.
                    confidence = 0.95 if (ticker and name) else 0.85

                    record = CompanyRecord(
                        company_id=company_id,
                        company_name=company_name,
                        ticker=ticker,
                        cik=cik,
                        is_public=bool(ticker),
                        as_of_date=self.as_of_date,
                        source_refs=[str(csv_path)],
                        confidence=confidence,
                    )
                    if sector:
                        # Re-use the aliases slot to carry the sector through
                        # without extending the schema. Sponsors keep their
                        # canonical name in company_name.
                        record.aliases = [sector]
                    records.append(record)
        except Exception as e:  # pragma: no cover - defensive, cache-only
            print(f"Warning: Failed to ingest universe from {csv_path}: {e}")

        return records
