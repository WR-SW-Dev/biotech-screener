"""
Null out IR URLs that were assigned to wrong companies in the GNW Pass 2 discovery run.
Run after populate_ir_sources.py (no --dry-run) has written to company_ir_sources.json.
"""

import json

BAD_TICKERS = {
    "ABCL",  # got preludetx.com -- AbCellera != Prelude
    "ARWR",  # got royaltypharma.com -- Arrowhead != Royalty Pharma
    "BRKR",  # got dragonflyenergy.com -- Bruker != Dragonfly Energy
    "ILMN",  # got standardbio.com -- Illumina != Standard BioTools
    "LGND",  # got orchestrabiomed.com -- Ligand != Orchestra BioMed
    "MEDP",  # got bfalaw.com -- Medpace != BFA Law
    "OABI",  # got voyageracq.com -- OcuSense/OABI != Voyage Acquisition
    "TEM",  # got temenos.com -- Tempus AI != Temenos (bank software)
    "ZLAB",  # got pomlaw.com -- Zymeworks != Pomerantz Law
    "NBP",  # got novabridge.com -- NovaBay Pharma != NovaBridge
    "GHRS",  # got www.ghrs.com (domain root only, no IR path)
}

src = "production_data/company_ir_sources.json"
with open(src) as f:
    data = json.load(f)

nulled = []
skipped = []
for entry in data:
    ticker = entry.get("ticker", "")
    if ticker in BAD_TICKERS:
        old = entry.get("company_ir_url", "")
        if old:
            entry["company_ir_url"] = ""
            nulled.append((ticker, old))
        else:
            skipped.append(ticker)

with open(src, "w") as f:
    json.dump(data, f, indent=2)

print(f"Nulled {len(nulled)} entries:")
for ticker, old_url in sorted(nulled):
    print(f"  {ticker:<8}  was: {old_url}")
if skipped:
    print(f"Skipped (already empty): {skipped}")
