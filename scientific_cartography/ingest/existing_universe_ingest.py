"""Ingest existing screener universe from local cache-only sources."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Optional

from scientific_cartography.schemas.company_schema import CompanyRecord


class ExistingUniverseIngest:
    """Read screener universe from local cache/snapshot files."""

    def __init__(self, as_of_date: str = ""):
        """Initialize ingester.

        Args:
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def _make_company_id(self, ticker: Optional[str], company_name: Optional[str]) -> str:
        """Create stable company ID from ticker or company name."""
        if ticker:
            return f"COMPANY_TICKER_{ticker.upper()}"

        if company_name:
            normalized = company_name.lower().strip()
            hash_hex = hashlib.sha256(normalized.encode()).hexdigest()[:16]
            return f"COMPANY_{hash_hex}"

        return f"COMPANY_UNKNOWN_{hash([company_name, ticker])}"

    def ingest_from_csv(self, csv_path: Path) -> list[CompanyRecord]:
        """Ingest universe from CSV with ticker/company columns.

        Expected columns: ticker, company (name), cik (optional)

        Args:
            csv_path: Path to CSV file.

        Returns:
            List of CompanyRecords.
        """
        records = []
        if not csv_path.exists():
            return records

        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                seen = set()

                for row in reader:
                    ticker = row.get("ticker", "").strip() if row.get("ticker") else None
                    company = row.get("company", "").strip() if row.get("company") else None
                    cik = row.get("cik", "").strip() if row.get("cik") else None

                    # Skip if no identifying information
                    if not (ticker or company):
                        continue

                    # Deduplicate by ticker
                    key = ticker or company
                    if key.lower() in seen:
                        continue
                    seen.add(key.lower())

                    company_id = self._make_company_id(ticker, company)
                    record = CompanyRecord(
                        company_id=company_id,
                        ticker=ticker,
                        company_name=company or ticker or "Unknown",
                        cik=cik,
                        is_public=bool(ticker),
                        as_of_date=self.as_of_date,
                        source_refs=[str(csv_path)],
                        confidence=0.95 if (ticker and company) else 0.85,
                    )
                    records.append(record)

        except Exception as e:
            print(f"Warning: Failed to ingest universe from {csv_path}: {e}")

        return records

    def ingest_from_json(self, json_path: Path) -> list[CompanyRecord]:
        """Ingest universe from JSON array of company objects.

        Expected structure: [{"ticker": "...", "company": "...", "cik": "..."}, ...]

        Args:
            json_path: Path to JSON file.

        Returns:
            List of CompanyRecords.
        """
        records = []
        if not json_path.exists():
            return records

        try:
            with open(json_path) as f:
                data = json.load(f)

            if not isinstance(data, list):
                return records

            seen = set()

            for item in data:
                if not isinstance(item, dict):
                    continue

                ticker = item.get("ticker", "").strip() if item.get("ticker") else None
                company = item.get("company", "").strip() if item.get("company") else None
                cik = item.get("cik", "").strip() if item.get("cik") else None

                if not (ticker or company):
                    continue

                key = (ticker or company).lower()
                if key in seen:
                    continue
                seen.add(key)

                company_id = self._make_company_id(ticker, company)
                record = CompanyRecord(
                    company_id=company_id,
                    ticker=ticker,
                    company_name=company or ticker or "Unknown",
                    cik=cik,
                    is_public=bool(ticker),
                    as_of_date=self.as_of_date,
                    source_refs=[str(json_path)],
                    confidence=0.95 if (ticker and company) else 0.85,
                )
                records.append(record)

        except Exception as e:
            print(f"Warning: Failed to ingest universe from {json_path}: {e}")

        return records

    def ingest_from_rankings_csv(self, csv_path: Path) -> list[CompanyRecord]:
        """Ingest from standard rankings.csv format.

        Looks for ticker column and derives company info.

        Args:
            csv_path: Path to rankings.csv.

        Returns:
            List of CompanyRecords.
        """
        records = []
        if not csv_path.exists():
            return records

        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                seen = set()

                for row in reader:
                    ticker = row.get("ticker", "").strip() if row.get("ticker") else None

                    if not ticker:
                        continue

                    if ticker.lower() in seen:
                        continue
                    seen.add(ticker.lower())

                    company_id = self._make_company_id(ticker, None)
                    record = CompanyRecord(
                        company_id=company_id,
                        ticker=ticker,
                        company_name=ticker,  # Use ticker as fallback name
                        is_public=True,
                        as_of_date=self.as_of_date,
                        source_refs=[str(csv_path)],
                        confidence=0.80,  # Lower confidence without company name
                    )
                    records.append(record)

        except Exception as e:
            print(f"Warning: Failed to ingest from {csv_path}: {e}")

        return records
