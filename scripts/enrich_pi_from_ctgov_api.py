#!/usr/bin/env python3
"""Enrich PI data by fetching overallOfficials from CT.gov API v2.

Fetches study-level PI names from CT.gov for NCT IDs not covered by AACT
facility_investigators.txt, and writes a supplementary PI index.

Usage:
    python3 scripts/enrich_pi_from_ctgov_api.py \
        --trial-records production_data/trial_records.json \
        --aact-dir aact/ \
        --out data/caches/pi_features/ctgov_api_pi_supplement.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.pi_features import load_facility_investigators, normalize_pi_name

CTGOV_API_BASE = "https://clinicaltrials.gov/api/v2"
BATCH_SIZE = 20  # NCT IDs per request (URL length safe)
RATE_LIMIT_SEC = 0.25  # ~4 req/sec, conservative


def _fetch_batch_officials(nct_ids: list[str]) -> dict[str, list[str]]:
    """Fetch overallOfficials PIs for a batch of NCT IDs.

    Returns dict: nct_id → list of PI names (raw).
    """
    params = {
        "query.id": ",".join(nct_ids),
        "fields": (
            "protocolSection.identificationModule.nctId," "protocolSection.contactsLocationsModule.overallOfficials"
        ),
        "pageSize": str(len(nct_ids)),
        "format": "json",
    }
    url = f"{CTGOV_API_BASE}/studies?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  WARN: batch fetch failed: {e}", file=sys.stderr)
        return {}

    result: dict[str, list[str]] = {}
    for study in data.get("studies", []):
        p = study.get("protocolSection", {})
        nct = p.get("identificationModule", {}).get("nctId", "")
        if not nct:
            continue
        clm = p.get("contactsLocationsModule", {})
        officials = clm.get("overallOfficials", [])
        pis = [o["name"] for o in officials if o.get("role") == "PRINCIPAL_INVESTIGATOR" and o.get("name")]
        if pis:
            result[nct] = pis

    return result


def main():
    parser = argparse.ArgumentParser(description="Enrich PI data from CT.gov API v2 overallOfficials")
    parser.add_argument("--trial-records", default="production_data/trial_records.json")
    parser.add_argument("--aact-dir", default="aact/")
    parser.add_argument("--out", default="data/caches/pi_features/ctgov_api_pi_supplement.json")
    args = parser.parse_args()

    # Load existing AACT PI index
    fi_path = Path(args.aact_dir) / "facility_investigators.txt"
    print(f"Loading AACT PI index from {fi_path}...")
    aact_pi = load_facility_investigators(fi_path)
    print(f"  {len(aact_pi)} trials in AACT")

    # Load trial records
    print(f"Loading trial records from {args.trial_records}...")
    with open(args.trial_records) as f:
        trials = json.load(f)
    all_ncts = list({t["nct_id"] for t in trials if t.get("nct_id")})
    print(f"  {len(all_ncts)} unique NCT IDs")

    # Find NCTs missing from AACT
    missing = [n for n in all_ncts if n not in aact_pi]
    print(f"  {len(missing)} missing from AACT → fetching from API")

    # Batch fetch
    api_pi: dict[str, list[str]] = {}
    n_batches = (len(missing) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        result = _fetch_batch_officials(batch)
        api_pi.update(result)

        if batch_num % 100 == 0 or batch_num == n_batches:
            print(f"  Batch {batch_num}/{n_batches}: " f"{len(api_pi)} trials with PI so far")

        time.sleep(RATE_LIMIT_SEC)

    print(f"\nAPI fetch complete: {len(api_pi)} trials with overallOfficials PI")

    # Build supplement index: nct_id → list of (normalized_name, role)
    supplement: dict[str, list[list[str]]] = {}
    unique_pis = set()
    for nct_id, raw_names in api_pi.items():
        entries = []
        for raw in raw_names:
            norm = normalize_pi_name(raw)
            if norm:
                entries.append([norm, "PRINCIPAL_INVESTIGATOR"])
                unique_pis.add(norm)
        if entries:
            supplement[nct_id] = entries

    print(f"  {len(supplement)} trials in supplement")
    print(f"  {len(unique_pis)} unique normalized PI names")

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "schema": "ctgov_api_pi_supplement.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "CT.gov API v2 overallOfficials",
        "n_trials_fetched": len(missing),
        "n_trials_with_pi": len(supplement),
        "n_unique_pis": len(unique_pis),
        "supplement": supplement,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, sort_keys=True)
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
